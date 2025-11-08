"""Posts API Endpoints"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

router = APIRouter()


class PostCreate(BaseModel):
    """Model for creating a new post"""
    caption: str
    media_ids: List[str]
    platforms: List[str]  # ["instagram", "facebook", "tiktok"]
    scheduled_at: Optional[datetime] = None
    category: Optional[str] = None
    hashtags: List[str] = []


class PostResponse(BaseModel):
    """Model for post response"""
    id: str
    caption: str
    platforms: List[str]
    scheduled_at: Optional[datetime]
    status: str  # "draft", "scheduled", "published"
    created_at: datetime


@router.post("/", response_model=PostResponse)
async def create_post(post: PostCreate):
    """Create a new post"""
    return PostResponse(
        id="post_123",
        caption=post.caption,
        platforms=post.platforms,
        scheduled_at=post.scheduled_at,
        status="draft",
        created_at=datetime.now()
    )


@router.get("/")
async def get_posts(
    status: str = None,
    platform: str = None,
    limit: int = 50
):
    """Get all posts with optional filtering"""
    return {
        "posts": [],
        "total": 0
    }


@router.get("/{post_id}")
async def get_post(post_id: str):
    """Get a specific post by ID"""
    return {
        "id": post_id,
        "caption": "Sample post",
        "platforms": ["instagram"],
        "status": "draft"
    }
