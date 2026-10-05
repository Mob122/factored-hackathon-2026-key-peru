"""Pasos 2 a 4 del turno (docs/contracts/state_machine.md sección 4): redacción, idioma y controles
de seguridad. Todo es código determinista; nada de esto lo decide el LLM (POL-GEN-01).

- redactar: POL-PII-01 y POL-PII-04. Un número de tarjeta completo queda como <CARD_1234> (solo los
  últimos 4, el formato que el clasificador entiende) y su valor crudo solo vive en memoria para la
  comprobación de propiedad (POL-ESC-10). Contraseñas y códigos quedan como [SECRET_n] (POL-AUTH-08).
- inyeccion_sospechada: POL-ESC-08.
- pide_datos_de_tercero: POL-ESC-10 (b).
- detectar_idioma: POL-GEN-03 (solo el texto; nunca el país del cliente).
- respuestas sí/no, últimos 4 y tipo de producto en estados de espera (docs/intents.md regla 7).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import hashlib
import hmac
import re
import unicodedata

from security.config import AUDIT_KEY


@dataclass
class Redaccion:
    texto: str # Texto redactado: lo único que ven el clasificador, el LLM, los logs y el audit log.
    numeros_tarjeta: List[str] = field(default_factory= list) # Crudos, solo en memoria (POL-PII-04).
    customer_ids: List[str] = field(default_factory= list) # Crudos, solo en memoria.
    secretos: int = 0
    marcadores: Dict[str, int] = field(default_factory= dict)


_PAN = re.compile(r"(?<![\d<])(?:\d[ -]?){12,18}\d(?![\d>])")
_CUSTOMER_ID = re.compile(r"\bCLI-[A-Za-z0-9]{12}\b")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Con separadores o prefijo +, o 10 a 12 dígitos seguidos: un monto como 1805684 no es un teléfono.
_TELEFONO = re.compile(r"(?<![\d.,])(?:\+\d{1,3}[ -]?\(?\d{2,3}\)?[ -]?\d{3,4}[ -]?\d{4}|\(?\d{2,3}\)?[ -]\d{3,4}[ -]\d{4}|\d{10,12})(?![\d.,])")
_DOCUMENTO = re.compile(r"\b(?:dni|c[eé]dula|cpf|rfc|curp|documento|pasaporte|passaporte|cc|ine)\s*(?:n[uú]mero\s*)?(?:es|é|:|#|nro\.?)?\s*([A-Za-z0-9.\-]{6,20})", re.I)
_SECRETO = re.compile(
    r"\b(?:contrase[ñn]a|clave|password|senha|pin|nip|c[oó]digo(?: de verificaci[oó]n)?|otp|token)\s*"
    r"(?:es|era|é|:|=)?\s*([A-Za-z0-9!@#$%^&*._-]{4,})",
    re.I,
)
_NOMBRE = re.compile(r"\b(?:me llamo|mi nombre es|meu nome é|me chamo)\s+([A-ZÁÉÍÓÚÑÃÕÇ][\wáéíóúñãõç]+(?:\s+[A-ZÁÉÍÓÚÑÃÕÇ][\wáéíóúñãõç]+){0,3})", re.I)
_CODIGO_SUELTO = re.compile(r"^\D{0,20}(\d{4,8})\D{0,10}$")


def redactar(texto: str, *, esperando_codigo: bool = False) -> Redaccion:
    """Reemplaza PII por marcadores tipados antes del clasificador, el LLM, los logs y el audit log."""
    resultado = Redaccion(texto= texto)
    cuenta: Dict[str, int] = {}

    def marcador(tipo: str) -> str:
        cuenta[tipo] = cuenta.get(tipo, 0) + 1
        return f"[{tipo}_{cuenta[tipo]}]"

    def pan(m: re.Match) -> str:
        digitos = re.sub(r"\D", "", m.group(0))
        resultado.numeros_tarjeta.append(digitos)
        cuenta["CARD_PAN"] = cuenta.get("CARD_PAN", 0) + 1
        return f"<CARD_{digitos[-4:]}>"

    def secreto(m: re.Match) -> str:
        resultado.secretos += 1
        return m.group(0).replace(m.group(1), marcador("SECRET"))

    def cliente(m: re.Match) -> str:
        resultado.customer_ids.append(m.group(0).upper())
        return f"<CUSTOMER_ID_{len(resultado.customer_ids)}>"

    t = _SECRETO.sub(secreto, texto)
    t = _PAN.sub(pan, t)
    t = _CUSTOMER_ID.sub(cliente, t)
    t = _EMAIL.sub(lambda m: marcador("EMAIL"), t)
    t = _DOCUMENTO.sub(lambda m: m.group(0).replace(m.group(1), marcador("DOC")), t)
    t = _TELEFONO.sub(lambda m: marcador("PHONE"), t)
    t = _NOMBRE.sub(lambda m: m.group(0).replace(m.group(1), marcador("NAME")), t)
    if esperando_codigo and _CODIGO_SUELTO.match(t):
        # En STEP_UP, un código escrito en el chat es un secreto (POL-AUTH-08), nunca se usa.
        resultado.secretos += 1
        t = _CODIGO_SUELTO.sub(lambda m: m.group(0).replace(m.group(1), marcador("SECRET")), t)

    resultado.texto = t
    resultado.marcadores = cuenta
    return resultado


def huella_tercero(valor: str) -> str:
    """AL-P5: un identificador de un tercero solo se guarda como HMAC-SHA256(AUDIT_KEY, valor normalizado)."""
    return hmac.new(AUDIT_KEY.encode("utf-8"), valor.strip().upper().encode("utf-8"), hashlib.sha256).hexdigest()


def normalizar(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto.lower())
    sin_acentos = "".join(c for c in base if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9<>_]+", " ", sin_acentos).strip()


# --- POL-ESC-08: inyección ------------------------------------------------------------------------

_INYECCION = [
    re.compile(r"</?\s*(?:user|system|assistant|usuario|sistema)\s*>", re.I),
    re.compile(r"\b(?:system|sistema)\s*:", re.I),
    re.compile(r"\b(?:ignor\w*|olvid\w*|esquec\w*|desconsider\w*)\b.{0,40}\b(?:regla|reglas|pol[ií]tica\w*|instrucci\w*|instru[cç][oõ]\w*|norma\w*|regra\w*)", re.I),
    re.compile(r"\b(?:modo|mode)\s+(?:mantenimiento|manuten[cç][aã]o|desarrollador|desenvolvedor|developer|admin\w*|debug|dios)\b", re.I),
    re.compile(r"\b(?:soy|sou|como)\s+(?:el |la |o |a )?(?:administrador\w*|admin|gerente|supervisor\w*|empleado del banco|funcionari[oa] do banco)\b", re.I),
    re.compile(r"\bverificad[oa] como administrador", re.I),
    re.compile(r"\b(?:unblock_card|block_card|open_handoff|get_balance|list_cards|get_card_status|list_transactions|describe_transaction|step_up|authenticate)\b", re.I),
    re.compile(r"\b[a-z_]{3,}\(\s*[a-z_]+\s*=", re.I),
    re.compile(r"\b(?:responde|responda|contesta|diga|di)\s+(?:solo|solamente|apenas|somente)\s*:", re.I),
    re.compile(r"\b(?:prompt|instrucciones del sistema|instru[cç][oõ]es do sistema)\b", re.I),
]


def inyeccion_sospechada(texto_redactado: str) -> bool:
    return any(p.search(texto_redactado) for p in _INYECCION)


# --- POL-ESC-10 (b): datos de otra persona -------------------------------------------------------

_PARIENTE = (r"(?:espos[oa]|marido|mujer|novi[oa]|herman[oa]|hij[oa]|padre|madre|papa|mama|amig[oa]|jefe|abuel[oa]|"
             r"ti[oa]|filh[oa]|irma[o]?|pai|mae|namorad[oa]|chefe|prim[oa]|sobrin[oa]|cunhad[oa]|cunad[oa]|vecin[oa]|socio)")
_TERCERO = [
    re.compile(rf"\b(?:de|da|do|del)\s+(?:mi|mis|minha|meu|meus|minhas)\s+{_PARIENTE}\b"),
    re.compile(rf"\b(?:mi|minha|meu)\s+{_PARIENTE}\s+(?:perdio|perdeu|quiere|quer|tiene|tem|necesita|precisa)\b"),
    re.compile(r"\b(?:de otra persona|de outra pessoa|de un tercero|de terceiros|de otro cliente|de outro cliente)\b"),
]


def pide_datos_de_tercero(texto_redactado: str, customer_ids: List[str], customer_id_sesion: str) -> bool:
    """Un customer_id ajeno escrito en el mensaje, o un pedido sobre la tarjeta o cuenta de otra persona."""
    if any(c != customer_id_sesion for c in customer_ids):
        return True
    norm = normalizar(texto_redactado)
    return any(p.search(norm) for p in _TERCERO)


# --- POL-GEN-03: idioma -------------------------------------------------------------------------

_PT = re.compile(r"\b(?:voce|nao|cartao|cartoes|quero|meu|minha|obrigad[oa]|ola|oi|conta poupanca|saldo da|qual|quais|bloqueia|preciso|tambem|isso|por favor me|fatura|atendente|sim)\b")
_ES = re.compile(r"\b(?:usted|tarjeta|tarjetas|quiero|mi|gracias|hola|cual|cuanto|cuenta de ahorros|bloquear la|necesito|tambien|eso|asesor|si|senor|buenos|buenas)\b")


def idioma_elegido(texto: str) -> Optional[str]:
    """Respuesta a "¿español o portugués?" (POL-ESC-11)."""
    norm = normalizar(texto)
    if re.search(r"\b(?:portugues|portuguesa|portugal|brasil\w*)\b", norm):
        return "pt"
    if re.search(r"\b(?:espanol|castellano|espanhol)\b", norm):
        return "es"
    return None


def detectar_idioma(texto: str) -> Optional[str]:
    """"es", "pt" o None si no se puede decidir (POL-ESC-11)."""
    crudo = texto.lower()
    norm = normalizar(texto)
    pt = len(_PT.findall(norm)) + 2 * sum(crudo.count(c) for c in ("ã", "õ", "ç"))
    es = len(_ES.findall(norm)) + 2 * sum(crudo.count(c) for c in ("ñ", "¿", "¡"))
    if pt > es:
        return "pt"
    if es > pt:
        return "es"
    return None


# --- Respuestas en estados de espera (docs/intents.md regla 7) ------------------------------------

_SI = re.compile(r"^(?:si|sim|claro|dale|ok|okay|okey|de acuerdo|correcto|exacto|afirmativo|ese|esa|esse|essa|isso|eso|confirmo|confirmado|adelante|hagalo|pode|bloqueela|bloquea|bloqueie|bloqueia)\b")
_NO = re.compile(r"^(?:no|nao|nop|negativo|mejor no|ahora no|todavia no|ainda nao|agora nao|cancel\w*|ninguno|ninguna|nenhum\w*)\b")
_DUDA = re.compile(r"\b(?:creo|tal vez|talvez|quizas|quiza|capaz|acho|pero|mas antes|aunque|primero|antes|no se|nao sei|supongo|mmm)\b")


def respuesta_si_no(texto: str) -> Optional[str]:
    """"si", "no" o None (ambigua u otra cosa). Una afirmación con dudas no cuenta (POL-ACT-03)."""
    norm = normalizar(texto)
    if _NO.match(norm):
        return "no"
    if _SI.match(norm):
        dudosa = _DUDA.search(norm) or re.search(r"\b(?:no|nao)\b", norm)
        return None if dudosa else "si"
    return None


_ULTIMOS4 = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def ultimos4_en(texto_redactado: str) -> List[str]:
    tarjetas = re.findall(r"<CARD_(\d{4})>", texto_redactado)
    sueltos = _ULTIMOS4.findall(re.sub(r"<CARD_\d{4}>", " ", texto_redactado))
    return tarjetas + sueltos


def tipo_producto_en(texto: str) -> Optional[str]:
    """credit_card, debit_card, savings_account, card o None, para elegir entre candidatos."""
    norm = normalizar(texto)
    if re.search(r"\b(?:cuenta de ahorros?|caja de ahorros?|conta poupanca|poupanca|ahorros?)\b", norm):
        return "savings_account"
    if re.search(r"\b(?:debito|debit)\b", norm):
        return "debit_card"
    if re.search(r"\b(?:credito|credit)\b", norm):
        return "credit_card"
    if re.search(r"\b(?:tarjeta|cartao|plastico)\b", norm):
        return "card"
    return None


_CANCELAR = re.compile(r"\b(?:cancel\w*|olvid\w*|deja(?:lo)?|dejalo|mejor no|esquece|esqueca|deixa pra la|nada|no importa|nao importa)\b")


def es_cancelacion(texto: str) -> bool:
    return bool(_CANCELAR.search(normalizar(texto))) or respuesta_si_no(texto) == "no"


_VENCIMIENTO = re.compile(r"\b(?:vencid\w*|vence\w*|vencimiento|expir\w*|caducad\w*|validade|valida hasta|venceu)\b")


def pregunta_vencimiento(texto: str) -> bool:
    """Preguntas sobre la vigencia de la tarjeta: nunca se responden (POL-ANS-13, POL-ESC-04)."""
    return bool(_VENCIMIENTO.search(normalizar(texto)))


_CONTINUACION = re.compile(r"^(?:y|e|and|tambien|tambem|ahora|agora)\b")


def es_continuacion(texto: str) -> bool:
    """Empieza como seguimiento de lo anterior ("¿Y el de…?", "E o do…?"), para POL-ESC-14."""
    norm = normalizar(texto)
    return bool(_CONTINUACION.match(norm)) and len(norm.split()) <= 8
