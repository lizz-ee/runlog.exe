from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models import Session
from ..schemas import SessionCreate, SessionOut

router = APIRouter()


@router.get("/", response_model=list[SessionOut])
def list_sessions(db: DBSession = Depends(get_db)):
    return db.query(Session).order_by(Session.started_at.desc()).all()


@router.post("/", response_model=SessionOut, status_code=201)
def create_session(data: SessionCreate, db: DBSession = Depends(get_db)):
    session = Session(**data.model_dump())
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.put("/{session_id}/end", response_model=SessionOut)
def end_session(session_id: int, db: DBSession = Depends(get_db)):
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.ended_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return session
