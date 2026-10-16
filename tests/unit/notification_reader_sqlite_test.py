"""Per-reader notification read state on the SQLite dialect (INSERT ... SELECT ... ON CONFLICT DO NOTHING)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.server.models.auth import AuthProvider, User, UserRole
from yaai.server.models.job import Notification, NotificationReadReceipt, NotificationSeverity
from yaai.server.models.model import Model, ModelVersion
from yaai.server.services.job_service import JobService, NotificationReader


async def _seed(db: AsyncSession) -> tuple[User, list[Notification]]:
    created = datetime.now(UTC) - timedelta(days=1)
    user = User(username="reader", email="reader@example.com", role=UserRole.VIEWER, auth_provider=AuthProvider.LOCAL)
    model = Model(name="m")
    db.add_all([user, model])
    await db.flush()
    version = ModelVersion(model_id=model.id, version="1")
    db.add(version)
    await db.flush()
    user.created_at = datetime.now(UTC) - timedelta(hours=1)
    notifications = [
        Notification(model_version_id=version.id, severity=NotificationSeverity.WARNING, message=name, created_at=at)
        for name, at in (("old", created), ("new-1", datetime.now(UTC)), ("new-2", datetime.now(UTC)))
    ]
    db.add_all(notifications)
    await db.commit()
    return user, notifications


async def test_mark_all_inserts_only_unread_newer_than_reader(db_session: AsyncSession):
    user, _ = await _seed(db_session)
    reader = NotificationReader("user", user.id, user.created_at)
    svc = JobService(db_session)

    assert await svc.mark_all_notifications_read(reader=reader) == 2
    assert await svc.mark_all_notifications_read(reader=reader) == 0
    count = (await db_session.execute(select(func.count()).select_from(NotificationReadReceipt))).scalar_one()
    assert count == 2


async def test_list_reports_backlog_as_read_and_filters(db_session: AsyncSession):
    user, _ = await _seed(db_session)
    reader = NotificationReader("user", user.id, user.created_at)
    svc = JobService(db_session)

    unread, unread_total = await svc.list_notifications(is_read=False, reader=reader)
    read, read_total = await svc.list_notifications(is_read=True, reader=reader)

    assert unread_total == 2 and {n.message for n in unread} == {"new-1", "new-2"}
    assert read_total == 1 and [n.message for n in read] == ["old"]


async def test_mark_notification_read_is_idempotent(db_session: AsyncSession):
    user, notifications = await _seed(db_session)
    reader = NotificationReader("user", user.id, user.created_at)
    svc = JobService(db_session)

    for _ in range(2):
        assert (await svc.mark_notification_read(notifications[1], reader)).is_read is True
    count = (await db_session.execute(select(func.count()).select_from(NotificationReadReceipt))).scalar_one()
    assert count == 1
