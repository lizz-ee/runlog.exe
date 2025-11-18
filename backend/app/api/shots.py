"""
Shot API endpoints
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db

router = APIRouter()


@router.get("/", response_model=List[schemas.Shot])
def list_shots(
    sequence_id: int = Query(None),
    project_id: int = Query(None),
    db: Session = Depends(get_db)
):
    """Get all shots for a sequence or project"""
    if sequence_id:
        shots = crud.get_shots_by_sequence(db, sequence_id)
    elif project_id:
        shots = crud.get_shots_by_project(db, project_id)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide either sequence_id or project_id"
        )
    return shots


@router.post("/", response_model=schemas.Shot, status_code=status.HTTP_201_CREATED)
def create_shot(shot: schemas.ShotCreate, db: Session = Depends(get_db)):
    """Create a new shot"""
    # Verify sequence exists
    sequence = crud.get_sequence(db, shot.sequence_id)
    if not sequence:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sequence not found")

    # Check if code already exists
    existing = crud.get_shot_by_code(db, shot.code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Shot with code '{shot.code}' already exists"
        )

    return crud.create_shot(db, shot)


@router.get("/{shot_id}", response_model=schemas.Shot)
def get_shot(shot_id: int, db: Session = Depends(get_db)):
    """Get a specific shot"""
    shot = crud.get_shot(db, shot_id)
    if not shot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shot not found")
    return shot


@router.put("/{shot_id}", response_model=schemas.Shot)
def update_shot(shot_id: int, shot: schemas.ShotUpdate, db: Session = Depends(get_db)):
    """Update a shot"""
    updated = crud.update_shot(db, shot_id, shot)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shot not found")
    return updated


@router.delete("/{shot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shot(shot_id: int, db: Session = Depends(get_db)):
    """Delete a shot"""
    success = crud.delete_shot(db, shot_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shot not found")
    return None
