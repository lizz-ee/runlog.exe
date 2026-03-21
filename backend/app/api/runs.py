from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from ..database import get_db
from ..models import Run
from ..schemas import RunCreate, RunUpdate, RunOut

router = APIRouter()


@router.get("/", response_model=list[RunOut])
def list_runs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    map_name: Optional[str] = None,
    survived: Optional[bool] = None,
    runner_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Run)
    if map_name:
        q = q.filter(Run.map_name == map_name)
    if survived is not None:
        q = q.filter(Run.survived == survived)
    if runner_id:
        q = q.filter(Run.runner_id == runner_id)
    return q.order_by(desc(Run.date)).offset(offset).limit(limit).all()


@router.get("/recent", response_model=list[RunOut])
def recent_runs(limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    return db.query(Run).order_by(desc(Run.date)).limit(limit).all()


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/", response_model=RunOut, status_code=201)
def create_run(data: RunCreate, db: Session = Depends(get_db)):
    run = Run(**data.model_dump(exclude_none=True))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@router.put("/{run_id}", response_model=RunOut)
def update_run(run_id: int, data: RunUpdate, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    for key, val in data.model_dump(exclude_none=True).items():
        setattr(run, key, val)
    db.commit()
    db.refresh(run)
    return run


@router.get("/unviewed/count")
def unviewed_count(db: Session = Depends(get_db)):
    """Get count of unviewed runs."""
    count = db.query(func.count(Run.id)).filter(Run.viewed == False).scalar()
    return JSONResponse(content={"count": count})


@router.post("/{run_id}/viewed")
def mark_viewed(run_id: int, db: Session = Depends(get_db)):
    """Mark a run as viewed."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run.viewed = True
    db.commit()
    return JSONResponse(content={"status": "ok"})


@router.post("/viewed/all")
def mark_all_viewed(db: Session = Depends(get_db)):
    """Mark all runs as viewed."""
    db.query(Run).filter(Run.viewed == False).update({"viewed": True})
    db.commit()
    return JSONResponse(content={"status": "ok"})


@router.post("/{run_id}/favorite")
def toggle_favorite(run_id: int, db: Session = Depends(get_db)):
    """Toggle favorite status on a run."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run.is_favorite = not run.is_favorite
    db.commit()
    return JSONResponse(content={"status": "ok", "is_favorite": run.is_favorite})
