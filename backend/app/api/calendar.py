"""Calendar API Endpoints"""

from fastapi import APIRouter
from datetime import datetime, timedelta

router = APIRouter()


@router.get("/")
async def get_calendar(
    start_date: str = None,
    end_date: str = None,
    view: str = "week"  # "week" or "month"
):
    """Get calendar view with scheduled posts"""
    return {
        "view": view,
        "start_date": start_date or datetime.now().isoformat(),
        "end_date": end_date or (datetime.now() + timedelta(days=7)).isoformat(),
        "posts": []
    }


@router.get("/suggested-times")
async def get_suggested_posting_times(content_type: str = "lifestyle"):
    """Get AI-suggested best times to post based on content type"""
    return {
        "suggestions": [
            {"day": "Monday", "time": "09:00", "score": 0.85},
            {"day": "Wednesday", "time": "14:00", "score": 0.92},
            {"day": "Friday", "time": "18:00", "score": 0.88}
        ]
    }
