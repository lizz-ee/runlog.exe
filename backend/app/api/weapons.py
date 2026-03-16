from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Weapon
from ..schemas import WeaponCreate, WeaponOut

router = APIRouter()


@router.get("/", response_model=list[WeaponOut])
def list_weapons(db: Session = Depends(get_db)):
    return db.query(Weapon).all()


@router.post("/", response_model=WeaponOut, status_code=201)
def create_weapon(data: WeaponCreate, db: Session = Depends(get_db)):
    weapon = Weapon(**data.model_dump())
    db.add(weapon)
    db.commit()
    db.refresh(weapon)
    return weapon


@router.delete("/{weapon_id}", status_code=204)
def delete_weapon(weapon_id: int, db: Session = Depends(get_db)):
    weapon = db.query(Weapon).filter(Weapon.id == weapon_id).first()
    if not weapon:
        raise HTTPException(status_code=404, detail="Weapon not found")
    db.delete(weapon)
    db.commit()
