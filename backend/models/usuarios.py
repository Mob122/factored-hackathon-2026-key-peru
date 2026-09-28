from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship
from typing import List, Optional


class Usuario(SQLModel, table= True):
    __tablename__ = "usuarios"

    id: Optional[int] = Field(default= None, primary_key= True)
    nombre: str = Field(max_length= 255, nullable= False)
    correo_electronico: str = Field(max_length= 255, nullable= False, unique= True)
    password: str = Field(max_length= 255, nullable= False)
    rol: str = Field(default= "usuario", max_length= 50)
    es_activo: bool = Field(default= True)
    creado_en: Optional[datetime] = Field(default= None)
    actualizado_en: Optional[datetime] = Field(default= None)

    # estimaciones: List["Estimacion"] = Relationship(back_populates= "creador")
    # facturas: List["Factura"] = Relationship(back_populates= "creador")