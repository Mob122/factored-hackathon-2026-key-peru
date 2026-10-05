from models.usuarios import Usuario
from security import verificar_password, get_password_encriptado, excepcion_credenciales
from schemas.usuarios import CrearUsuario, IniciarSesionUsuario
from services import auditoria, banco, identidad
from services.identidad import ErrorSesion

from datetime import datetime, timezone

from fastapi import HTTPException
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

    if not db_usuario.es_activo:
        return None

    return db_usuario

async def registrar_usuario(*, sesion: Session, usuario: CrearUsuario) -> Optional[Usuario]:
    existe_usuario = sesion.exec(select(Usuario).where(Usuario.correo_electronico == usuario.correo_electronico)).first()

    if existe_usuario:
        return None

    ahora = datetime.now(timezone.utc)

    # El registro abierto siempre crea un "cliente" sin customer_id: no ve datos de ningún cliente.
    # Los roles agente y jurado y la relación con un cliente solo los crea el script de semilla (POL-AUTH-10).
    db_usuario = Usuario(
        nombre= usuario.nombre,
        correo_electronico= usuario.correo_electronico,
        password= get_password_encriptado(usuario.password),
        rol= "cliente",
        customer_id= None,
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

def _auditar_fallo_inicio(sesion: Session) -> None:
    # Sin correo ni identificadores: solo que hubo un intento fallido (audit_log.md 4.1).
    auditoria.registrar_evento(
        sesion,
        event_type= "session",
        conversation_id= "conv_" + auditoria.uuid7(),
        session_id= None,
        actor= "identity",
        auth_level= "L0",
        state= "UNAUTHENTICATED",
        rule_ids= ["POL-AUTH-01", "POL-AUTH-02"],
        campos= {"session_event": "authentication_failed", "auth_level_before": "L0", "auth_level_after": "L0",
                 "expires_at": None, "step_up": None, "failure_count": 0, "language_preference": None,
                 "customer_status": None, "resume_intent": None},
    )
    sesion.commit()

async def iniciar_sesion_usuario(*, sesion: Session, credenciales: IniciarSesionUsuario) -> Optional[str]:
    db_usuario = autenticar_usuario(sesion= sesion, correo_electronico= credenciales.correo_electronico, password= credenciales.password)

    if db_usuario is None:
        _auditar_fallo_inicio(sesion)
        return None

    customer_status = None
    if db_usuario.rol == "cliente" and db_usuario.customer_id:
        try:
            customer_status = banco.estado_cliente(db_usuario.customer_id) # POL-AUTH-09: se revisa en cada inicio de sesión.
        except banco.ErrorHerramienta:
            customer_status = None

        if customer_status is None:
            raise HTTPException(status_code= 503, detail= "No se pudo verificar el estado del cliente.")

    registro = identidad.crear_sesion(
        sesion,
        rol= db_usuario.rol,
        metodo= "contrasena",
        usuario_id= db_usuario.id,
        customer_id= db_usuario.customer_id if db_usuario.rol == "cliente" else None,
        customer_status= customer_status,
        idioma= credenciales.idioma.value if credenciales.idioma else None,
    )
    identidad.auditar_sesion(
        sesion, registro, "authenticated", rule_ids= ["POL-AUTH-01"], state= "UNAUTHENTICATED",
        auth_level_before= "L0", auth_level_after= "L1", expires_at= registro.expira_absoluta_en,
        customer_status= customer_status,
    )
    sesion.commit()

    return identidad.emitir_token(registro) # El JWT solo nombra la sesión del servidor (POL-AUTH-12).

async def get_actual_usuario(*, sesion: Session, token: str) -> Usuario:
    try:
        registro = identidad.sesion_desde_token(sesion, token)
    except ErrorSesion:
        raise excepcion_credenciales

    if registro.usuario_id is None:
        # Sesión abierta por un jurado en el IdP de prueba: no hay un usuario registrado detrás.
        raise HTTPException(status_code= 403, detail= "Esta sesión no corresponde a un usuario registrado.")

    db_usuario = get_usuario(sesion= sesion, usuario_id= registro.usuario_id)

    if db_usuario is None or not db_usuario.es_activo:
        raise excepcion_credenciales

    return db_usuario
