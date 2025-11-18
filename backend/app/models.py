"""
Database models for Scian Production Tracking
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    Boolean, Enum as SQLEnum, Float, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()


class TaskStatus(str, enum.Enum):
    """Task/Shot status options"""
    WTG = "wtg"  # Waiting to Start
    RDY = "rdy"  # Ready to Start
    IP = "ip"    # In Progress
    REV = "rev"  # Pending Review
    APP = "app"  # Approved
    HLD = "hld"  # On Hold / Changes Requested
    FIN = "fin"  # Final
    OMT = "omt"  # Omitted


class Priority(str, enum.Enum):
    """Priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Department(str, enum.Enum):
    """Production departments"""
    MODELING = "modeling"
    RIGGING = "rigging"
    SURFACING = "surfacing"
    ANIMATION = "animation"
    FX = "fx"
    LIGHTING = "lighting"
    RENDERING = "rendering"
    COMPOSITING = "compositing"
    EDITORIAL = "editorial"
    CONCEPT = "concept"
    PRODUCTION = "production"


class User(Base):
    """Team member"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    avatar_url = Column(String(500))
    department = Column(SQLEnum(Department))
    role = Column(String(100))  # Artist, Supervisor, Producer, etc.
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    assigned_tasks = relationship("Task", back_populates="assignee")
    comments = relationship("Comment", back_populates="author")


class Project(Base):
    """Production/Show"""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, nullable=False, index=True)  # e.g., "PROJ"
    description = Column(Text)
    thumbnail_url = Column(String(500))
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.IP)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    sequences = relationship("Sequence", back_populates="project", cascade="all, delete-orphan")
    assets = relationship("Asset", back_populates="project", cascade="all, delete-orphan")


class Sequence(Base):
    """Sequence of shots"""
    __tablename__ = "sequences"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(String(255), nullable=False)
    code = Column(String(50), nullable=False, index=True)  # e.g., "SEQ010"
    description = Column(Text)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.WTG)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="sequences")
    shots = relationship("Shot", back_populates="sequence", cascade="all, delete-orphan")


class Shot(Base):
    """Individual shot"""
    __tablename__ = "shots"

    id = Column(Integer, primary_key=True)
    sequence_id = Column(Integer, ForeignKey("sequences.id"), nullable=False)
    name = Column(String(255), nullable=False)
    code = Column(String(50), nullable=False, unique=True, index=True)  # e.g., "SEQ010_SH0010"
    description = Column(Text)
    thumbnail_url = Column(String(500))
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.WTG)
    priority = Column(SQLEnum(Priority), default=Priority.MEDIUM)

    # Frame range
    frame_start = Column(Integer)
    frame_end = Column(Integer)
    frame_duration = Column(Integer)
    fps = Column(Float, default=24.0)

    # Custom metadata
    custom_metadata = Column(JSON)  # Additional custom fields

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    sequence = relationship("Sequence", back_populates="shots")
    tasks = relationship("Task", back_populates="shot", cascade="all, delete-orphan")
    versions = relationship("Version", back_populates="shot", cascade="all, delete-orphan")


class AssetType(str, enum.Enum):
    """Asset categories"""
    CHARACTER = "character"
    PROP = "prop"
    ENVIRONMENT = "environment"
    FX = "fx"
    VEHICLE = "vehicle"
    MATTE_PAINTING = "matte_painting"


class Asset(Base):
    """Reusable asset (character, prop, environment, etc.)"""
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(String(255), nullable=False)
    code = Column(String(50), nullable=False, unique=True, index=True)
    asset_type = Column(SQLEnum(AssetType), nullable=False)
    description = Column(Text)
    thumbnail_url = Column(String(500))
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.WTG)
    priority = Column(SQLEnum(Priority), default=Priority.MEDIUM)

    # Custom metadata
    custom_metadata = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="assets")
    tasks = relationship("Task", back_populates="asset", cascade="all, delete-orphan")
    versions = relationship("Version", back_populates="asset", cascade="all, delete-orphan")


class Task(Base):
    """Work assignment"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    department = Column(SQLEnum(Department), nullable=False)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.WTG)
    priority = Column(SQLEnum(Priority), default=Priority.MEDIUM)

    # Assignment
    assignee_id = Column(Integer, ForeignKey("users.id"))

    # Linked to either a shot or asset
    shot_id = Column(Integer, ForeignKey("shots.id"))
    asset_id = Column(Integer, ForeignKey("assets.id"))

    # Scheduling
    start_date = Column(DateTime)
    due_date = Column(DateTime)
    completed_date = Column(DateTime)

    # Time tracking
    estimated_hours = Column(Float)
    actual_hours = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    assignee = relationship("User", back_populates="assigned_tasks")
    shot = relationship("Shot", back_populates="tasks")
    asset = relationship("Asset", back_populates="tasks")


class Version(Base):
    """Media version (uploaded media file)"""
    __tablename__ = "versions"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    version_number = Column(Integer, nullable=False)
    description = Column(Text)

    # Media file
    file_url = Column(String(500), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_size = Column(Integer)  # bytes
    mime_type = Column(String(100))
    thumbnail_url = Column(String(500))

    # Video metadata
    duration = Column(Float)  # seconds
    fps = Column(Float)
    resolution_width = Column(Integer)
    resolution_height = Column(Integer)
    codec = Column(String(50))

    # Linked to either a shot or asset
    shot_id = Column(Integer, ForeignKey("shots.id"))
    asset_id = Column(Integer, ForeignKey("assets.id"))

    # Upload info
    uploaded_by_id = Column(Integer, ForeignKey("users.id"))
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    # Review status
    review_status = Column(SQLEnum(TaskStatus), default=TaskStatus.REV)

    # Relationships
    shot = relationship("Shot", back_populates="versions")
    asset = relationship("Asset", back_populates="versions")
    uploaded_by = relationship("User")
    comments = relationship("Comment", back_populates="version", cascade="all, delete-orphan")


class CommentType(str, enum.Enum):
    """Comment types"""
    NOTE = "note"
    APPROVAL = "approval"
    REVISION = "revision"


class Comment(Base):
    """Review comment/annotation"""
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("versions.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    text = Column(Text, nullable=False)
    comment_type = Column(SQLEnum(CommentType), default=CommentType.NOTE)

    # Frame-accurate timestamp
    frame_number = Column(Integer)  # Specific frame
    timecode = Column(String(20))   # HH:MM:SS:FF

    # Drawing/annotation data (JSON)
    annotation_data = Column(JSON)  # Coordinates, shapes, etc.

    # Threading
    parent_comment_id = Column(Integer, ForeignKey("comments.id"))

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    version = relationship("Version", back_populates="comments")
    author = relationship("User", back_populates="comments")
    replies = relationship("Comment", remote_side=[parent_comment_id])


class Activity(Base):
    """Activity feed / audit log"""
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String(100), nullable=False)  # created, updated, commented, approved, etc.
    entity_type = Column(String(50), nullable=False)  # shot, asset, task, version, etc.
    entity_id = Column(Integer, nullable=False)
    details = Column(JSON)  # Additional context
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    user = relationship("User")
