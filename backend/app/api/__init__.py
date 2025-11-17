"""
API router configuration - Production Tracking System
"""

from fastapi import APIRouter

from app.api import (
    projects,
    sequences,
    shots,
    assets,
    tasks,
    versions,
    comments,
    users,
    activity
)

router = APIRouter()

# Include all sub-routers
router.include_router(projects.router, prefix="/projects", tags=["projects"])
router.include_router(sequences.router, prefix="/sequences", tags=["sequences"])
router.include_router(shots.router, prefix="/shots", tags=["shots"])
router.include_router(assets.router, prefix="/assets", tags=["assets"])
router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
router.include_router(versions.router, prefix="/versions", tags=["versions"])
router.include_router(comments.router, prefix="/comments", tags=["comments"])
router.include_router(users.router, prefix="/users", tags=["users"])
router.include_router(activity.router, prefix="/activity", tags=["activity"])
