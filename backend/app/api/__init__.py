from fastapi import APIRouter

from .screenshot import router as screenshot_router
from .runs import router as runs_router
from .runners import router as runners_router
from .loadouts import router as loadouts_router
from .weapons import router as weapons_router
from .stats import router as stats_router
from .sessions import router as sessions_router
from .spawns import router as spawns_router
from .detect import router as detect_router
from .capture_api import router as capture_router

api_router = APIRouter(prefix="/api")

api_router.include_router(screenshot_router, prefix="/screenshot", tags=["screenshot"])
api_router.include_router(runs_router, prefix="/runs", tags=["runs"])
api_router.include_router(runners_router, prefix="/runners", tags=["runners"])
api_router.include_router(loadouts_router, prefix="/loadouts", tags=["loadouts"])
api_router.include_router(weapons_router, prefix="/weapons", tags=["weapons"])
api_router.include_router(stats_router, prefix="/stats", tags=["stats"])
api_router.include_router(sessions_router, prefix="/sessions", tags=["sessions"])
api_router.include_router(spawns_router, prefix="/spawns", tags=["spawns"])
api_router.include_router(detect_router, prefix="/detect", tags=["detect"])
api_router.include_router(capture_router, prefix="/capture", tags=["capture"])
