from models.usuarios import Usuario
from security import verificar_password, get_password_encriptado, crear_token_acceso, excepcion_credenciales, SECRET_KEY, ALGORITHM
from schemas.usuarios import CrearUsuario, IniciarSesionUsuario

from datetime import datetime, timedelta, timezone

import jwt

from sqlmodel import Session, select
from typing import Optional

def get_usuario(sesion: Session, usuario_id: int) -> Optional[Usuario]:
    db_usuario = sesion.exec(select(Usuario).where(Usuario.id == usuario_id)).first()

    return db_usuario

def autenticar_usuario(sesion: Session, correo_electronico: str, password: str) -> Optional[Usuario]:
    db_usuario = sesion.exec(select(Usuario).where(Usuario.correo_electronico == correo_electronico)).first()

    if db_usuario is None:
        return None

    if not verificar_password(password, db_usuario.password):
        return None

    return db_usuario

async def registrar_usuario(*, sesion: Session, usuario: CrearUsuario) -> Optional[Usuario]:
    existe_usuario = sesion.exec(select(Usuario).where(Usuario.correo_electronico == usuario.correo_electronico)).first()

    if existe_usuario:
        return None
    
    ahora = datetime.now(timezone.utc)

    db_usuario = Usuario(
        nombre= usuario.nombre,
        correo_electronico= usuario.correo_electronico,
        password= get_password_encriptado(usuario.password),
        rol= usuario.rol.value,
        es_activo= True,
        creado_en= ahora,
        actualizado_en= ahora
    )
    try:
        sesion.add(db_usuario)
        sesion.commit()
        sesion.refresh(db_usuario)
    except Exception:
        sesion.rollback()
        raise

    return db_usuario

async def iniciar_sesion_usuario(*, sesion: Session, credenciales: IniciarSesionUsuario) -> Optional[str]:
    db_usuario = autenticar_usuario(sesion= sesion, correo_electronico= credenciales.correo_electronico, password= credenciales.password)

    if db_usuario is None:
        return None
    
    return crear_token_acceso(data= {"sub": str(db_usuario.id)}, expira_delta= timedelta(minutes= 60 * 8)) # sub: Significa "subject" y se utiliza para identificar al usuario al que pertenece el token. En este caso, se está utilizando el ID del usuario como subject del token.

async def get_actual_usuario(*, sesion: Session, token: str) -> Usuario:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms= [ALGORITHM])

        id_usuario = payload.get("sub")

        if id_usuario is None:
            raise excepcion_credenciales

    except jwt.InvalidTokenError:
        raise excepcion_credenciales

    db_usuario = get_usuario(sesion= sesion, usuario_id= int(id_usuario))

    if db_usuario is None:
        raise excepcion_credenciales

    return db_usuario
