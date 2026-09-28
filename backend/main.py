from db import crear_db_y_tablas
from routers import (
    usuarios_router
)

from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager # Importa el decorador asynccontextmanager para manejar eventos de inicio y cierre de la aplicación.
from fastapi.middleware.cors import CORSMiddleware

import logging
import os

ENV = os.getenv("ENV", "development") # Obtiene la variable de entorno ENV, que indica el modo de ejecución (desarrollo o producción). Por defecto, se establece en "development".

logging.basicConfig(level= logging.INFO) # Configura el nivel de logging para la aplicación. En desarrollo, se muestra toda la información, mientras que en producción se puede ajustar a un nivel más alto como WARNING o ERROR.
logger = logging.getLogger(__name__) # Configura el logger para la aplicación.

@asynccontextmanager
async def startup_event(app: FastAPI):
    logger.info(f"Aplicación iniciando en modo: {ENV}")

    try:
        if ENV == "development":
            crear_db_y_tablas()            
            logger.info("Base de datos y tablas verificadas/creadas.")
        else:
            logger.info("Modo producción: se asume que la base de datos ya está configurada.")
            
    except Exception as e:
        logger.error(f"Error al crear la base de datos: {e}")
        
    yield


app = FastAPI(lifespan= startup_event) # Crea una instancia de la aplicación FastAPI y asigna el evento de inicio definido anteriormente.


app.add_middleware(
    CORSMiddleware,
    allow_origins= ["*"],
    allow_credentials= True,
    allow_methods= ["*"],
    allow_headers= ["*"]
)

app.include_router(usuarios_router) # Agrega el enrutador de usuarios a la aplicación FastAPI.


@app.get("/")
async def get_root_endpoint():
    return {"Hello": "Backend de Key Peru"}