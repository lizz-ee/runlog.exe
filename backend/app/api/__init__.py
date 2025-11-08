"""API Routes"""

from fastapi import APIRouter
from app.api import ai, media, posts, calendar, analytics

router = APIRouter()

# Include sub-routers
router.include_router(ai.router, prefix="/ai", tags=["AI"])
router.include_router(media.router, prefix="/media", tags=["Media"])
router.include_router(posts.router, prefix="/posts", tags=["Posts"])
router.include_router(calendar.router, prefix="/calendar", tags=["Calendar"])
router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
