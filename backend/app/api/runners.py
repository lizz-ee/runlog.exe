from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Runner
from ..schemas import RunnerCreate, RunnerUpdate, RunnerOut

router = APIRouter()


@router.get("/", response_model=list[RunnerOut])
def list_runners(db: Session = Depends(get_db)):
    return db.query(Runner).all()


@router.get("/{runner_id}", response_model=RunnerOut)
def get_runner(runner_id: int, db: Session = Depends(get_db)):
    runner = db.query(Runner).filter(Runner.id == runner_id).first()
    if not runner:
        raise HTTPException(status_code=404, detail="Runner not found")
    return runner


@router.post("/", response_model=RunnerOut, status_code=201)
def create_runner(data: RunnerCreate, db: Session = Depends(get_db)):
    runner = Runner(**data.model_dump())
    db.add(runner)
    db.commit()
    db.refresh(runner)
    return runner


@router.put("/{runner_id}", response_model=RunnerOut)
def update_runner(runner_id: int, data: RunnerUpdate, db: Session = Depends(get_db)):
    runner = db.query(Runner).filter(Runner.id == runner_id).first()
    if not runner:
        raise HTTPException(status_code=404, detail="Runner not found")
    for key, val in data.model_dump(exclude_none=True).items():
        setattr(runner, key, val)
    db.commit()
    db.refresh(runner)
    return runner


@router.delete("/{runner_id}", status_code=204)
def delete_runner(runner_id: int, db: Session = Depends(get_db)):
    runner = db.query(Runner).filter(Runner.id == runner_id).first()
    if not runner:
        raise HTTPException(status_code=404, detail="Runner not found")
    db.delete(runner)
    db.commit()
