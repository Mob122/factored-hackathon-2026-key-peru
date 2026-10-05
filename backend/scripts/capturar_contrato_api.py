"""Captura con llamadas reales los ejemplos de docs/contracts/chat_api.md y exporta el OpenAPI.

- La app completa corre en proceso (TestClient): rutas, validación, sesiones, orquestador, clasificador
  real y tools sobre el gold de demo (ml/scripts/make_demo_gold.py), con el reloj de las conversaciones
  golden y LLM_MODE=mock. La base SQLite y las claves son temporales: nunca lee backend/.env.
- Solo dos ejemplos fuerzan una condición: la sesión vencida adelanta 16 min el reloj de identidad, y el
  respaldo del LLM apunta el cliente de OpenAI a un puerto local cerrado (no llama a la API).
- Escribe docs/contracts/chat_api_examples.json, los bloques <!-- example(s): ... --> de chat_api.md y
  docs/contracts/openapi.json. Los tokens y la contraseña se reemplazan por marcadores.
- Falla si una respuesta no tiene el código HTTP o el estado esperado: así el contrato no se desactualiza
  sin que nadie lo note.

Uso, desde backend/:  python -m scripts.capturar_contrato_api [--gold ../ml/data/demo_gold]
"""

from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import argparse
import json
import os
import re
import secrets
import sys
import tempfile

RAIZ_BACKEND = Path(__file__).resolve().parents[1]
RAIZ_REPO = RAIZ_BACKEND.parent
DIR_CONTRATOS = RAIZ_REPO / "docs" / "contracts"
RELOJ_GOLDEN = "2026-06-18T10:00:00"
_JWT = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")
_MARCADOR = re.compile(r"<!-- (example|examples): (\S+)((?: \w+=\S+)*) -->\n.*?<!-- /example -->", re.S)
ETIQUETAS_AUTH = {
    "cliente": "customer token", "agente": "agent token", "jurado": "jurado token", "prueba": "test session token",
    "invalido": "invalid token",
}


def preparar_entorno(gold: Path) -> str:
    """Variables antes de importar la app: nada sale de backend/.env (como tests/conftest.py)."""
    import dotenv

    dotenv.load_dotenv = lambda *args, **kwargs: False
    temporal = Path(tempfile.mkdtemp(prefix= "keyperu-contrato-"))
    password = secrets.token_urlsafe(18)
    os.environ.update({
        "ENV": "development",
        "DATABASE_URL": f"sqlite:///{(temporal / 'contrato.db').as_posix()}",
        "SECRET_KEY": secrets.token_urlsafe(48), "ALGORITHM": "HS256",
        "CARD_HASH_KEY": secrets.token_urlsafe(32), "AUDIT_KEY": secrets.token_urlsafe(32),
        "SEED_PASSWORD": password, "GOLD_DIR": str(gold), "RELOJ_SIMULADO": RELOJ_GOLDEN,
        "LLM_PROVIDER": "openai", "LLM_MODE": "mock", "LLM_MODEL": "gpt-4o-mini", "LLM_ALLOWED_MODELS": "gpt-4o-mini",
        "FALLBACK_QUEUE_PATH": str(temporal / "cola_casos.jsonl"),
    })
    os.environ.pop("OPENAI_API_KEY", None)
    sys.path.insert(0, str(RAIZ_BACKEND))
    return password


class Grabadora:
    """Hace cada llamada, comprueba el resultado esperado y guarda pedido y respuesta sin secretos."""

    def __init__(self, http, password: str):
        self.http = http
        self.password = password
        self.tokens: Dict[str, str] = {} # etiqueta -> token
        self.ejemplos: List[Dict[str, Any]] = []

    def token(self, etiqueta: str, valor: str) -> str:
        self.tokens[etiqueta] = valor
        return valor

    def llamar(self, id_: str, titulo: str, metodo: str, ruta: str, auth: Optional[str] = None, cuerpo: Any = None,
               query: Optional[Dict[str, Any]] = None, http: int = 200, estado: Optional[str] = None,
               grabar: bool = True) -> Any:
        cabeceras = {"Authorization": f"Bearer {self.tokens[auth]}"} if auth else {}
        respuesta = self.http.request(metodo, ruta, json= cuerpo, params= query, headers= cabeceras)
        datos = respuesta.json() if respuesta.content else None
        if respuesta.status_code != http or (estado and (datos or {}).get("state") != estado):
            raise SystemExit(f"{id_}: se esperaba HTTP {http} {estado or ''}, llegó {respuesta.status_code}: {respuesta.text[:400]}")
        if grabar:
            self.ejemplos.append({
                "id": id_, "title": titulo,
                "request": {"method": metodo, "path": ruta, "query": query, "auth": auth, "body": self.limpiar(cuerpo)},
                "response": {"status": respuesta.status_code, "body": self.limpiar(datos)},
            })
        return datos

    def chat(self, id_: str, titulo: str, auth: str, conversation_id: str, mensaje: Optional[str] = None,
             codigo: Optional[str] = None, estado: Optional[str] = None, idioma: Optional[str] = None) -> Dict[str, Any]:
        cuerpo: Dict[str, Any] = {"conversation_id": conversation_id}
        cuerpo.update({"mensaje": mensaje} if mensaje is not None else {"codigo_step_up": codigo})
        if idioma:
            cuerpo["idioma"] = idioma
        return self.llamar(id_, titulo, "POST", "/chat/mensaje", auth= auth, cuerpo= cuerpo, estado= estado)

    def limpiar(self, valor: Any) -> Any:
        if isinstance(valor, dict):
            return {k: self.limpiar(v) for k, v in valor.items()}
        if isinstance(valor, list):
            return [self.limpiar(v) for v in valor]
        if isinstance(valor, str):
            for etiqueta, token in self.tokens.items():
                valor = valor.replace(token, f"<{ETIQUETAS_AUTH[etiqueta.split(':')[0]]}>")
            return _JWT.sub("<token>", valor.replace(self.password, "<SEED_PASSWORD>"))
        return valor


# --- conversaciones -------------------------------------------------------------------------------

D1, D2, D5, D9, D11, D12 = ("CLI-5B9VSCP2GSML", "CLI-JPK27B33SV65", "CLI-AYAHYQEG16BZ", "CLI-LD6QVNCSTR43",
                            "CLI-SQJOCEDJJNCZ", "CLI-AN7KXGR09TB2")


def entrar_cliente(g: Grabadora, prefijo: str, customer_id: str, idioma: Optional[str] = None, grabar: bool = False) -> str:
    from scripts.sembrar_usuarios import correo_cliente

    cuerpo = {"correo_electronico": correo_cliente(customer_id), "password": g.password, **({"idioma": idioma} if idioma else {})}
    token = g.llamar(f"{prefijo}-login", "Seeded customer signs in", "POST", "/autenticacion/iniciar-sesion",
                     cuerpo= cuerpo, grabar= grabar)
    g.token(f"cliente:{customer_id}", token)
    return f"cliente:{customer_id}"


def abrir_chat(g: Grabadora, id_: str, auth: str, idioma: Optional[str] = None, grabar: bool = True) -> str:
    cuerpo = {"idioma": idioma} if idioma else {}
    datos = g.llamar(id_, "Open the chat (turn 0)", "POST", "/chat/sesiones", auth= auth, cuerpo= cuerpo, http= 201,
                     estado= "IDLE", grabar= grabar)
    return datos["conversation_id"]


def sesion_prueba(g: Grabadora, id_: Optional[str], customer_id: str, idioma: Optional[str] = None) -> Dict[str, Any]:
    cuerpo = {"customer_id": customer_id, **({"idioma": idioma} if idioma else {})}
    datos = g.llamar(id_ or "_", "Jurado starts a test session for a customer", "POST", "/identidad/sesion-prueba",
                     auth= "jurado", cuerpo= cuerpo, http= 201, grabar= id_ is not None)
    g.token(f"prueba:{customer_id}", datos["token"])
    return datos


def cliente_para_idp(gold: Path, excluir: List[str]) -> Dict[str, str]:
    """Un cliente no persona, Active, con 2+ productos de saldo y una tarjeta de crédito con movimientos en los
    30 días del reloj golden y últimos 4 únicos: la sesión del IdP de prueba muestra la selección y "esa tarjeta"."""
    import duckdb

    con = duckdb.connect()
    fila = con.execute(f"""
        WITH saldo AS (SELECT customer_id, count(*) n FROM read_parquet('{gold / "balance_products.parquet"}') GROUP BY 1),
        tarjeta AS (
            SELECT b.customer_id, b.last4 FROM read_parquet('{gold / "balance_products.parquet"}') b
            JOIN read_parquet('{gold / "card_transactions.parquet"}') t ON t.card_id = b.product_id
            WHERE b.kind = 'credit_card' AND b.status = 'Active'
              AND t.transaction_datetime >= TIMESTAMP '2026-05-19' AND t.transaction_datetime < TIMESTAMP '{RELOJ_GOLDEN}'
            GROUP BY 1, 2),
        unicos AS (SELECT customer_id, last4 FROM read_parquet('{gold / "balance_products.parquet"}') GROUP BY 1, 2 HAVING count(*) = 1)
        SELECT c.customer_id, c.country, c.segment, tarjeta.last4
        FROM read_parquet('{gold / "customers.parquet"}') c JOIN saldo USING (customer_id)
        JOIN tarjeta USING (customer_id) JOIN unicos USING (customer_id, last4)
        WHERE c.customer_status = 'Active' AND saldo.n >= 2 AND c.customer_id NOT IN ({", ".join("?" for _ in excluir)})
        ORDER BY c.customer_id LIMIT 1""", excluir).fetchone()
    if fila is None:
        raise SystemExit("El gold no tiene un cliente adecuado para la sesión del IdP de prueba.")
    return dict(zip(("customer_id", "country", "segment", "last4"), fila))


def capturar(g: Grabadora, gold: Path) -> None:
    from services import identidad
    from services.agente import llm
    from scripts.sembrar_usuarios import PERSONAS_GOLDEN

    # Autenticación de un cliente sembrado.
    auth = entrar_cliente(g, "auth", D11, grabar= True)
    g.llamar("auth-profile", "Profile of the signed-in user", "GET", "/autenticacion/mi-perfil", auth= auth)
    g.llamar("auth-session", "Session level and expiry", "GET", "/autenticacion/mi-sesion", auth= auth)

    # Diálogo 11 (es): saldo de una tarjeta de crédito.
    conv = abrir_chat(g, "d11-t0", auth)
    g.chat("d11-t1", "Balance, two eligible products: clarification", auth, conv, "Hola, ¿cuál es mi saldo?", estado= "SELECT_CARD")
    g.chat("d11-t2", "Product chosen by type", auth, conv, "La tarjeta de crédito.", estado= "IDLE")
    g.chat("d11-t3", "Available credit is never computed (POL-BAL-05)", auth, conv, "¿Y cuánto tengo disponible para usar?", estado= "IDLE")
    g.chat("d11-t4", "Balance read again, never reused (POL-GEN-07)", auth, conv,
           "Ok. ¿Y el saldo de la tarjeta sigue igual que hace un rato?", estado= "IDLE")
    g.chat("d11-t5", "Closing", auth, conv, "Gracias, eso es todo.", estado= "ENDED")

    # Diálogo 1 (es): cargo rechazado.
    auth = entrar_cliente(g, "d1", D1)
    conv = abrir_chat(g, "d1-t0", auth)
    g.chat("d1-t1", "Declined charge explained with its response code", auth, conv,
           "Hola, hace unos días me rechazaron un pago en Uber con mi tarjeta terminada en 6873. ¿Qué pasó?", estado= "IDLE")
    g.chat("d1-t2", "Card status; no expiration date is confirmed (POL-ANS-13)", auth, conv,
           "¿Entonces mi tarjeta está vencida?", estado= "IDLE")
    g.chat("d1-t3", "Closing", auth, conv, "No, así está bien. Gracias.", estado= "ENDED")

    # Diálogo 5 (es): reclamo de un cargo, bloqueo ofrecido y rechazado, transferencia con expediente.
    auth_d5 = entrar_cliente(g, "d5", D5)
    conv = abrir_chat(g, "d5-t0", auth_d5)
    g.chat("d5-t1", "Dispute: the transaction is found and must be confirmed", auth_d5, conv,
           "No reconozco un cobro de Empresa Telefónica en mi tarjeta de crédito terminada en 4950. Quiero reclamarlo.",
           estado= "SELECT_TRANSACTION")
    g.chat("d5-t2", "Confirmed: a block is offered", auth_d5, conv, "Sí, ese.", estado= "OFFER_BLOCK")
    caso = g.chat("d5-t3", "Block declined: handoff with a case ID", auth_d5, conv,
                  "No, por ahora solo quiero el reclamo.", estado= "HANDED_OFF")["case_id"]
    g.chat("d5-t4", "Message after the handoff is appended to the case (T-38)", auth_d5, conv,
           "¿En cuánto tiempo me contactan?", estado= "HANDED_OFF")

    # Portal del cliente (POL-PII-10): tarjetas y transacciones del diálogo 1, conversaciones y casos del diálogo 5.
    g.llamar("portal-cards", "The customer's cards, no internal IDs", "GET", "/cliente/tarjetas", auth= f"cliente:{D1}")
    g.llamar("portal-transactions", "Card transactions of the last 30 days of the bank clock", "GET", "/cliente/transacciones",
             auth= f"cliente:{D1}", query= {"dias": 30})
    g.llamar("portal-conversations", "The customer's conversations, newest first", "GET", "/cliente/conversaciones", auth= auth_d5)
    g.llamar("portal-cases", "The customer's cases: reference and context, never the case file", "GET", "/cliente/casos",
             auth= auth_d5)

    # Diálogo 12 (pt): saldo de la cuenta de ahorros y luego de una tarjeta.
    auth = entrar_cliente(g, "d12", D12, idioma= "pt")
    conv = abrir_chat(g, "d12-t0", auth)
    g.chat("d12-t1", "Savings balance, only one eligible: no question", auth, conv,
           "Oi, qual é o saldo da minha conta poupança?", estado= "IDLE")
    g.chat("d12-t2", "Three credit cards: clarification", auth, conv, "E o do cartão de crédito?", estado= "SELECT_CARD")
    g.chat("d12-t3", "Card chosen by last 4", auth, conv, "O 7858.", estado= "IDLE")
    g.chat("d12-t4", "Closing", auth, conv, "Obrigado, era isso.", estado= "ENDED")

    # Jurado: entra y busca clientes en el IdP de prueba.
    g.token("jurado", g.llamar("jurado-login", "Jurado signs in", "POST", "/autenticacion/iniciar-sesion",
                               cuerpo= {"correo_electronico": "jurado@keyperu.example", "password": g.password}))
    idp = cliente_para_idp(gold, [c for c, _ in PERSONAS_GOLDEN])
    g.llamar("idp-search", "Search customers (filters and paging)", "GET", "/identidad/clientes", auth= "jurado",
             query= {"pais": idp["country"], "segmento": idp["segment"], "estado_cliente": "Active", "tamano": 3})
    g.llamar("idp-search-prefix", "Search by customer_id prefix", "GET", "/identidad/clientes", auth= "jurado",
             query= {"q": idp["customer_id"][:8]})

    # Diálogo 2 (pt): bloqueo de una tarjeta perdida con step-up y confirmación.
    prueba = sesion_prueba(g, "d2-session", D2, idioma= "pt")
    auth = f"prueba:{D2}"
    conv = abrir_chat(g, "d2-t0", auth)
    g.chat("d2-t1", "Block request: step-up required", auth, conv, "Oi, perdi meu cartão de crédito. Quero bloquear agora.", estado= "STEP_UP")
    otp = g.llamar("d2-otp", "Jurado console issues a test one-time code", "POST", "/identidad/otp-prueba", auth= "jurado",
                   cuerpo= {"sesion_id": prueba["sesion_id"]}, http= 201)
    g.chat("d2-t2", "Code sent from the verification widget: confirmation prompt", auth, conv, codigo= otp["codigo"],
           estado= "AWAIT_CONFIRMATION")
    g.chat("d2-t3", "Explicit yes: block executed and verified", auth, conv, "Sim, pode bloquear.", estado= "IDLE")
    g.chat("d2-t4", "Closing", auth, conv, "Não, era só isso, valeu.", estado= "ENDED")

    # Sesión del IdP de prueba para un cliente cualquiera del gold.
    prueba = sesion_prueba(g, "idp-session", idp["customer_id"], idioma= "es")
    auth = f"prueba:{idp['customer_id']}"
    conv = abrir_chat(g, "idp-t0", auth)
    g.chat("idp-t1", "Balance: clarification between products", auth, conv, "Hola, ¿cuál es mi saldo?", estado= "SELECT_CARD")
    g.chat("idp-t2", "Credit card chosen by last 4", auth, conv, f"La terminada en {idp['last4']}.", estado= "IDLE")
    g.chat("idp-t3", "\"That card\" keeps the selected card (D-35)", auth, conv,
           "¿Qué movimientos tuvo esa tarjeta en el último mes?", estado= "IDLE")
    g.chat("idp-t4", "Closing", auth, conv, "Gracias, eso es todo.", estado= "ENDED")
    g.llamar("idp-audit", "Audit trail of the test session", "GET", f"/auditoria/{prueba['sesion_id']}", auth= "jurado")

    # Bandeja del agente.
    g.token("agente", g.llamar("agent-login", "Agent signs in", "POST", "/autenticacion/iniciar-sesion",
                               cuerpo= {"correo_electronico": "agente@keyperu.example", "password": g.password}))
    g.llamar("agent-cases", "Case inbox, newest first", "GET", "/casos", auth= "agente", query= {"limite": 10})
    g.llamar("agent-case", "Full case file of dialogue 5", "GET", f"/casos/{caso}", auth= "agente")
    caso_d5 = g.llamar("_", "", "GET", f"/casos/{caso}", auth= "agente", grabar= False)
    g.llamar("agent-audit", "Audit trail of the case's conversation (conversation_ref)", "GET",
             f"/auditoria/conversacion/{caso_d5['conversation_ref']}", auth= "agente")

    # Errores.
    g.llamar("err-login", "Wrong password", "POST", "/autenticacion/iniciar-sesion", http= 401,
             cuerpo= {"correo_electronico": "agente@keyperu.example", "password": "contrasena-incorrecta"})
    g.tokens["invalido"] = "no-es-un-token"
    g.llamar("err-token-invalid", "Malformed or forged token", "GET", "/autenticacion/mi-sesion", http= 401, auth= "invalido")
    del g.tokens["invalido"]
    g.llamar("err-role-forbidden", "A customer calls the agent inbox", "GET", "/casos", auth= f"cliente:{D11}", http= 403)
    g.llamar("err-not-customer", "A jurado token cannot chat", "POST", "/chat/sesiones", auth= "jurado", cuerpo= {}, http= 403)
    g.llamar("err-conversation-forbidden", "Another customer's conversation", "POST", "/chat/mensaje", auth= f"cliente:{D1}",
             cuerpo= {"conversation_id": conv, "mensaje": "Hola"}, http= 403)
    g.llamar("err-validation", "Both a message and a code in one turn", "POST", "/chat/mensaje", auth= f"cliente:{D1}",
             cuerpo= {"conversation_id": conv, "mensaje": "Hola", "codigo_step_up": "123456"}, http= 422)
    g.llamar("err-customer-not-found", "Test session for a customer not in gold", "POST", "/identidad/sesion-prueba",
             auth= "jurado", cuerpo= {"customer_id": "CLI-000000000000"}, http= 404)
    g.chat("ended-message", "Message to an ended conversation: fixed reply, nothing runs", auth, conv, "Hola de nuevo",
           estado= "ENDED")
    g.llamar("err-conversation-closed", "An ended conversation cannot be resumed", "POST", "/chat/sesiones", auth= auth,
             cuerpo= {"conversation_id": conv}, http= 409)

    # Step-up con un código incorrecto (diálogo 9, tarjeta de débito).
    prueba = sesion_prueba(g, None, D9, idioma= "es")
    auth = f"prueba:{D9}"
    conv = abrir_chat(g, "_", auth, grabar= False)
    g.chat("err-stepup-t1", "Block request: step-up required", auth, conv, "Quiero bloquear mi tarjeta de débito.", estado= "STEP_UP")
    g.chat("err-stepup-t2", "Wrong code: asked again (T-29)", auth, conv, codigo= "000000", estado= "STEP_UP")

    # SMS simulado (POL-AUTH-14): el mismo cliente entra con contraseña, como en la web, y pide su propio código.
    auth = entrar_cliente(g, "sms", D9)
    conv = abrir_chat(g, "_", auth, grabar= False)
    g.llamar("err-sms-not-in-step-up", "Simulated SMS with no verification pending", "POST", "/autenticacion/otp-demo",
             auth= auth, http= 409)
    g.chat("sms-t1", "Block request: step-up required", auth, conv, "Quiero bloquear mi tarjeta de débito.", estado= "STEP_UP")
    sms = g.llamar("sms-otp", "Simulated SMS: the customer's own code (development only)", "POST", "/autenticacion/otp-demo",
                   auth= auth, http= 201)
    g.chat("sms-t2", "Code typed in the verification widget: confirmation prompt", auth, conv, codigo= sms["codigo"],
           estado= "AWAIT_CONFIRMATION")
    g.chat("sms-t3", "A no cancels the block; nothing runs", auth, conv, "No, mejor no.", estado= "IDLE")

    # Respaldo del LLM: LLM_MODE=openai contra un puerto cerrado; la respuesta sale con las plantillas.
    prueba = sesion_prueba(g, None, D11, idioma= "es")
    auth = f"prueba:{D11}"
    conv = abrir_chat(g, "_", auth, grabar= False)
    configuracion = dict(llm.CONFIG)
    llm.CONFIG.update(modo= "openai", base_url= "http://127.0.0.1:9/v1")
    os.environ["OPENAI_API_KEY"] = "sk-local-unreachable"
    llm.cliente_llm.cliente, llm.cliente_llm.dormir = None, lambda segundos: None
    try:
        g.chat("err-llm-fallback", "LLM unreachable: same reply from the code's sentences (POL-REL-04)", auth, conv,
               "Hola, ¿cuál es mi saldo?", estado= "SELECT_CARD")
    finally:
        llm.CONFIG.clear()
        llm.CONFIG.update(configuracion)
        os.environ.pop("OPENAI_API_KEY", None)
        llm.cliente_llm.cliente = None
    g.llamar("err-llm-fallback-audit", "Audit of the fallback turn", "GET", f"/auditoria/{prueba['sesion_id']}", auth= "jurado")

    # Límite de búsquedas del IdP de prueba (10 por minuto por jurado).
    identidad.limitador_busqueda.reiniciar()
    for _ in range(10):
        g.llamar("_", "", "GET", "/identidad/clientes", auth= "jurado", grabar= False)
    g.llamar("err-rate-limited", "Eleventh search in a minute", "GET", "/identidad/clientes", auth= "jurado", http= 429)

    # Registro abierto (solo ENV=development) y cierre de sesión.
    g.llamar("register", "Open registration (development only): a customer user with no bank data", "POST",
             "/autenticacion/registrar", http= 201,
             cuerpo= {"nombre": "Usuario de prueba", "correo_electronico": "nuevo@ejemplo.keyperu.example", "password": g.password})
    g.token("cliente:nuevo", g.llamar("_", "", "POST", "/autenticacion/iniciar-sesion", grabar= False,
                                      cuerpo= {"correo_electronico": "nuevo@ejemplo.keyperu.example", "password": g.password}))
    g.llamar("err-no-customer", "A registered user without a customer cannot chat", "POST", "/chat/sesiones",
             auth= "cliente:nuevo", cuerpo= {}, http= 403)
    g.llamar("logout", "Sign out", "POST", "/autenticacion/cerrar-sesion", auth= "cliente:nuevo", http= 204)
    g.llamar("err-after-logout", "The token stops working after sign-out", "GET", "/autenticacion/mi-sesion",
             auth= "cliente:nuevo", http= 401)

    # Sesión vencida (al final: adelanta el reloj de identidad de todas las sesiones).
    prueba = sesion_prueba(g, None, D11, idioma= "es")
    auth = f"prueba:{D11}"
    conv = abrir_chat(g, "expiry-t0", auth)
    g.chat("expiry-t1", "Balance: clarification", auth, conv, "Hola, ¿cuál es mi saldo?", estado= "SELECT_CARD")
    reloj = identidad.ahora_utc
    identidad.ahora_utc = lambda: reloj() + timedelta(minutes= identidad.SESION_INACTIVIDAD_MIN + 1)
    try:
        g.chat("expiry-t2", "Idle timeout: no data, sign in again (G-01)", auth, conv, "La tarjeta de crédito.",
               estado= "SESSION_EXPIRED")
        g.llamar("expiry-session", "Any other endpoint answers 401", "GET", "/autenticacion/mi-sesion", auth= auth, http= 401)
        g.token("jurado", g.llamar("_", "", "POST", "/autenticacion/iniciar-sesion", grabar= False,
                                   cuerpo= {"correo_electronico": "jurado@keyperu.example", "password": g.password}))
        sesion_prueba(g, None, D11, idioma= "es")
        g.llamar("expiry-resume", "New session resumes the conversation (G-02)", "POST", "/chat/sesiones", auth= auth,
                 cuerpo= {"conversation_id": conv}, http= 201, estado= "IDLE")
        g.chat("expiry-t3", "Customer accepts the resume question (T-50)", auth, conv, "Sí", estado= "SELECT_CARD")
    finally:
        identidad.ahora_utc = reloj


# --- salida ---------------------------------------------------------------------------------------

def bloque(ejemplo: Dict[str, Any], opciones: Optional[Dict[str, str]] = None) -> str:
    """Pedido y respuesta en un bloque http. En un audit log, `types` deja el primer evento de cada tipo, del turno
    `turn` si se da."""
    opciones = opciones or {}
    pedido, respuesta = ejemplo["request"], ejemplo["response"]
    lineas = [f"{pedido['method']} {pedido['path']}" + (f"?{urlencode(pedido['query'])}" if pedido.get("query") else "")]
    if pedido.get("auth"):
        lineas.append(f"Authorization: Bearer <{ETIQUETAS_AUTH[pedido['auth'].split(':')[0]]}>")
    if pedido.get("body") is not None:
        lineas += ["", json.dumps(pedido["body"], ensure_ascii= False, indent= 2)]
    cuerpo = respuesta["body"]
    if opciones.get("types") and isinstance(cuerpo, dict) and "eventos" in cuerpo:
        eventos = [e for e in cuerpo["eventos"] if "turn" not in opciones or e["turn_index"] == int(opciones["turn"])]
        elegidos = [next(e for e in eventos if e["event_type"] == tipo) for tipo in opciones["types"].split(",")
                    if any(e["event_type"] == tipo for e in eventos)]
        cuerpo = {**cuerpo, "eventos": elegidos,
                  "_excerpt": f"{len(elegidos)} of {cuerpo['total']} events; the full trail is in chat_api_examples.json"}
    lineas += ["", f"HTTP {respuesta['status']}"]
    if cuerpo is not None:
        lineas.append(json.dumps(cuerpo, ensure_ascii= False, indent= 2))
    return f"`{ejemplo['id']}` · {ejemplo['title']}\n\n```http\n" + "\n".join(lineas) + "\n```"


def actualizar_doc(ruta: Path, ejemplos: List[Dict[str, Any]]) -> int:
    texto = ruta.read_text(encoding= "utf-8")
    por_id = {e["id"]: e for e in ejemplos}
    faltan: List[str] = []

    def reemplazar(marca: re.Match) -> str:
        clase, clave, extra = marca.group(1), marca.group(2), marca.group(3)
        opciones = dict(o.split("=", 1) for o in extra.split())
        if clase == "example":
            elegidos = [por_id[clave]] if clave in por_id else []
        else:
            elegidos = [e for e in ejemplos if e["id"].startswith(clave)]
        if not elegidos:
            faltan.append(clave)
            return marca.group(0)
        cuerpo = "\n\n".join(bloque(e, opciones) for e in elegidos)
        return f"<!-- {clase}: {clave}{extra} -->\n{cuerpo}\n<!-- /example -->"

    nuevo, cantidad = _MARCADOR.subn(reemplazar, texto)
    if faltan:
        raise SystemExit(f"{ruta.name} cita ejemplos que no se capturaron: {faltan}")
    ruta.write_text(nuevo, encoding= "utf-8")
    return cantidad


def main(argumentos: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description= "Captura los ejemplos de docs/contracts/chat_api.md y exporta el OpenAPI.")
    parser.add_argument("--gold", type= Path, default= RAIZ_REPO / "ml" / "data" / "demo_gold")
    opciones = parser.parse_args(argumentos)
    gold = opciones.gold.resolve()
    if not (gold / "_load_log.parquet").is_file():
        print(f"No hay gold en {gold}. Genérelo con ml/scripts/make_demo_gold.py o descomprima ml/data/demo_gold.zip.")
        return 1

    password = preparar_entorno(gold)
    from fastapi.testclient import TestClient
    from sqlmodel import Session

    from db import crear_db_y_tablas
    from db.config import motor
    from main import app
    from scripts.sembrar_usuarios import clientes_ausentes_en_gold, sembrar

    crear_db_y_tablas()
    with Session(motor) as sesion:
        sembrar(sesion, password)
    if ausentes := clientes_ausentes_en_gold():
        print(f"Faltan clientes golden en {gold}: {ausentes}")
        return 1

    with TestClient(app) as http:
        grabadora = Grabadora(http, password)
        capturar(grabadora, gold)

    ejemplos = grabadora.ejemplos
    salida = {
        "generated_by": "backend/scripts/capturar_contrato_api.py",
        "gold": gold.name, "bank_clock": RELOJ_GOLDEN, "llm_mode": "mock",
        "examples": ejemplos,
    }
    (DIR_CONTRATOS / "chat_api_examples.json").write_text(json.dumps(salida, ensure_ascii= False, indent= 1) + "\n", encoding= "utf-8")
    (DIR_CONTRATOS / "openapi.json").write_text(json.dumps(app.openapi(), ensure_ascii= False, indent= 1) + "\n", encoding= "utf-8")
    doc = DIR_CONTRATOS / "chat_api.md"
    bloques = actualizar_doc(doc, ejemplos) if doc.is_file() else 0
    print(f"{len(ejemplos)} ejemplos en docs/contracts/chat_api_examples.json, {bloques} bloques en chat_api.md, "
          f"{len(app.openapi()['paths'])} rutas en docs/contracts/openapi.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
