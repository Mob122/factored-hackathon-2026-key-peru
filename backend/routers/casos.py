"""Bandeja de casos para asesores humanos (rol agente). Los asesores ven los expedientes con el
customer_id y los ids internos del cliente de la sesión (POL-PII-05, POL-PII-07)."""

from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select

from db import SesionDependencia
from models.banco import Caso
from models.identidad import SesionIdentidad
from schemas.chat import LecturaCaso, ResumenCaso
from security.dependencias import requiere_rol

router = APIRouter(prefix= "/casos", tags= ["Casos (agente)"])
AgenteDependencia = Annotated[SesionIdentidad, Depends(requiere_rol("agente"))]


@router.get("", response_model= List[ResumenCaso])
async def listar_casos(sesion: SesionDependencia, agente: AgenteDependencia,
                       limite: int = Query(50, ge= 1, le= 200), desplazamiento: int = Query(0, ge= 0)):
    casos = sesion.exec(select(Caso).order_by(Caso.created_at.desc()).offset(desplazamiento).limit(limite)).all()
    return [ResumenCaso(**caso.model_dump()) for caso in casos]


@router.get("/{case_id}", response_model= LecturaCaso)
async def leer_caso(sesion: SesionDependencia, agente: AgenteDependencia, case_id: str):
    caso = sesion.get(Caso, case_id)
    if caso is None:
        raise HTTPException(status_code= 404, detail= "Caso no encontrado.")
    return LecturaCaso(**caso.model_dump())
