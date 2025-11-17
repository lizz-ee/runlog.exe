"""
Version API endpoints
"""

from typing import List
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db
from app.config import settings

router = APIRouter()


@router.get("/", response_model=List[schemas.Version])
def list_versions(
    shot_id: int = Query(None),
    asset_id: int = Query(None),
    db: Session = Depends(get_db)
):
    """Get all versions for a shot or asset"""
    if shot_id:
        versions = crud.get_versions_by_shot(db, shot_id)
    elif asset_id:
        versions = crud.get_versions_by_asset(db, asset_id)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide either shot_id or asset_id"
        )
    return versions


@router.post("/", response_model=schemas.Version, status_code=status.HTTP_201_CREATED)
def create_version(version: schemas.VersionCreate, db: Session = Depends(get_db)):
    """Register a new version (file path only, no upload)"""
    # Verify shot or asset exists
    if version.shot_id:
        shot = crud.get_shot(db, version.shot_id)
        if not shot:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shot not found")
    elif version.asset_id:
        asset = crud.get_asset(db, version.asset_id)
        if not asset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Version must be linked to either a shot or an asset"
        )

    # Verify uploader exists
    uploader = crud.get_user(db, version.uploaded_by_id)
    if not uploader:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uploader user not found")

    # Validate file path exists (optional but recommended)
    file_path = Path(version.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File not found at path: {version.file_path}"
        )

    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is not a file: {version.file_path}"
        )

    return crud.create_version(db, version)


@router.get("/{version_id}", response_model=schemas.Version)
def get_version(version_id: int, db: Session = Depends(get_db)):
    """Get a specific version"""
    version = crud.get_version(db, version_id)
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return version


@router.put("/{version_id}", response_model=schemas.Version)
def update_version(version_id: int, version: schemas.VersionUpdate, db: Session = Depends(get_db)):
    """Update a version"""
    updated = crud.update_version(db, version_id, version)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return updated


@router.delete("/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_version(version_id: int, db: Session = Depends(get_db)):
    """Delete a version"""
    success = crud.delete_version(db, version_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return None


@router.post("/validate-path", response_model=schemas.FilePathValidation)
def validate_file_path(file_path: str):
    """Validate that a file path exists and is accessible"""
    path = Path(file_path)

    result = schemas.FilePathValidation(
        exists=False,
        readable=False
    )

    if not path.exists():
        result.error = "File does not exist"
        return result

    result.exists = True

    if not path.is_file():
        result.error = "Path is not a file"
        return result

    try:
        # Check if readable
        with open(path, 'rb'):
            result.readable = True
            result.size = path.stat().st_size

            # Try to determine mime type from extension
            ext = path.suffix.lower()
            mime_types = {
                '.mp4': 'video/mp4',
                '.mov': 'video/quicktime',
                '.avi': 'video/x-msvideo',
                '.mkv': 'video/x-matroska',
                '.webm': 'video/webm',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.exr': 'image/x-exr',
                '.tif': 'image/tiff',
                '.tiff': 'image/tiff',
            }
            result.mime_type = mime_types.get(ext, 'application/octet-stream')

    except PermissionError:
        result.error = "Permission denied"
    except Exception as e:
        result.error = str(e)

    return result
