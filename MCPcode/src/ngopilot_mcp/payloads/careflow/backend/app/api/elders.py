"""長者資料 CRUD（簡版）— 供未來功能 3 引用。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Elder

router = APIRouter(prefix="/api/elders", tags=["elders"])


@router.get("")
def list_elders(session: Session = Depends(get_session)):
    elders = session.exec(select(Elder).order_by(Elder.id.desc())).all()
    return {"elders": [e.model_dump() for e in elders]}


@router.post("", status_code=201)
def create_elder(elder: Elder, session: Session = Depends(get_session)):
    elder.id = None
    session.add(elder)
    session.commit()
    session.refresh(elder)
    return elder.model_dump()


@router.get("/{elder_id}")
def get_elder(elder_id: int, session: Session = Depends(get_session)):
    e = session.get(Elder, elder_id)
    if not e:
        raise HTTPException(404, "elder not found")
    return e.model_dump()
