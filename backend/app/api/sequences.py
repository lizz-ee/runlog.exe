"""
Sequence API endpoints
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db

router = APIRouter()


@router.get("/", response_model=List[schemas.Sequence])
def list_sequences(project_id: int, db: Session = Depends(get_db)):
    """Get all sequences for a project"""
    sequences = crud.get_sequences_by_project(db, project_id)
    return sequences


@router.post("/", response_model=schemas.Sequence, status_code=status.HTTP_201_CREATED)
def create_sequence(sequence: schemas.SequenceCreate, db: Session = Depends(get_db)):
    """Create a new sequence"""
    # Verify project exists
    project = crud.get_project(db, sequence.project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return crud.create_sequence(db, sequence)


@router.get("/{sequence_id}", response_model=schemas.Sequence)
def get_sequence(sequence_id: int, db: Session = Depends(get_db)):
    """Get a specific sequence"""
    sequence = crud.get_sequence(db, sequence_id)
    if not sequence:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sequence not found")
    return sequence


@router.put("/{sequence_id}", response_model=schemas.Sequence)
def update_sequence(sequence_id: int, sequence: schemas.SequenceUpdate, db: Session = Depends(get_db)):
    """Update a sequence"""
    updated = crud.update_sequence(db, sequence_id, sequence)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sequence not found")
    return updated


@router.delete("/{sequence_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sequence(sequence_id: int, db: Session = Depends(get_db)):
    """Delete a sequence"""
    success = crud.delete_sequence(db, sequence_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sequence not found")
    return None
