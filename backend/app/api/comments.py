"""
Comment and annotation API endpoints
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db

router = APIRouter()


@router.get("/", response_model=List[schemas.Comment])
def list_comments(version_id: int, db: Session = Depends(get_db)):
    """Get all comments for a version"""
    # Verify version exists
    version = crud.get_version(db, version_id)
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    comments = crud.get_comments_by_version(db, version_id)
    return comments


@router.post("/", response_model=schemas.Comment, status_code=status.HTTP_201_CREATED)
def create_comment(comment: schemas.CommentCreate, db: Session = Depends(get_db)):
    """Create a new comment/annotation"""
    # Verify version exists
    version = crud.get_version(db, comment.version_id)
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    # Verify author exists
    author = crud.get_user(db, comment.author_id)
    if not author:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Author not found")

    # If parent comment, verify it exists
    if comment.parent_comment_id:
        parent = crud.get_comment(db, comment.parent_comment_id)
        if not parent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent comment not found")

    return crud.create_comment(db, comment)


@router.get("/{comment_id}", response_model=schemas.Comment)
def get_comment(comment_id: int, db: Session = Depends(get_db)):
    """Get a specific comment"""
    comment = crud.get_comment(db, comment_id)
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    return comment


@router.get("/{comment_id}/replies", response_model=List[schemas.Comment])
def get_comment_replies(comment_id: int, db: Session = Depends(get_db)):
    """Get all replies to a comment"""
    comment = crud.get_comment(db, comment_id)
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

    replies = crud.get_comment_replies(db, comment_id)
    return replies


@router.put("/{comment_id}", response_model=schemas.Comment)
def update_comment(comment_id: int, comment: schemas.CommentUpdate, db: Session = Depends(get_db)):
    """Update a comment"""
    updated = crud.update_comment(db, comment_id, comment)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    return updated


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: int, db: Session = Depends(get_db)):
    """Delete a comment"""
    success = crud.delete_comment(db, comment_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    return None
