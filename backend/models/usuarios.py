from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship
from typing import List, Optional


class Usuario(SQLModel, table= True):
    __tablename__ = "usuarios"

    id: Optional[int] = Field(default= None, primary_key= True)
    nombre: str = Field(max_length= 255, nullable= False)
    correo_electronico: str = Field(max_length= 255, nullable= False, unique= True)
    password: str = Field(max_length= 255, nullable= False)
    rol: str = Field(default= "cliente", max_length= 50) # "cliente", "agente" o "jurado" (POL-AUTH-10).
    customer_id: Optional[str] = Field(default= None, max_length= 16, index= True) # Solo usuarios "cliente" sembrados; nunca se toma de un formulario.
    es_activo: bool = Field(default= True)
    creado_en: Optional[datetime] = Field(default= None)
    actualizado_en: Optional[datetime] = Field(default= None)

    # estimaciones: List["Estimacion"] = Relationship(back_populates= "creador")
    # facturas: List["Factura"] = Relationship(back_populates= "creador")
