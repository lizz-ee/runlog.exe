"""
CRUD operations for database models
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
from datetime import datetime

from app import models, schemas


# ============================================================================
# User CRUD
# ============================================================================

def get_user(db: Session, user_id: int) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.email == email).first()


def get_users(db: Session, skip: int = 0, limit: int = 100) -> List[models.User]:
    return db.query(models.User).offset(skip).limit(limit).all()


def create_user(db: Session, user: schemas.UserCreate) -> models.User:
    db_user = models.User(**user.model_dump(exclude={'password'}))
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def update_user(db: Session, user_id: int, user: schemas.UserUpdate) -> Optional[models.User]:
    db_user = get_user(db, user_id)
    if not db_user:
        return None
    for key, value in user.model_dump(exclude_unset=True).items():
        setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
    return db_user


# ============================================================================
# Project CRUD
# ============================================================================

def get_project(db: Session, project_id: int) -> Optional[models.Project]:
    return db.query(models.Project).filter(models.Project.id == project_id).first()


def get_project_by_code(db: Session, code: str) -> Optional[models.Project]:
    return db.query(models.Project).filter(models.Project.code == code).first()


def get_projects(db: Session, skip: int = 0, limit: int = 100) -> List[models.Project]:
    return db.query(models.Project).order_by(desc(models.Project.updated_at)).offset(skip).limit(limit).all()


def create_project(db: Session, project: schemas.ProjectCreate) -> models.Project:
    db_project = models.Project(**project.model_dump())
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project


def update_project(db: Session, project_id: int, project: schemas.ProjectUpdate) -> Optional[models.Project]:
    db_project = get_project(db, project_id)
    if not db_project:
        return None
    for key, value in project.model_dump(exclude_unset=True).items():
        setattr(db_project, key, value)
    db_project.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_project)
    return db_project


def delete_project(db: Session, project_id: int) -> bool:
    db_project = get_project(db, project_id)
    if not db_project:
        return False
    db.delete(db_project)
    db.commit()
    return True


# ============================================================================
# Sequence CRUD
# ============================================================================

def get_sequence(db: Session, sequence_id: int) -> Optional[models.Sequence]:
    return db.query(models.Sequence).filter(models.Sequence.id == sequence_id).first()


def get_sequences_by_project(db: Session, project_id: int) -> List[models.Sequence]:
    return db.query(models.Sequence).filter(models.Sequence.project_id == project_id).all()


def create_sequence(db: Session, sequence: schemas.SequenceCreate) -> models.Sequence:
    db_sequence = models.Sequence(**sequence.model_dump())
    db.add(db_sequence)
    db.commit()
    db.refresh(db_sequence)
    return db_sequence


def update_sequence(db: Session, sequence_id: int, sequence: schemas.SequenceUpdate) -> Optional[models.Sequence]:
    db_sequence = get_sequence(db, sequence_id)
    if not db_sequence:
        return None
    for key, value in sequence.model_dump(exclude_unset=True).items():
        setattr(db_sequence, key, value)
    db_sequence.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_sequence)
    return db_sequence


def delete_sequence(db: Session, sequence_id: int) -> bool:
    db_sequence = get_sequence(db, sequence_id)
    if not db_sequence:
        return False
    db.delete(db_sequence)
    db.commit()
    return True


# ============================================================================
# Shot CRUD
# ============================================================================

def get_shot(db: Session, shot_id: int) -> Optional[models.Shot]:
    return db.query(models.Shot).filter(models.Shot.id == shot_id).first()


def get_shot_by_code(db: Session, code: str) -> Optional[models.Shot]:
    return db.query(models.Shot).filter(models.Shot.code == code).first()


def get_shots_by_sequence(db: Session, sequence_id: int) -> List[models.Shot]:
    return db.query(models.Shot).filter(models.Shot.sequence_id == sequence_id).all()


def get_shots_by_project(db: Session, project_id: int) -> List[models.Shot]:
    return db.query(models.Shot).join(models.Sequence).filter(
        models.Sequence.project_id == project_id
    ).all()


def create_shot(db: Session, shot: schemas.ShotCreate) -> models.Shot:
    db_shot = models.Shot(**shot.model_dump())
    db.add(db_shot)
    db.commit()
    db.refresh(db_shot)
    return db_shot


def update_shot(db: Session, shot_id: int, shot: schemas.ShotUpdate) -> Optional[models.Shot]:
    db_shot = get_shot(db, shot_id)
    if not db_shot:
        return None
    for key, value in shot.model_dump(exclude_unset=True).items():
        setattr(db_shot, key, value)
    db_shot.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_shot)
    return db_shot


def delete_shot(db: Session, shot_id: int) -> bool:
    db_shot = get_shot(db, shot_id)
    if not db_shot:
        return False
    db.delete(db_shot)
    db.commit()
    return True


# ============================================================================
# Asset CRUD
# ============================================================================

def get_asset(db: Session, asset_id: int) -> Optional[models.Asset]:
    return db.query(models.Asset).filter(models.Asset.id == asset_id).first()


def get_asset_by_code(db: Session, code: str) -> Optional[models.Asset]:
    return db.query(models.Asset).filter(models.Asset.code == code).first()


def get_assets_by_project(db: Session, project_id: int) -> List[models.Asset]:
    return db.query(models.Asset).filter(models.Asset.project_id == project_id).all()


def create_asset(db: Session, asset: schemas.AssetCreate) -> models.Asset:
    db_asset = models.Asset(**asset.model_dump())
    db.add(db_asset)
    db.commit()
    db.refresh(db_asset)
    return db_asset


def update_asset(db: Session, asset_id: int, asset: schemas.AssetUpdate) -> Optional[models.Asset]:
    db_asset = get_asset(db, asset_id)
    if not db_asset:
        return None
    for key, value in asset.model_dump(exclude_unset=True).items():
        setattr(db_asset, key, value)
    db_asset.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_asset)
    return db_asset


def delete_asset(db: Session, asset_id: int) -> bool:
    db_asset = get_asset(db, asset_id)
    if not db_asset:
        return False
    db.delete(db_asset)
    db.commit()
    return True


# ============================================================================
# Task CRUD
# ============================================================================

def get_task(db: Session, task_id: int) -> Optional[models.Task]:
    return db.query(models.Task).filter(models.Task.id == task_id).first()


def get_tasks(db: Session, skip: int = 0, limit: int = 100) -> List[models.Task]:
    return db.query(models.Task).offset(skip).limit(limit).all()


def get_tasks_by_shot(db: Session, shot_id: int) -> List[models.Task]:
    return db.query(models.Task).filter(models.Task.shot_id == shot_id).all()


def get_tasks_by_asset(db: Session, asset_id: int) -> List[models.Task]:
    return db.query(models.Task).filter(models.Task.asset_id == asset_id).all()


def get_tasks_by_assignee(db: Session, user_id: int) -> List[models.Task]:
    return db.query(models.Task).filter(models.Task.assignee_id == user_id).all()


def create_task(db: Session, task: schemas.TaskCreate) -> models.Task:
    db_task = models.Task(**task.model_dump())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task


def update_task(db: Session, task_id: int, task: schemas.TaskUpdate) -> Optional[models.Task]:
    db_task = get_task(db, task_id)
    if not db_task:
        return None
    for key, value in task.model_dump(exclude_unset=True).items():
        setattr(db_task, key, value)
    db_task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_task)
    return db_task


def delete_task(db: Session, task_id: int) -> bool:
    db_task = get_task(db, task_id)
    if not db_task:
        return False
    db.delete(db_task)
    db.commit()
    return True


# ============================================================================
# Version CRUD
# ============================================================================

def get_version(db: Session, version_id: int) -> Optional[models.Version]:
    return db.query(models.Version).filter(models.Version.id == version_id).first()


def get_versions_by_shot(db: Session, shot_id: int) -> List[models.Version]:
    return db.query(models.Version).filter(
        models.Version.shot_id == shot_id
    ).order_by(desc(models.Version.version_number)).all()


def get_versions_by_asset(db: Session, asset_id: int) -> List[models.Version]:
    return db.query(models.Version).filter(
        models.Version.asset_id == asset_id
    ).order_by(desc(models.Version.version_number)).all()


def create_version(db: Session, version: schemas.VersionCreate) -> models.Version:
    db_version = models.Version(**version.model_dump())
    db.add(db_version)
    db.commit()
    db.refresh(db_version)
    return db_version


def update_version(db: Session, version_id: int, version: schemas.VersionUpdate) -> Optional[models.Version]:
    db_version = get_version(db, version_id)
    if not db_version:
        return None
    for key, value in version.model_dump(exclude_unset=True).items():
        setattr(db_version, key, value)
    db.commit()
    db.refresh(db_version)
    return db_version


def delete_version(db: Session, version_id: int) -> bool:
    db_version = get_version(db, version_id)
    if not db_version:
        return False
    db.delete(db_version)
    db.commit()
    return True


# ============================================================================
# Comment CRUD
# ============================================================================

def get_comment(db: Session, comment_id: int) -> Optional[models.Comment]:
    return db.query(models.Comment).filter(models.Comment.id == comment_id).first()


def get_comments_by_version(db: Session, version_id: int) -> List[models.Comment]:
    return db.query(models.Comment).filter(
        models.Comment.version_id == version_id,
        models.Comment.parent_comment_id.is_(None)  # Only top-level comments
    ).order_by(models.Comment.created_at).all()


def get_comment_replies(db: Session, comment_id: int) -> List[models.Comment]:
    return db.query(models.Comment).filter(
        models.Comment.parent_comment_id == comment_id
    ).order_by(models.Comment.created_at).all()


def create_comment(db: Session, comment: schemas.CommentCreate) -> models.Comment:
    db_comment = models.Comment(**comment.model_dump())
    db.add(db_comment)
    db.commit()
    db.refresh(db_comment)
    return db_comment


def update_comment(db: Session, comment_id: int, comment: schemas.CommentUpdate) -> Optional[models.Comment]:
    db_comment = get_comment(db, comment_id)
    if not db_comment:
        return None
    for key, value in comment.model_dump(exclude_unset=True).items():
        setattr(db_comment, key, value)
    db_comment.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_comment)
    return db_comment


def delete_comment(db: Session, comment_id: int) -> bool:
    db_comment = get_comment(db, comment_id)
    if not db_comment:
        return False
    db.delete(db_comment)
    db.commit()
    return True


# ============================================================================
# Activity CRUD
# ============================================================================

def create_activity(db: Session, activity: schemas.ActivityCreate) -> models.Activity:
    db_activity = models.Activity(**activity.model_dump())
    db.add(db_activity)
    db.commit()
    db.refresh(db_activity)
    return db_activity


def get_recent_activities(db: Session, limit: int = 50) -> List[models.Activity]:
    return db.query(models.Activity).order_by(
        desc(models.Activity.created_at)
    ).limit(limit).all()


def get_activities_by_entity(db: Session, entity_type: str, entity_id: int) -> List[models.Activity]:
    return db.query(models.Activity).filter(
        and_(
            models.Activity.entity_type == entity_type,
            models.Activity.entity_id == entity_id
        )
    ).order_by(desc(models.Activity.created_at)).all()
