"""
Pydantic schemas for API request/response validation
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.models import TaskStatus, Priority, Department, AssetType, CommentType


# ============================================================================
# User Schemas
# ============================================================================

class UserBase(BaseModel):
    email: str
    name: str
    avatar_url: Optional[str] = None
    department: Optional[Department] = None
    role: Optional[str] = None
    is_active: bool = True


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    department: Optional[Department] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class User(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Project Schemas
# ============================================================================

class ProjectBase(BaseModel):
    name: str
    code: str
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    status: TaskStatus = TaskStatus.IP
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    status: Optional[TaskStatus] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class Project(ProjectBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectWithStats(Project):
    """Project with statistics"""
    total_shots: int = 0
    total_assets: int = 0
    shots_completed: int = 0
    assets_completed: int = 0


# ============================================================================
# Sequence Schemas
# ============================================================================

class SequenceBase(BaseModel):
    project_id: int
    name: str
    code: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.WTG


class SequenceCreate(SequenceBase):
    pass


class SequenceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None


class Sequence(SequenceBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Shot Schemas
# ============================================================================

class ShotBase(BaseModel):
    sequence_id: int
    name: str
    code: str
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    status: TaskStatus = TaskStatus.WTG
    priority: Priority = Priority.MEDIUM
    frame_start: Optional[int] = None
    frame_end: Optional[int] = None
    frame_duration: Optional[int] = None
    fps: float = 24.0
    custom_metadata: Optional[Dict[str, Any]] = None


class ShotCreate(ShotBase):
    pass


class ShotUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[Priority] = None
    frame_start: Optional[int] = None
    frame_end: Optional[int] = None
    frame_duration: Optional[int] = None
    fps: Optional[float] = None
    custom_metadata: Optional[Dict[str, Any]] = None


class Shot(ShotBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Asset Schemas
# ============================================================================

class AssetBase(BaseModel):
    project_id: int
    name: str
    code: str
    asset_type: AssetType
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    status: TaskStatus = TaskStatus.WTG
    priority: Priority = Priority.MEDIUM
    custom_metadata: Optional[Dict[str, Any]] = None


class AssetCreate(AssetBase):
    pass


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    asset_type: Optional[AssetType] = None
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[Priority] = None
    custom_metadata: Optional[Dict[str, Any]] = None


class Asset(AssetBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Task Schemas
# ============================================================================

class TaskBase(BaseModel):
    name: str
    description: Optional[str] = None
    department: Department
    status: TaskStatus = TaskStatus.WTG
    priority: Priority = Priority.MEDIUM
    assignee_id: Optional[int] = None
    shot_id: Optional[int] = None
    asset_id: Optional[int] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    estimated_hours: Optional[float] = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[Priority] = None
    assignee_id: Optional[int] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    completed_date: Optional[datetime] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None


class Task(TaskBase):
    id: int
    completed_date: Optional[datetime] = None
    actual_hours: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskWithDetails(Task):
    """Task with related entity details"""
    assignee: Optional[User] = None


# ============================================================================
# Version Schemas
# ============================================================================

class VersionBase(BaseModel):
    name: str
    version_number: int
    description: Optional[str] = None
    file_path: str  # Path to file on network storage
    file_name: str
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration: Optional[float] = None
    fps: Optional[float] = None
    resolution_width: Optional[int] = None
    resolution_height: Optional[int] = None
    codec: Optional[str] = None
    shot_id: Optional[int] = None
    asset_id: Optional[int] = None
    uploaded_by_id: int
    review_status: TaskStatus = TaskStatus.REV


class VersionCreate(VersionBase):
    pass


class VersionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    review_status: Optional[TaskStatus] = None


class Version(VersionBase):
    id: int
    uploaded_at: datetime

    class Config:
        from_attributes = True


class VersionWithDetails(Version):
    """Version with uploader info and comment count"""
    uploaded_by: Optional[User] = None
    comment_count: int = 0


# ============================================================================
# Comment Schemas
# ============================================================================

class CommentBase(BaseModel):
    version_id: int
    author_id: int
    text: str
    comment_type: CommentType = CommentType.NOTE
    frame_number: Optional[int] = None
    timecode: Optional[str] = None
    annotation_data: Optional[Dict[str, Any]] = None  # Drawing data
    parent_comment_id: Optional[int] = None


class CommentCreate(CommentBase):
    pass


class CommentUpdate(BaseModel):
    text: Optional[str] = None
    comment_type: Optional[CommentType] = None
    annotation_data: Optional[Dict[str, Any]] = None


class Comment(CommentBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CommentWithDetails(Comment):
    """Comment with author details"""
    author: User
    replies: List['CommentWithDetails'] = []


# ============================================================================
# Activity Schemas
# ============================================================================

class ActivityBase(BaseModel):
    user_id: Optional[int] = None
    action: str
    entity_type: str
    entity_id: int
    details: Optional[Dict[str, Any]] = None


class ActivityCreate(ActivityBase):
    pass


class Activity(ActivityBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ActivityWithUser(Activity):
    """Activity with user details"""
    user: Optional[User] = None


# ============================================================================
# Special Response Schemas
# ============================================================================

class FilePathValidation(BaseModel):
    """Response for file path validation"""
    exists: bool
    readable: bool
    size: Optional[int] = None
    mime_type: Optional[str] = None
    error: Optional[str] = None


class ProjectDashboard(BaseModel):
    """Dashboard data for a project"""
    project: Project
    sequences: List[Sequence]
    recent_activity: List[ActivityWithUser]
    stats: Dict[str, Any]


# Update forward references
CommentWithDetails.model_rebuild()
