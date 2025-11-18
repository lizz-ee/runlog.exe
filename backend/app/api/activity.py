"""
Activity feed API endpoints
"""

from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db

router = APIRouter()


@router.get("/", response_model=List[schemas.Activity])
def list_activities(
    entity_type: str = Query(None),
    entity_id: int = Query(None),
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Get recent activities, optionally filtered by entity"""
    if entity_type and entity_id:
        activities = crud.get_activities_by_entity(db, entity_type, entity_id)
    else:
        activities = crud.get_recent_activities(db, limit)
    return activities


@router.post("/", response_model=schemas.Activity, status_code=201)
def create_activity(activity: schemas.ActivityCreate, db: Session = Depends(get_db)):
    """Create an activity log entry"""
    return crud.create_activity(db, activity)
