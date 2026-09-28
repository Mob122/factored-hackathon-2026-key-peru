from fastapi import Depends
from sqlmodel import SQLModel, Session, create_engine
from typing import Annotated, Generator

from dotenv import load_dotenv

import os

load_dotenv(dotenv_path= '.env')  # Carga las variables de entorno desde el archivo .env.

DATABASE_URL = os.getenv("DATABASE_URL") # Obtiene la URL de la base de datos desde las variables de entorno, con un valor predeterminado para desarrollo.

# Si es sqlite.
es_sqlite = DATABASE_URL.startswith("sqlite://")

engine_args = {}
if es_sqlite:
    engine_args["connect_args"] = {"check_same_thread": False} # Para SQLite, permite conexiones desde múltiples hilos.
else:
    engine_args["pool_pre_ping"] = True # Para MySQL, ayuda a mantener las conexiones vivas sirve para evitar errores de conexión.
    engine_args["pool_size"] = 10 # Para MySQL, establece el tamaño del pool de conexiones para mejorar el rendimiento en producción.
    engine_args["max_overflow"] = 20 # Para MySQL, permite un número adicional de conexiones por encima del tamaño del pool para manejar picos de tráfico.
    engine_args['echo'] = False # Para MySQL, desactiva el logging de las consultas SQL para mejorar el rendimiento en producción.
    

motor = create_engine(DATABASE_URL, **engine_args) # Para SQLite, permite conexiones desde múltiples hilos.

def run_migraciones():
    """Migraciones idempotentes para bases existentes (create_all no altera tablas).

    Postgres soporta ADD COLUMN IF NOT EXISTS, por lo que es seguro ejecutarlo
    en cada arranque.
    """
    if es_sqlite:
        return
    
    from sqlalchemy import text

    declaraciones = [
        # "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS discount_type VARCHAR(10)",
        # "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS discount_value NUMERIC(12,2) DEFAULT 0",
        # "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(14,2) DEFAULT 0",
        # "ALTER TABLE services_products ADD COLUMN IF NOT EXISTS url VARCHAR(255) DEFAULT NULL",
    ]
    with motor.begin() as conexion:
        for statement in declaraciones:
            conexion.execute(text(statement))

def crear_db_y_tablas():
    import models  # noqa: F401  fuerza el registro de todos los modelos en SQLModel.metadata.

    SQLModel.metadata.create_all(motor) # Crea las tablas en la base de datos según los modelos definidos.
    run_migraciones()

def get_sesion() -> Generator[Session, None, None]: # Generator que devuelve una sesión de la base de datos, se puede usar con Depends en FastAPI para inyectar la sesión en las rutas.
    with Session(motor) as conexion: # Establece una conexión a la base de datos.
        yield conexion # Devuelve la conexión para su uso en otras partes del código, como en las rutas de FastAPI, yield permite que se cierre automáticamente después de su uso.

SesionDependencia = Annotated[Session, Depends(get_sesion)] # Define una anotación de tipo para la sesión de la base de datos, que se puede usar en las rutas de FastAPI para inyectar la sesión automáticamente.