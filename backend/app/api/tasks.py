"""
Task API endpoints
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db

router = APIRouter()


@router.get("/", response_model=List[schemas.Task])
def list_tasks(
    shot_id: int = Query(None),
    asset_id: int = Query(None),
    assignee_id: int = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get tasks filtered by shot, asset, or assignee"""
    if shot_id:
        tasks = crud.get_tasks_by_shot(db, shot_id)
    elif asset_id:
        tasks = crud.get_tasks_by_asset(db, asset_id)
    elif assignee_id:
        tasks = crud.get_tasks_by_assignee(db, assignee_id)
    else:
        tasks = crud.get_tasks(db, skip, limit)
    return tasks


@router.post("/", response_model=schemas.Task, status_code=status.HTTP_201_CREATED)
def create_task(task: schemas.TaskCreate, db: Session = Depends(get_db)):
    """Create a new task"""
    # Verify shot or asset exists
    if task.shot_id:
        shot = crud.get_shot(db, task.shot_id)
        if not shot:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shot not found")
    elif task.asset_id:
        asset = crud.get_asset(db, task.asset_id)
        if not asset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task must be linked to either a shot or an asset"
        )

    # Verify assignee exists if provided
    if task.assignee_id:
        assignee = crud.get_user(db, task.assignee_id)
        if not assignee:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignee not found")

    return crud.create_task(db, task)


@router.get("/{task_id}", response_model=schemas.Task)
def get_task(task_id: int, db: Session = Depends(get_db)):
    """Get a specific task"""
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.put("/{task_id}", response_model=schemas.Task)
def update_task(task_id: int, task: schemas.TaskUpdate, db: Session = Depends(get_db)):
    """Update a task"""
    updated = crud.update_task(db, task_id, task)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return updated


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    """Delete a task"""
    success = crud.delete_task(db, task_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return None
