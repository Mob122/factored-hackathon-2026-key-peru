"""Textos del asistente en español y portugués.

- PLANTILLAS: las plantillas de docs/policy_cards.md (BAL, TXS, DEC, ACT, HND), copiadas tal cual.
  Las rinde el código; el LLM no las reescribe.
- FRASES: oraciones fijas de política (pedir el código, aviso de confirmación, rechazos...),
  tomadas de las conversaciones golden. Tampoco las reescribe el LLM.
- Formato de números y fechas de la sección 3b: México 1,234.56; Colombia y Argentina 1.234,56.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

IDIOMAS = ("es", "pt")

PLANTILLAS: Dict[str, Dict[str, str]] = {
    "POL-BAL-01": {
        "es": "El saldo actual de su tarjeta de crédito terminada en {ultimos4} es de {saldo} {moneda} y su límite de crédito es de {limite} {moneda}, según los datos del {as_of}.",
        "pt": "O saldo atual do seu cartão de crédito final {ultimos4} é de {saldo} {moneda} e o limite de crédito é de {limite} {moneda}, segundo os dados de {as_of}.",
    },
    "POL-BAL-02": {
        "es": "El saldo actual de su cuenta de ahorros terminada en {ultimos4} es de {saldo} {moneda}, según los datos del {as_of}.",
        "pt": "O saldo atual da sua conta poupança final {ultimos4} é de {saldo} {moneda}, segundo os dados de {as_of}.",
    },
    "POL-BAL-03": {
        "es": "Estos datos pueden no incluir los movimientos más recientes.",
        "pt": "Esses dados podem não incluir as movimentações mais recentes.",
    },
    "POL-BAL-04": {
        "es": "No puedo confirmar el límite de crédito de esta tarjeta.",
        "pt": "Não consigo confirmar o limite de crédito deste cartão.",
    },
    "POL-BAL-05": {
        "es": "No puedo calcular el crédito disponible; solo puedo indicarle el saldo y el límite registrados. Si lo necesita, puedo transferirle con un asesor.",
        "pt": "Não consigo calcular o crédito disponível; só posso informar o saldo e o limite registrados. Se precisar, posso transferir você para um atendente.",
    },
    "POL-BAL-06": {
        "es": "El saldo actual de su tarjeta de crédito terminada en {ultimos4} es de {saldo} {moneda}, según los datos del {as_of}.",
        "pt": "O saldo atual do seu cartão de crédito final {ultimos4} é de {saldo} {moneda}, segundo os dados de {as_of}.",
    },
    "POL-ACT-10": {
        "es": "No pude confirmar si su tarjeta terminada en {ultimos4} quedó bloqueada. Por seguridad, considere que la tarjeta NO está bloqueada. Transferí su caso a un asesor como urgente, referencia {case_id}.",
        "pt": "Não consegui confirmar se o seu cartão final {ultimos4} foi bloqueado. Por segurança, considere que o cartão NÃO está bloqueado. Transferi o seu caso para um atendente como urgente, referência {case_id}.",
    },
    "POL-ACT-11": {
        "es": "Listo: su tarjeta {tipo} terminada en {ultimos4} está bloqueada. Para desbloquearla o pedir una tarjeta nueva, tiene que hablar con un asesor; puedo transferirle si lo desea.",
        "pt": "Pronto: o seu cartão {tipo} final {ultimos4} está bloqueado. Para desbloquear ou pedir um cartão novo, é preciso falar com um atendente; posso transferir você, se quiser.",
    },
    "POL-ACT-13": {
        "es": "Si hay cargos en esta tarjeta que usted no reconoce, dígame cuáles y abro un reclamo con un asesor.",
        "pt": "Se houver compras neste cartão que você não reconhece, me diga quais e eu abro uma contestação com um atendente.",
    },
    "POL-HND-03": {
        "es": "Un asesor revisará su caso, referencia {case_id}.",
        "pt": "Um atendente vai analisar o seu caso, referência {case_id}.",
    },
    "POL-HND-04": {
        "es": "Agregué su mensaje a su caso, referencia {case_id}. Un asesor lo revisará.",
        "pt": "Adicionei sua mensagem ao seu caso, referência {case_id}. Um atendente vai analisá-la.",
    },
    "POL-HND-05": {
        "es": "No pude registrar su caso en este momento. Por favor, comuníquese con el centro de contacto del banco.",
        "pt": "Não consegui registrar o seu caso agora. Por favor, entre em contato com a central de atendimento do banco.",
    },
    "POL-HND-07": {
        "es": "Para atender su solicitud, un asesor necesita revisar su caso.",
        "pt": "Para atender a sua solicitação, um atendente precisa analisar o seu caso.",
    },
    "POL-HND-08": {
        "es": "¿Quiere que le pase con un asesor?",
        "pt": "Quer que eu transfira você para um atendente?",
    },
    "POL-DEC-PREFIX": {
        "es": "Tiene registrado el código de respuesta {codigo}, que en las redes de pago significa: {significado}",
        "pt": "Tem registrado o código de resposta {codigo}, que nas redes de pagamento significa: {significado}",
    },
    "POL-DEC-DISCLAIMER": {
        "es": "Este código es lo que muestra el registro; no me permite confirmar la causa. Si necesita saber por qué ocurrió, puedo transferirle con un asesor.",
        "pt": "Esse código é o que consta no registro; ele não me permite confirmar a causa. Se precisar saber por que isso aconteceu, posso transferir você para um atendente.",
    },
    "POL-DEC-90": {
        "es": "No hay un código de respuesta registrado para esta transacción.",
        "pt": "Não há código de resposta registrado para esta transação.",
    },
    "POL-DEC-91": {
        "es": "No tengo una descripción aprobada para este código.",
        "pt": "Não tenho uma descrição aprovada para este código.",
    },
}

SIGNIFICADO_DEC = {
    "05": {"es": "no autorizada por el emisor, sin un motivo específico.", "pt": "não autorizada pelo emissor, sem motivo específico."},
    "14": {"es": "número de tarjeta inválido.", "pt": "número de cartão inválido."},
    "51": {"es": "fondos insuficientes.", "pt": "saldo insuficiente."},
    "54": {"es": "tarjeta vencida.", "pt": "cartão vencido."},
}

# Sujeto de las plantillas TXS (política sección 6): (texto, género).
SUJETO_TXS = {
    "Purchase": {"es": ("La compra", "f"), "pt": ("A compra", "f")},
    "Payment": {"es": ("El pago", "m"), "pt": ("O pagamento", "m")},
    "Withdrawal": {"es": ("El retiro", "m"), "pt": ("O saque", "m")},
}
PREDICADO_TXS = {
    "POL-TXS-01": {"es": {"f": "fue aprobada.", "m": "fue aprobado."}, "pt": {"f": "foi aprovada.", "m": "foi aprovado."}},
    "POL-TXS-02": {"es": {"f": "fue rechazada.", "m": "fue rechazado."}, "pt": {"f": "foi recusada.", "m": "foi recusado."}},
    "POL-TXS-03": {"es": {"f": "está pendiente: aún no se ha completado.", "m": "está pendiente: aún no se ha completado."},
                   "pt": {"f": "está pendente: ainda não foi concluída.", "m": "está pendente: ainda não foi concluído."}},
    "POL-TXS-04": {"es": {"f": "fue revertida: se anuló después de registrarse.", "m": "fue revertido: se anuló después de registrarse."},
                   "pt": {"f": "foi estornada: foi anulada depois de registrada.", "m": "foi estornado: foi anulado depois de registrado."}},
}

FRASES: Dict[str, Dict[str, str]] = {
    "saludo": {"es": "Hola, ¿en qué puedo ayudarle?", "pt": "Olá, em que posso ajudar?"},
    "capacidades": {  # POL-ANS-05: texto estático versionado con la política.
        "es": "Puedo ayudarle con el saldo de sus tarjetas de crédito y cuentas de ahorro, el estado de sus tarjetas, sus transacciones recientes, el bloqueo de una tarjeta y la transferencia con un asesor.",
        "pt": "Posso ajudar com o saldo dos seus cartões de crédito e contas poupança, a situação dos seus cartões, as suas transações recentes, o bloqueio de um cartão e a transferência para um atendente.",
    },
    "fuera_de_alcance": {"es": "Eso no es algo que pueda hacer por aquí.", "pt": "Isso não é algo que eu possa fazer por aqui."},
    "cierre": {"es": "Con gusto. Hasta luego.", "pt": "Por nada. Até logo."},
    "conversacion_terminada": {"es": "Esta conversación terminó. Si necesita algo más, inicie una nueva.", "pt": "Esta conversa terminou. Se precisar de algo mais, inicie uma nova."},
    "pedir_codigo": {
        "es": "Para bloquearla necesito confirmar su identidad con un código de verificación; ingréselo en la ventana de verificación, no en el chat.",
        "pt": "Para bloquear, preciso confirmar sua identidade com um código de verificação; digite-o na janela de verificação, não aqui no chat.",
    },
    "pedir_codigo_nuevo": {
        "es": "Para bloquearla necesito un nuevo código de verificación; ingréselo en la ventana de verificación.",
        "pt": "Para bloquear, preciso de um novo código de verificação; digite-o na janela de verificação.",
    },
    "codigo_invalido": {"es": "El código no es válido o venció. Ingréselo de nuevo en la ventana de verificación.", "pt": "O código não é válido ou expirou. Digite-o de novo na janela de verificação."},
    "identidad_confirmada": {"es": "Identidad confirmada.", "pt": "Identidade confirmada."},
    "aviso_bloqueo": {  # POL-ACT-02
        "es": "Voy a bloquear su tarjeta {tipo} terminada en {ultimos4}. Después del bloqueo la tarjeta deja de funcionar y yo no puedo desbloquearla; eso solo lo hace un asesor.",
        "pt": "Vou bloquear o seu cartão {tipo} final {ultimos4}. Depois do bloqueio ele deixa de funcionar e eu não consigo desbloqueá-lo; só um atendente pode fazer isso.",
    },
    "pregunta_bloqueo": {
        "es": "¿Confirma el bloqueo de la tarjeta terminada en {ultimos4}? Responda sí o no.",
        "pt": "Confirma o bloqueio do cartão final {ultimos4}? Responda sim ou não.",
    },
    "bloqueo_cancelado": {"es": "Entendido, no bloqueé la tarjeta.", "pt": "Entendido, não bloqueei o cartão."},
    "ya_bloqueada": {"es": "Su tarjeta {tipo} terminada en {ultimos4} ya está bloqueada.", "pt": "O seu cartão {tipo} final {ultimos4} já está bloqueado."},
    "no_codigo_en_chat": {
        "es": "Por seguridad, no escriba contraseñas ni códigos en el chat; use la ventana de verificación.",
        "pt": "Por segurança, não escreva senhas nem códigos no chat; use a janela de verificação.",
    },
    "no_numero_en_chat": {"es": "Por seguridad, no escriba números de tarjeta completos en el chat.", "pt": "Por segurança, não escreva números de cartão completos no chat."},
    "sin_verificacion_pendiente": {"es": "No hay ninguna verificación pendiente.", "pt": "Não há nenhuma verificação pendente."},
    "sesion_vencida_accion": {"es": "Su sesión expiró por inactividad, así que no bloqueé la tarjeta.", "pt": "A sua sessão expirou por inatividade, então não bloqueei o cartão."},
    "sesion_vencida": {"es": "Su sesión expiró.", "pt": "A sua sessão expirou."},
    "iniciar_sesion": {"es": "Por favor, inicie sesión de nuevo para continuar.", "pt": "Por favor, faça login novamente para continuar."},
    "sesion_iniciada": {"es": "Sesión iniciada.", "pt": "Sessão iniciada."},
    "retomar": {"es": "¿Quiere retomar lo que estaba haciendo?", "pt": "Quer retomar o que estava fazendo?"},
    "entendido": {"es": "Entendido.", "pt": "Entendido."},
    "tarjeta_no_encontrada": {"es": "No encuentro esa tarjeta entre las suyas.", "pt": "Não encontro esse cartão entre os seus."},
    "cual_consultar": {"es": "¿Cuál de ellas quiere consultar?", "pt": "Qual deles quer consultar?"},
    "cual_tipo": {"es": "Tiene más de un producto terminado en {ultimos4}. ¿Es la tarjeta de crédito, la de débito o la cuenta de ahorros?",
                  "pt": "Você tem mais de um produto final {ultimos4}. É o cartão de crédito, o de débito ou a conta poupança?"},
    "solo_titular": {
        "es": "Solo puedo mostrar información de los productos de la persona que inició sesión.",
        "pt": "Só posso mostrar informações dos produtos da pessoa que fez login.",
    },
    "solo_titular_numero_cliente": {
        "es": "Solo puedo mostrar información de las tarjetas de la persona que inició sesión, y un número de cliente no sirve para autorizar el acceso.",
        "pt": "Só posso mostrar informações dos cartões da pessoa que fez login, e um número de cliente não serve para autorizar o acesso.",
    },
    "no_desbloqueo": {"es": "No puedo desbloquear tarjetas.", "pt": "Não consigo desbloquear cartões."},
    "transferire_desbloqueo": {
        "es": "Su tarjeta {tipo} terminada en {ultimos4} figura como {estado}, así que transferiré la solicitud de desbloqueo.",
        "pt": "O seu cartão {tipo} final {ultimos4} consta como {estado}, então vou transferir a solicitação de desbloqueio.",
    },
    "transferire_desbloqueo_sin_tarjeta": {"es": "Transferiré la solicitud a un asesor.", "pt": "Vou transferir a solicitação para um atendente."},
    "sin_causa_bloqueo": {
        "es": "No tengo información sobre la causa ni la fecha de ese estado, así que transferiré su consulta a un asesor.",
        "pt": "Não tenho informação sobre a causa nem a data dessa situação, então vou transferir a sua consulta para um atendente.",
    },
    "transferir_humano": {"es": "Le transfiero con un asesor.", "pt": "Vou transferir você para um atendente."},
    "no_entendi": {"es": "No logré entender su solicitud, así que la transfiero a un asesor.", "pt": "Não consegui entender a sua solicitação, então vou transferi-la para um atendente."},
    "fallo_servicio": {"es": "No puedo completar su solicitud en este momento.", "pt": "Não consigo concluir a sua solicitação agora."},
    "estado_no_permite": {"es": "Por el estado de la tarjeta, un asesor tiene que atender esta solicitud.", "pt": "Pela situação do cartão, um atendente precisa atender esta solicitação."},
    "ninguna_elegible_tarjetas_activas": {"es": "No tiene tarjetas activas.", "pt": "Você não tem cartões ativos."},
    "ninguna_elegible_tarjetas": {"es": "No encuentro tarjetas para esta consulta.", "pt": "Não encontro cartões para esta consulta."},
    "ninguna_elegible_saldo": {"es": "No tiene tarjetas de crédito ni cuentas de ahorro con saldo consultable.", "pt": "Você não tem cartões de crédito nem contas poupança com saldo para consultar."},
    "ofrecer_transferencia": {"es": "Si lo necesita, puedo transferirle con un asesor.", "pt": "Se precisar, posso transferir você para um atendente."},
    "no_vencimiento": {"es": "No puedo confirmar fechas de vencimiento de la tarjeta.", "pt": "Não consigo confirmar datas de vencimento do cartão."},
    "no_vencimiento_codigo": {
        "es": "No puedo confirmar fechas de vencimiento, así que no puedo decirle si el código {codigo} corresponde al estado real de su tarjeta.",
        "pt": "Não consigo confirmar datas de vencimento, então não posso dizer se o código {codigo} corresponde à situação real do seu cartão.",
    },
    "no_transacciones": {
        "es": "No encontré transacciones de su tarjeta {tipo} terminada en {ultimos4} entre el {desde} y el {hasta}.",
        "pt": "Não encontrei transações do seu cartão {tipo} final {ultimos4} entre {desde} e {hasta}.",
    },
    "transacciones_encabezado": {
        "es": "Estas son las transacciones de su tarjeta {tipo} terminada en {ultimos4} entre el {desde} y el {hasta}:",
        "pt": "Estas são as transações do seu cartão {tipo} final {ultimos4} entre {desde} e {hasta}:",
    },
    "transacciones_tope": {"es": "Le muestro las {n} más recientes.", "pt": "Mostro as {n} mais recentes."},
    "ventana_limite": {
        "es": "Solo puedo consultar los últimos {dias} días. Si necesita movimientos anteriores, puedo transferirle con un asesor.",
        "pt": "Só consigo consultar os últimos {dias} dias. Se precisar de movimentações anteriores, posso transferir você para um atendente.",
    },
    "cual_transaccion": {"es": "¿Cuál de ellas quiere que le explique?", "pt": "Qual delas quer que eu explique?"},
    "es_este_cobro": {"es": "¿Es este el cobro que no reconoce?", "pt": "É esta a cobrança que você não reconhece?"},
    "cual_cobro": {"es": "¿Cuál de estos cobros no reconoce?", "pt": "Qual destas cobranças você não reconhece?"},
    "cobro_no_encontrado": {"es": "No encontré esa transacción en los últimos {dias} días.", "pt": "Não encontrei essa transação nos últimos {dias} dias."},
    "ofrecer_bloqueo": {
        "es": "¿Quiere que la bloquee antes de transferir su reclamo? Para eso le pediré un código de verificación y su confirmación.",
        "pt": "Quer que eu bloqueie o cartão antes de transferir a sua contestação? Para isso vou pedir um código de verificação e a sua confirmação.",
    },
    "no_bloquee": {"es": "No bloqueé la tarjeta.", "pt": "Não bloqueei o cartão."},
    "reclamo_asesor": {
        "es": "No puedo determinar si este cobro es válido; los reclamos los revisa un asesor.",
        "pt": "Não consigo determinar se esta cobrança é válida; as contestações são analisadas por um atendente.",
    },
    "parte_no_respondida": {"es": "No respondí lo que pidió sobre {tema}; puede preguntármelo por separado.", "pt": "Não respondi o que pediu sobre {tema}; pode me perguntar separadamente."},
    "elegir_idioma": {  # POL-ESC-11: una vez, en los dos idiomas.
        "es": "¿Prefiere continuar en español o en portugués? / Prefere continuar em espanhol ou em português?",
        "pt": "¿Prefiere continuar en español o en portugués? / Prefere continuar em espanhol ou em português?",
    },
    "aclarar": {"es": "¿Quiere {a} o {b}?", "pt": "Você quer {a} ou {b}?"},
    "repregunta": {"es": "No entendí su respuesta. {pregunta}", "pt": "Não entendi a sua resposta. {pregunta}"},
}

# Descripción corta de cada intención para las preguntas aclaratorias (POL-ESC-06).
DESCRIPCION_INTENCION = {
    "balance_inquiry": {"es": "consultar un saldo", "pt": "consultar um saldo"},
    "card_list": {"es": "ver qué tarjetas tiene", "pt": "ver quais cartões você tem"},
    "card_status": {"es": "saber el estado de una tarjeta", "pt": "saber a situação de um cartão"},
    "transaction_list": {"es": "ver sus transacciones", "pt": "ver as suas transações"},
    "transaction_detail": {"es": "que le explique una transacción", "pt": "que eu explique uma transação"},
    "card_block": {"es": "bloquear una tarjeta", "pt": "bloquear um cartão"},
    "charge_dispute": {"es": "reclamar un cargo que no reconoce", "pt": "contestar uma cobrança que não reconhece"},
    "block_reason": {"es": "saber por qué una tarjeta está bloqueada", "pt": "saber por que um cartão está bloqueado"},
    "card_unblock": {"es": "desbloquear o reponer una tarjeta", "pt": "desbloquear ou repor um cartão"},
    "human_request": {"es": "hablar con un asesor", "pt": "falar com um atendente"},
    "conversation_end": {"es": "terminar la conversación", "pt": "encerrar a conversa"},
    "out_of_scope": {"es": "otra cosa", "pt": "outra coisa"},
}

TEMA_INTENCION = {
    "balance_inquiry": {"es": "el saldo", "pt": "o saldo"},
    "card_list": {"es": "sus tarjetas", "pt": "os seus cartões"},
    "card_status": {"es": "el estado de la tarjeta", "pt": "a situação do cartão"},
    "transaction_list": {"es": "sus transacciones", "pt": "as suas transações"},
    "transaction_detail": {"es": "esa transacción", "pt": "essa transação"},
}

NUMEROS = {
    "es": ["cero", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez"],
    "pt": ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez"],
}
MESES = {
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
    "pt": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"],
}
ESTADO_TARJETA = {  # Tarjeta (es, femenino) y cartão (pt, masculino).
    "Active": {"es": "activa", "pt": "ativo"},
    "Blocked": {"es": "bloqueada", "pt": "bloqueado"},
    "Suspended": {"es": "suspendida", "pt": "suspenso"},
    "Closed": {"es": "cerrada", "pt": "encerrado"},
}
ESTADO_CUENTA = {  # Cuenta / conta (femenino en los dos idiomas).
    "Active": {"es": "activa", "pt": "ativa"},
    "Blocked": {"es": "bloqueada", "pt": "bloqueada"},
    "Suspended": {"es": "suspendida", "pt": "suspensa"},
    "Closed": {"es": "cerrada", "pt": "encerrada"},
}


def texto(clave: str, idioma: str, **valores) -> str:
    fuente = PLANTILLAS.get(clave) or FRASES[clave]
    return fuente[idioma].format(**valores)


def tipo_tarjeta(product_type: str, idioma: str) -> str:
    """{tipo} de la política: "de crédito" / "de débito" (POL-ACT-11)."""
    return "de crédito" if "Crédito" in (product_type or "") else "de débito"


def estado_tarjeta(status: str, idioma: str) -> str:
    return ESTADO_TARJETA.get(status, {}).get(idioma, status)


def numero_palabra(n: int, idioma: str) -> str:
    return NUMEROS[idioma][n] if 0 <= n < len(NUMEROS[idioma]) else str(n)


def monto(valor, pais: Optional[str]) -> str:
    """Convención de números del país del cliente (política 3b)."""
    base = f"{Decimal(str(valor)):,.2f}"
    if pais in ("Colombia", "Argentina"):
        return base.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return base


def fecha_larga(valor, idioma: str) -> str:
    dia = valor.date() if isinstance(valor, datetime) else valor
    union = "de"
    return f"{dia.day} {union} {MESES[idioma][dia.month - 1]} {union} {dia.year}"


def fecha_hora(valor: datetime, idioma: str) -> str:
    """as_of: "18 de junio de 2026 a las 06:40" / "18 de junho de 2026 às 06:40"."""
    conector = "a las" if idioma == "es" else "às"
    return f"{fecha_larga(valor, idioma)} {conector} {valor:%H:%M}"


def lista(elementos: List[str], idioma: str) -> str:
    if len(elementos) <= 1:
        return "".join(elementos)
    conjuncion = "y" if idioma == "es" else "e"
    return ", ".join(elementos[:-1]) + f" {conjuncion} " + elementos[-1]


def oracion_transaccion(tx: dict, plantilla_txs: str, idioma: str, pais: Optional[str], ultimos4: str) -> str:
    """Una oración TXS completa (sujeto con los hechos + estado), sección 6 de la política."""
    sujeto, genero = SUJETO_TXS.get(tx["type"], {"es": ("La transacción", "f"), "pt": ("A transação", "f")})[idioma]
    cantidad = f"{monto(tx['amount'], pais)} {tx['currency']}"
    if idioma == "es":
        frase = f"{sujeto} del {fecha_larga(tx['date'], idioma)} por {cantidad}"
        frase += f" en {tx['merchant']}" if tx.get("merchant") else ""
        frase += f" con la tarjeta terminada en {ultimos4}"
    else:
        frase = f"{sujeto} de {fecha_larga(tx['date'], idioma)} no valor de {cantidad}"
        frase += f" em {tx['merchant']}" if tx.get("merchant") else ""
        frase += f" no cartão final {ultimos4}"
    return f"{frase} {PREDICADO_TXS[plantilla_txs][idioma][genero]}"


def linea_transaccion(tx: dict, idioma: str, pais: Optional[str]) -> str:
    """Una fila de una lista de transacciones (POL-ANS-03: fecha, tipo, monto, moneda, comercio, estado)."""
    estado = {"Approved": {"es": "aprobada", "pt": "aprovada"}, "Declined": {"es": "rechazada", "pt": "recusada"},
              "Pending": {"es": "pendiente", "pt": "pendente"}, "Reversed": {"es": "revertida", "pt": "estornada"}}
    tipo = {"Purchase": {"es": "compra", "pt": "compra"}, "Payment": {"es": "pago", "pt": "pagamento"},
            "Withdrawal": {"es": "retiro", "pt": "saque"}}
    partes = [fecha_larga(tx["date"], idioma), tipo.get(tx["type"], {}).get(idioma, tx["type"]),
              f"{monto(tx['amount'], pais)} {tx['currency']}"]
    if tx.get("merchant"):
        partes.append(tx["merchant"])
    partes.append(estado.get(tx["status"], {}).get(idioma, tx["status"]))
    return "- " + ", ".join(partes)
