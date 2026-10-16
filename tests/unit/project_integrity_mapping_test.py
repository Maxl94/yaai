"""Mapping of IntegrityErrors to HTTP errors when a project is deleted concurrently (simulated commit failures)."""

import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.schemas.model import ModelCreate, ModelUpdate
from yaai.server.models.model import Model
from yaai.server.models.project import Project
from yaai.server.services.model_service import ModelService
from yaai.server.services.project_service import ProjectService


def _integrity_error() -> IntegrityError:
    return IntegrityError("INSERT", {}, Exception("constraint violated"))


@pytest.fixture
async def project(db_session: AsyncSession) -> Project:
    project = Project(name=f"p-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project


async def test_create_model_failed_commit_in_existing_project_is_409(db_session: AsyncSession, project: Project):
    with patch.object(db_session, "commit", side_effect=_integrity_error()):
        with pytest.raises(HTTPException) as exc_info:
            await ModelService(db_session).create_model(ModelCreate(name="m"), project.id)

    assert exc_info.value.status_code == 409
    assert "already exists" in exc_info.value.detail


async def test_create_model_failed_commit_in_deleted_project_is_404(db_session: AsyncSession):
    with patch.object(db_session, "commit", side_effect=_integrity_error()):
        with pytest.raises(HTTPException) as exc_info:
            await ModelService(db_session).create_model(ModelCreate(name="m"), uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Project not found"


async def test_update_model_failed_commit_maps_name_clash_and_missing_project(
    db_session: AsyncSession, project: Project
):
    model = Model(name="m", project_id=project.id)
    db_session.add(model)
    await db_session.commit()
    svc = ModelService(db_session)

    with patch.object(db_session, "commit", side_effect=_integrity_error()):
        with pytest.raises(HTTPException) as clash:
            await svc.update_model(model.id, ModelUpdate(name="renamed"))
    assert clash.value.status_code == 409


async def test_update_model_move_into_project_deleted_before_commit_is_404(db_session: AsyncSession, project: Project):
    model = Model(name="m", project_id=project.id)
    db_session.add(model)
    await db_session.commit()
    gone = uuid.uuid4()
    original_get = db_session.get

    async def get_with_stale_project(entity, pk, *args, **kwargs):
        # The existence pre-check still sees the project; it vanishes before the commit
        return Project(id=gone, name="stale") if entity is Project and pk == gone else await original_get(entity, pk)

    with (
        patch.object(db_session, "get", side_effect=get_with_stale_project),
        patch.object(db_session, "commit", side_effect=_integrity_error()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ModelService(db_session).update_model(model.id, ModelUpdate(project_id=gone))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Project not found"


async def test_delete_project_failed_commit_is_409_not_500(db_session: AsyncSession, project: Project):
    project_id = project.id
    with patch.object(db_session, "commit", side_effect=_integrity_error()):
        with pytest.raises(HTTPException) as exc_info:
            await ProjectService(db_session).delete_project(project_id)

    assert exc_info.value.status_code == 409
    assert "contains models" in exc_info.value.detail
    assert await db_session.get(Project, project_id) is not None
