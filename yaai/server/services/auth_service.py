"""Authentication service: user CRUD, login, service accounts."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.server.auth.config import AuthConfig
from yaai.server.auth.jwt import create_access_token, create_refresh_token
from yaai.server.auth.passwords import hash_password, verify_password
from yaai.server.auth.service_auth import hash_api_key
from yaai.server.models.auth import APIKey, AuthProvider, RefreshToken, ServiceAccount, User, UserRole

# Pre-computed bcrypt hash for timing-attack mitigation in authenticate_local().
# This ensures non-existent user lookups take the same time as real ones.
_DUMMY_HASH = "$2b$12$tGcQ/cij2YhgRoc0dzhb3eiC/yDPaI3oMdk270Q88g.twJZ5SA8j."


class AuthService:
    def __init__(self, db: AsyncSession, config: AuthConfig):
        self.db = db
        self.config = config

    # ── User authentication ──────────────────────────────────────────

    async def authenticate_local(self, username: str, password: str) -> User | None:
        """Authenticate a user with username and password."""
        stmt = select(User).where(User.username == username, User.is_active.is_(True))
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None or user.hashed_password is None:
            # Run a dummy bcrypt verify to prevent timing-based user enumeration
            verify_password(password, _DUMMY_HASH)
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    async def create_tokens(self, user: User) -> dict:
        """Create JWT access and refresh tokens for a user, storing refresh token in DB."""
        access = create_access_token(self.config, str(user.id), user.role.value)
        refresh, jti = create_refresh_token(self.config, str(user.id), user.role.value)

        rt = RefreshToken(
            user_id=user.id,
            jti=jti,
            expires_at=datetime.now(UTC) + timedelta(days=self.config.jwt.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        self.db.add(rt)
        await self.db.commit()

        return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}

    # ── User CRUD ────────────────────────────────────────────────────

    async def list_users(self) -> list[User]:
        stmt = select(User).order_by(User.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_user(
        self,
        username: str,
        password: str,
        role: str = "viewer",
        email: str | None = None,
        auth_provider: AuthProvider = AuthProvider.LOCAL,
        google_sub: str | None = None,
    ) -> User:
        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password) if password else None,
            role=UserRole(role),
            auth_provider=auth_provider,
            google_sub=google_sub,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # Explicit allowlist of fields that can be updated via the admin API
    _UPDATABLE_USER_FIELDS = frozenset({"email", "role", "is_active"})

    async def update_user(self, user_id: uuid.UUID, **kwargs) -> User | None:
        user = await self.get_user_by_id(user_id)
        if user is None:
            return None
        was_active = user.is_active
        for key, value in kwargs.items():
            if key not in self._UPDATABLE_USER_FIELDS:
                continue
            if value is not None:
                if key == "role":
                    setattr(user, key, UserRole(value))
                else:
                    setattr(user, key, value)
        await self.db.commit()
        await self.db.refresh(user)

        # Revoke all refresh tokens when a user is deactivated
        if was_active and not user.is_active:
            await self.revoke_all_user_tokens(user_id)

        return user

    async def delete_user(self, user_id: uuid.UUID) -> bool:
        user = await self.get_user_by_id(user_id)
        if user is None:
            return False
        await self.db.delete(user)
        await self.db.commit()
        return True

    async def change_password(self, user: User, new_password: str) -> User:
        user.hashed_password = hash_password(new_password)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # ── Refresh token management ────────────────────────────────────

    async def validate_refresh_token(self, jti: str) -> RefreshToken | None:
        """Look up a refresh token by JTI. Returns None if not found (revoked or expired)."""
        stmt = select(RefreshToken).where(RefreshToken.jti == jti)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_refresh_token(self, jti: str) -> None:
        """Revoke a single refresh token by deleting its DB row."""
        await self.db.execute(delete(RefreshToken).where(RefreshToken.jti == jti))
        await self.db.commit()

    async def revoke_all_user_tokens(self, user_id: uuid.UUID) -> None:
        """Revoke all refresh tokens for a user (e.g. on deactivation)."""
        await self.db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
        await self.db.commit()

    # ── OAuth user management ────────────────────────────────────────

    async def get_or_create_google_user(self, email: str, google_sub: str, name: str | None = None) -> User | None:
        """Find or create a user from Google OAuth. Returns None if access denied."""
        google_cfg = self.config.oauth.google

        # Check allowed domains
        if google_cfg.allowed_domains:
            domain = email.rsplit("@", maxsplit=1)[1].lower() if "@" in email else ""
            allowed_domains = {d.lower() for d in google_cfg.allowed_domains}
            if domain not in allowed_domains:
                return None

        # Resolve role from email lists (None = access denied)
        role = google_cfg.resolve_role(email)
        if role is None:
            return None

        # Try to find by google_sub first
        stmt = select(User).where(User.google_sub == google_sub)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            # Sync role with config on each login
            if user.role != UserRole(role):
                user.role = UserRole(role)
                await self.db.commit()
                await self.db.refresh(user)
            return user

        # Try to find by email and link
        stmt = select(User).where(User.email == email)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            user.google_sub = google_sub
            user.auth_provider = AuthProvider.GOOGLE
            user.role = UserRole(role)
            await self.db.commit()
            await self.db.refresh(user)
            return user

        # Auto-create if enabled
        if not google_cfg.auto_create_users:
            return None

        username = name or email.split("@", maxsplit=1)[0]
        # Ensure unique username
        existing = await self.get_user_by_username(username)
        if existing:
            username = f"{username}_{google_sub[:6]}"

        return await self.create_user(
            username=username,
            password="",
            role=role,
            email=email,
            auth_provider=AuthProvider.GOOGLE,
            google_sub=google_sub,
        )

    # ── Service accounts ─────────────────────────────────────────────

    async def list_service_accounts(self) -> list[ServiceAccount]:
        stmt = select(ServiceAccount).order_by(ServiceAccount.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_service_account(
        self,
        name: str,
        auth_type: str = "api_key",
        description: str | None = None,
        google_sa_email: str | None = None,
        created_by_user_id: uuid.UUID | None = None,
    ) -> tuple[ServiceAccount, str | None]:
        """Create a service account.

        For auth_type='api_key', auto-generates an API key linked to the SA.
        Returns (ServiceAccount, raw_key). raw_key is None for google type.
        """
        sa = ServiceAccount(
            name=name,
            description=description,
            auth_type=auth_type,
            google_sa_email=google_sa_email,
        )
        self.db.add(sa)
        await self.db.flush()  # Get SA id without committing

        raw_key: str | None = None
        if auth_type == "api_key":
            # Auto-create API key for this service account
            raw_key = f"yaam_{secrets.token_urlsafe(32)}"
            key_hash = hash_api_key(raw_key)
            key_prefix = raw_key[:12]

            api_key = APIKey(
                name=f"{name} API Key",
                key_hash=key_hash,
                key_prefix=key_prefix,
                service_account_id=sa.id,
                created_by_user_id=created_by_user_id,
            )
            self.db.add(api_key)

        await self.db.commit()
        await self.db.refresh(sa)
        return sa, raw_key

    async def get_service_account_api_key(self, sa_id: uuid.UUID) -> APIKey | None:
        """Get the API key associated with a service account (if any)."""
        stmt = select(APIKey).where(APIKey.service_account_id == sa_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_service_account(self, sa_id: uuid.UUID) -> bool:
        stmt = select(ServiceAccount).where(ServiceAccount.id == sa_id)
        result = await self.db.execute(stmt)
        sa = result.scalar_one_or_none()
        if sa is None:
            return False
        await self.db.delete(sa)
        await self.db.commit()
        return True

    # ── API keys (internal, for service accounts) ────────────────────

    async def regenerate_api_key(
        self,
        sa_id: uuid.UUID,
        created_by_user_id: uuid.UUID | None = None,
    ) -> tuple[APIKey, str] | None:
        """Regenerate the API key for a service account. Returns new (APIKey, raw_key)."""
        stmt = select(ServiceAccount).where(ServiceAccount.id == sa_id)
        result = await self.db.execute(stmt)
        sa = result.scalar_one_or_none()
        if sa is None or sa.auth_type != "api_key":
            return None

        # Delete existing key
        del_stmt = select(APIKey).where(APIKey.service_account_id == sa_id)
        del_result = await self.db.execute(del_stmt)
        existing_key = del_result.scalar_one_or_none()
        if existing_key:
            await self.db.delete(existing_key)

        # Create new key
        raw_key = f"yaam_{secrets.token_urlsafe(32)}"
        key_hash = hash_api_key(raw_key)
        key_prefix = raw_key[:12]

        api_key = APIKey(
            name=f"{sa.name} API Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            service_account_id=sa_id,
            created_by_user_id=created_by_user_id,
        )
        self.db.add(api_key)
        await self.db.commit()
        await self.db.refresh(api_key)
        return api_key, raw_key
