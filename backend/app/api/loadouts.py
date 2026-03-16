from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Loadout
from ..schemas import LoadoutCreate, LoadoutUpdate, LoadoutOut

router = APIRouter()


@router.get("/", response_model=list[LoadoutOut])
def list_loadouts(db: Session = Depends(get_db)):
    return db.query(Loadout).all()


@router.get("/{loadout_id}", response_model=LoadoutOut)
def get_loadout(loadout_id: int, db: Session = Depends(get_db)):
    loadout = db.query(Loadout).filter(Loadout.id == loadout_id).first()
    if not loadout:
        raise HTTPException(status_code=404, detail="Loadout not found")
    return loadout


@router.post("/", response_model=LoadoutOut, status_code=201)
def create_loadout(data: LoadoutCreate, db: Session = Depends(get_db)):
    loadout = Loadout(**data.model_dump(exclude_none=True))
    db.add(loadout)
    db.commit()
    db.refresh(loadout)
    return loadout


@router.put("/{loadout_id}", response_model=LoadoutOut)
def update_loadout(loadout_id: int, data: LoadoutUpdate, db: Session = Depends(get_db)):
    loadout = db.query(Loadout).filter(Loadout.id == loadout_id).first()
    if not loadout:
        raise HTTPException(status_code=404, detail="Loadout not found")
    for key, val in data.model_dump(exclude_none=True).items():
        setattr(loadout, key, val)
    db.commit()
    db.refresh(loadout)
    return loadout


@router.delete("/{loadout_id}", status_code=204)
def delete_loadout(loadout_id: int, db: Session = Depends(get_db)):
    loadout = db.query(Loadout).filter(Loadout.id == loadout_id).first()
    if not loadout:
        raise HTTPException(status_code=404, detail="Loadout not found")
    db.delete(loadout)
    db.commit()
