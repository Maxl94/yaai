import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.schemas.project import ProjectRead, ProjectRole
from yaai.server.models.auth import ServiceAccount, User
from yaai.server.models.model import Model
from yaai.server.models.project import DEFAULT_PROJECT_NAME, Project, ProjectMembership
from yaai.server.schemas.project import (
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberRead,
    ProjectUpdate,
)

logger = logging.getLogger(__name__)

RESERVED_NAME_DETAIL = f"The project name '{DEFAULT_PROJECT_NAME}' is reserved for the default project"
SA_OWNER_DETAIL = "Service accounts cannot be project owners; use the editor role"


async def get_or_create_default_project(db: AsyncSession) -> Project:
    """Return the "default" project, creating it if it does not exist yet.

    The migration creates it; on-demand creation covers fresh databases created without migrations
    (tests) and a default project that was deleted from the database manually.
    """
    project = (await db.execute(select(Project).where(Project.name == DEFAULT_PROJECT_NAME))).scalar_one_or_none()
    if project is not None:
        return project
    db.add(Project(name=DEFAULT_PROJECT_NAME, description="Default project"))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()  # created concurrently by another request
    return (await db.execute(select(Project).where(Project.name == DEFAULT_PROJECT_NAME))).scalar_one()


class ProjectService:
    """Project CRUD and membership management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: uuid.UUID) -> Project:
        """Fetch a project by ID, raising 404 if it does not exist."""
        project = await self.db.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    async def to_read(self, projects: list[Project], roles: dict[uuid.UUID, ProjectRole] | None) -> list[ProjectRead]:
        """Build API objects with model counts.

        Args:
            projects: Projects to convert.
            roles: Role of the caller per project ID; None means the caller is a global owner.
        """
        counts = dict(
            (
                await self.db.execute(
                    select(Model.project_id, func.count())
                    .where(Model.project_id.in_([p.id for p in projects]))
                    .group_by(Model.project_id)
                )
            )
            .tuples()
            .all()
        )
        return [
            ProjectRead(
                id=p.id,
                name=p.name,
                description=p.description,
                is_default=p.name == DEFAULT_PROJECT_NAME,
                model_count=counts.get(p.id, 0),
                my_role=ProjectRole.OWNER if roles is None else roles.get(p.id),
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
            for p in projects
        ]

    async def list_projects(self, project_ids: list[uuid.UUID] | None = None) -> list[Project]:
        """List projects ordered by name, optionally restricted to the given IDs."""
        query = select(Project).order_by(Project.name)
        if project_ids is not None:
            query = query.where(Project.id.in_(project_ids))
        return list((await self.db.execute(query)).scalars().all())

    async def create_project(self, data: ProjectCreate) -> Project:
        """Create a project, raising 409 if the name is taken or reserved for the default project."""
        if data.name == DEFAULT_PROJECT_NAME:
            raise HTTPException(status_code=409, detail=RESERVED_NAME_DETAIL)
        project = Project(name=data.name, description=data.description)
        self.db.add(project)
        await self._commit_unique(project, "Project with this name already exists")
        return project

    async def update_project(self, project_id: uuid.UUID, data: ProjectUpdate) -> Project:
        """Partially update name and/or description. The default project cannot be renamed or taken over."""
        project = await self.get_project(project_id)
        if data.name is not None and data.name != project.name:
            if project.name == DEFAULT_PROJECT_NAME:
                raise HTTPException(status_code=409, detail="The default project cannot be renamed")
            if data.name == DEFAULT_PROJECT_NAME:
                raise HTTPException(status_code=409, detail=RESERVED_NAME_DETAIL)
            project.name = data.name
        if data.description is not None:
            project.description = data.description
        await self._commit_unique(project, "Project with this name already exists")
        return project

    async def delete_project(self, project_id: uuid.UUID) -> None:
        """Delete an empty project (memberships are removed with it).

        Raises:
            HTTPException: 404 if unknown, 409 for the default project or a project that still contains models.
        """
        project = await self.get_project(project_id)
        if project.name == DEFAULT_PROJECT_NAME:
            raise HTTPException(status_code=409, detail="The default project cannot be deleted")
        model_count = (
            await self.db.execute(select(func.count()).select_from(Model).where(Model.project_id == project_id))
        ).scalar_one()
        if model_count:
            raise HTTPException(
                status_code=409,
                detail=f"Project still contains {model_count} model(s); move or delete them first",
            )
        await self.db.delete(project)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()  # a model was added concurrently (RESTRICT foreign key)
            raise HTTPException(
                status_code=409, detail="Project still contains models; move or delete them first"
            ) from None

    async def list_members(self, project_id: uuid.UUID) -> list[ProjectMemberRead]:
        """List the members (users and service accounts) of a project."""
        rows = (
            await self.db.execute(
                select(ProjectMembership, User, ServiceAccount)
                .outerjoin(User, ProjectMembership.user_id == User.id)
                .outerjoin(ServiceAccount, ProjectMembership.service_account_id == ServiceAccount.id)
                .where(ProjectMembership.project_id == project_id)
                .order_by(ProjectMembership.created_at)
            )
        ).all()
        return [self._member_read(m, user, sa) for m, user, sa in rows]

    async def add_member(self, project_id: uuid.UUID, data: ProjectMemberCreate) -> ProjectMemberRead:
        """Add a user or service account to a project.

        Raises:
            HTTPException: 404 if the principal does not exist, 409 if it already is a member.
        """
        user = sa = None
        if data.service_account_id is not None:
            sa = await self.db.get(ServiceAccount, data.service_account_id)
            if sa is None:
                raise HTTPException(status_code=404, detail="Service account not found")
        else:
            user = await self._find_user(data)
        membership = ProjectMembership(
            project_id=project_id,
            user_id=user.id if user else None,
            service_account_id=sa.id if sa else None,
            role=data.role,
        )
        self.db.add(membership)
        await self._commit_unique(membership, "Already a member of this project")
        return self._member_read(membership, user, sa)

    async def update_member_role(
        self, project_id: uuid.UUID, membership_id: uuid.UUID, role: ProjectRole, *, guard_last_owner: bool = False
    ) -> ProjectMemberRead:
        """Change a member's role.

        Args:
            project_id: Project the membership must belong to.
            membership_id: Membership to change.
            role: New role.
            guard_last_owner: Reject demoting the last project owner (set for callers that are not global owners).

        Raises:
            HTTPException: 404 if the membership is not part of the project, 422 for an owner service account,
                409 if the last owner would be demoted.
        """
        membership = await self._get_membership(project_id, membership_id)
        if role == ProjectRole.OWNER and membership.service_account_id is not None:
            raise HTTPException(status_code=422, detail=SA_OWNER_DETAIL)
        if guard_last_owner and role != ProjectRole.OWNER:
            await self._ensure_not_last_owner(membership)
        membership.role = role
        await self.db.commit()
        return await self._read_member(membership)

    async def remove_member(
        self, project_id: uuid.UUID, membership_id: uuid.UUID, *, guard_last_owner: bool = False
    ) -> None:
        """Remove a member.

        Raises:
            HTTPException: 404 if the membership is not part of the project, 409 if ``guard_last_owner`` is set
                and the last project owner would be removed.
        """
        membership = await self._get_membership(project_id, membership_id)
        if guard_last_owner:
            await self._ensure_not_last_owner(membership)
        await self.db.delete(membership)
        await self.db.commit()

    async def _ensure_not_last_owner(self, membership: ProjectMembership) -> None:
        if membership.role != ProjectRole.OWNER:
            return
        owner_count = (
            await self.db.execute(
                select(func.count())
                .select_from(ProjectMembership)
                .where(
                    ProjectMembership.project_id == membership.project_id, ProjectMembership.role == ProjectRole.OWNER
                )
            )
        ).scalar_one()
        if owner_count <= 1:
            raise HTTPException(
                status_code=409, detail="The last project owner cannot be removed or demoted by a project owner"
            )

    async def _find_user(self, data: ProjectMemberCreate) -> User:
        stmt = select(User).where(
            User.id == data.user_id if data.user_id is not None else User.username == data.username
        )
        user = (await self.db.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    async def _get_membership(self, project_id: uuid.UUID, membership_id: uuid.UUID) -> ProjectMembership:
        membership = await self.db.get(ProjectMembership, membership_id)
        if membership is None or membership.project_id != project_id:
            raise HTTPException(status_code=404, detail="Membership not found")
        return membership

    async def _read_member(self, membership: ProjectMembership) -> ProjectMemberRead:
        user = await self.db.get(User, membership.user_id) if membership.user_id else None
        sa = await self.db.get(ServiceAccount, membership.service_account_id) if membership.service_account_id else None
        return self._member_read(membership, user, sa)

    @staticmethod
    def _member_read(membership: ProjectMembership, user: User | None, sa: ServiceAccount | None) -> ProjectMemberRead:
        return ProjectMemberRead(
            id=membership.id,
            project_id=membership.project_id,
            principal_type="user" if user else "service_account",
            user_id=membership.user_id,
            service_account_id=membership.service_account_id,
            name=user.username if user else sa.name,
            email=user.email if user else None,
            role=membership.role,
            created_at=membership.created_at,
        )

    async def _commit_unique(self, instance: Project | ProjectMembership, conflict_detail: str) -> None:
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail=conflict_detail) from None
        await self.db.refresh(instance)
