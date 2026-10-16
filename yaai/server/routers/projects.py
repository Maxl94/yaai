import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.server.auth.dependencies import (
    CurrentIdentity,
    get_project_role,
    get_project_roles,
    has_global_access,
    require_auth,
    require_owner,
    require_project_admin,
)
from yaai.server.database import get_db
from yaai.server.schemas.project import (
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberUpdate,
    ProjectUpdate,
)
from yaai.server.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_projects(
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List the projects the caller can access (all projects for global owners), each with ``my_role``."""
    svc = ProjectService(db)
    if has_global_access(identity):
        return {"data": await svc.to_read(await svc.list_projects(), None)}
    roles = await get_project_roles(identity, db)
    projects = await svc.list_projects(list(roles))
    return {"data": await svc.to_read(projects, roles)}


@router.post("", status_code=201)
async def create_project(
    data: ProjectCreate,
    _identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    svc = ProjectService(db)
    project = await svc.create_project(data)
    return {"data": (await svc.to_read([project], None))[0]}


@router.get("/{project_id}")
async def get_project(
    project_id: uuid.UUID,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    svc = ProjectService(db)
    project = await svc.get_project(project_id)
    role = await get_project_role(identity, project_id, db)
    if role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this project")
    return {"data": (await svc.to_read([project], {project_id: role}))[0]}


@router.patch("/{project_id}")
async def update_project(
    project_id: uuid.UUID,
    data: ProjectUpdate,
    identity: CurrentIdentity = Depends(require_project_admin),
    db: AsyncSession = Depends(get_db),
):
    svc = ProjectService(db)
    project = await svc.update_project(project_id, data)
    role = await get_project_role(identity, project_id, db)
    return {"data": (await svc.to_read([project], {project_id: role}))[0]}


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    _identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    await ProjectService(db).delete_project(project_id)


@router.get("/{project_id}/members")
async def list_members(
    project_id: uuid.UUID,
    _identity: CurrentIdentity = Depends(require_project_admin),
    db: AsyncSession = Depends(get_db),
):
    svc = ProjectService(db)
    await svc.get_project(project_id)
    return {"data": await svc.list_members(project_id)}


@router.post("/{project_id}/members", status_code=201)
async def add_member(
    project_id: uuid.UUID,
    data: ProjectMemberCreate,
    _identity: CurrentIdentity = Depends(require_project_admin),
    db: AsyncSession = Depends(get_db),
):
    svc = ProjectService(db)
    await svc.get_project(project_id)
    return {"data": await svc.add_member(project_id, data)}


@router.patch("/{project_id}/members/{membership_id}")
async def update_member(
    project_id: uuid.UUID,
    membership_id: uuid.UUID,
    data: ProjectMemberUpdate,
    _identity: CurrentIdentity = Depends(require_project_admin),
    db: AsyncSession = Depends(get_db),
):
    return {"data": await ProjectService(db).update_member_role(project_id, membership_id, data.role)}


@router.delete("/{project_id}/members/{membership_id}", status_code=204)
async def remove_member(
    project_id: uuid.UUID,
    membership_id: uuid.UUID,
    _identity: CurrentIdentity = Depends(require_project_admin),
    db: AsyncSession = Depends(get_db),
):
    await ProjectService(db).remove_member(project_id, membership_id)
