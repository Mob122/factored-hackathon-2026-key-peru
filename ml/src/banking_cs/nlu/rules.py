"""Keyword and regex parser for the intent taxonomy in docs/intents.md (intents-1.0).

Two jobs:
- The deterministic baseline of docs/eval_plan.md 8.3 (`parse(text)["intent"]`).
- The slot extractor used at runtime by every model: learned models predict the
  intent, slots always come from `extract_slots`.

Standard library only, so the backend can import it without Kedro or numpy.
Written from docs/intents.md and docs/golden_conversations.md alone, before the
utterance dataset existed, so it is not tuned to the evaluation data.

Matching runs on a normalized copy of the text (lowercase, no accents, every
non-alphanumeric run turned into one space). Read intents are scored on a copy in
which out-of-scope phrases are blanked ("suban el cupo", "pagar la tarjeta"), so
those phrases cannot trigger `balance_inquiry`; the transfer and action intents
see the unmasked text. Precedence (docs/intents.md section 3, rule 2):
human_request > charge_dispute > card_block > card_unblock > block_reason > the
read intent mentioned first > conversation_end > out_of_scope.

Slot values (the canonical forms the utterance dataset is labeled with):
- product_kind: credit_card, debit_card, card, savings_account, current_account,
  other_product.
- last4: four digits, from a cue ("termina en", "terminación", "final") or a
  redacted card placeholder such as `<CARD_0044>`.
- date: today, yesterday, day_before_yesterday, few_days_ago, n_days_ago:N,
  this_week, last_week, last_weekend, this_month, last_month, last_n_days:N,
  month:MM, date:MM-DD, since:MM-DD, weekday:mon..sun.
- amount: "<number>" or "<number> <currency>", number without thousands
  separators and with "." as decimal point; currency USD, BRL, COP, ARS, MXN, or
  PESO when the customer says pesos without a country.
- merchant: a capitalized name after a preposition, as typed.
- tx_status: approved, declined, pending, reversed.
- balance_item: balance (default), credit_limit, available_credit,
  minimum_payment, due_date.
Only the slots an intent takes (docs/intents.md section 1) are returned.
"""

from __future__ import annotations

import re
import unicodedata

INTENTS_VERSION = "intents-1.0"

INTENTS = (
    "balance_inquiry",
    "card_list",
    "card_status",
    "transaction_list",
    "transaction_detail",
    "card_block",
    "charge_dispute",
    "block_reason",
    "card_unblock",
    "human_request",
    "conversation_end",
    "out_of_scope",
)
SLOTS = (
    "product_kind",
    "last4",
    "date",
    "amount",
    "merchant",
    "tx_status",
    "balance_item",
)
INTENT_SLOTS = {
    "balance_inquiry": ("product_kind", "last4", "balance_item"),
    "card_list": ("product_kind",),
    "card_status": ("product_kind", "last4"),
    "transaction_list": (
        "product_kind",
        "last4",
        "date",
        "amount",
        "merchant",
        "tx_status",
    ),
    "transaction_detail": ("last4", "date", "amount", "merchant", "tx_status"),
    "card_block": ("product_kind", "last4"),
    "charge_dispute": ("last4", "date", "amount", "merchant"),
    "block_reason": ("product_kind", "last4"),
    "card_unblock": ("product_kind", "last4"),
    "human_request": (),
    "conversation_end": (),
    "out_of_scope": (),
}
PRODUCT_KINDS = (
    "credit_card",
    "debit_card",
    "card",
    "savings_account",
    "current_account",
    "other_product",
)
TX_STATUSES = ("approved", "declined", "pending", "reversed")
BALANCE_ITEMS = (
    "balance",
    "credit_limit",
    "available_credit",
    "minimum_payment",
    "due_date",
)

PRECEDENCE = (
    "human_request",
    "charge_dispute",
    "card_block",
    "card_unblock",
    "block_reason",
)
READ_INTENTS = (
    "balance_inquiry",
    "card_list",
    "card_status",
    "transaction_list",
    "transaction_detail",
)
FALLBACK_SCORE = 0.3


def normalize(text: str) -> str:
    """Lowercase, strip accents, and collapse every non-alphanumeric run to a space."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern)


# Words between two anchors, at most n of them.
def _gap(n: int) -> str:
    return rf"(?:\s+\S+){{0,{n}}}\s+"


_CARD = r"(?:tarjeta|tarjetas|tarjetita|plastico|cartao|cartoes)"
_BLOCKED_STATE = (
    r"(?:bloquead\w*|bloquearon|bloquearam|bloqueou|bloqueo|bloqueio|"
    r"suspendid\w*|suspendieron|suspens\w*|inhabilit\w*|deshabilit\w*|"
    r"desactivad\w*|desativad\w*|desactivaron|cancelaron|congelad\w*)"
)
_WHY = (
    r"(?:por que|porque|por q|motivo|razon|causa|que paso|que sucedio|"
    r"que ocurrio|o que aconteceu|o que houve|o que foi que|cuando|quando)"
)

# (pattern, weight). Weights combine by noisy-or into the intent score.
PATTERNS: dict[str, list[tuple[re.Pattern, float]]] = {
    "human_request": [
        (
            _rx(
                r"\b(?:asesor|asesora|ejecutivo|ejecutiva|operador|operadora|"
                r"atendente|ser humano|humano|agente humano|persona real|"
                r"supervisor|supervisora|gerente)\b"
            ),
            0.9,
        ),
        (
            _rx(
                r"\b(?:hablar|hable|habla|comuni[cq]\w*|pas\w*|transfi\w* con|"
                r"atienda|atiendan|falar|fale|passa|passe|me passa|chamar|"
                r"contactar|conectar\w*)"
                + _gap(4)
                + r"(?:persona|personas|alguien|pessoa|alguem|agente|"
                r"funcionari\w*|gente de verdad)\b"
            ),
            0.85,
        ),
        (_rx(r"\b(?:atencion al cliente|servicio al cliente)\b"), 0.5),
    ],
    "charge_dispute": [
        (
            _rx(
                r"\b(?:no|nao) (?:la |lo |le |a |o )?(?:reconozco|reconoce\w*|"
                r"reconheco|reconhece\w*)\b"
            ),
            0.95,
        ),
        (_rx(r"\bdesconoc\w*\b"), 0.9),
        (
            _rx(
                r"\b(?:yo no|no lo|no la|nunca|nao|eu nao|no) (?:lo |la )?"
                r"(?:hice|hize|realice|compre|autorice|reconozco|fiz|realizei|"
                r"comprei|autorizei|recibi|recebi|pedi|use|usei)\b(?! nada\b)"
            ),
            0.85,
        ),
        (_rx(r"\b(?:no fui yo|nao fui eu|no fue mio|nao e meu|no es mio)\b"), 0.9),
        (
            _rx(
                r"\b(?:cobr\w*|descont\w*|debit\w*|carg\w*)"
                + _gap(3)
                + r"(?:dos veces|duas vezes|2 veces|2 vezes|doble|dobrado)\b"
            ),
            0.95,
        ),
        (
            _rx(
                r"\b(?:duplicad\w*|cobro doble|cargo doble|doble cobro|"
                r"cobranca duplicada|cobrado duas vezes|cobrou duas vezes)\b"
            ),
            0.9,
        ),
        (
            _rx(
                r"\b(?:cobraron|cobro|cobrado|cobrou|cobraram|cobran)"
                r"(?: \S+){0,2} (?:de mas|mas de lo|a mais|demas|de mais)\b"
            ),
            0.9,
        ),
        (
            _rx(
                r"\b(?:reclamar|reclamo|disputar|impugnar|objetar|contestar|"
                r"contestacao|cuestionar)"
                + _gap(3)
                + r"(?:cargo|cobro|consumo|compra|cobranca|debito|pago|"
                r"transac\w*|lancamento)\b"
            ),
            0.85,
        ),
        (
            _rx(
                r"\b(?:devuelvan|devolver|devolucion|reembols\w*|reintegr\w*|"
                r"devolvam|devolverem|quero (?:o )?estorno|pedir (?:o )?estorno|"
                r"solicitar (?:o )?estorno)\b"
            ),
            0.75,
        ),
        (_rx(r"\b(?:fraude|fraudulent\w*|clonad\w*|clonaron|clonaram)\b"), 0.8),
        (
            _rx(
                r"\b(?:cargo|cobro|consumo|compra|cobranca)"
                r" (?:no autorizad\w*|indebid\w*|desconocid\w*|que no hice|"
                r"que nao fiz|nao autorizad\w*)\b"
            ),
            0.9,
        ),
    ],
    "card_block": [
        (
            _rx(
                r"\bbloque(?:ar(?:la|lo|las|los|me|mela)?|a(?:la|lo|me|mela)?|"
                r"e(?:la|lo|n(?:la|lo|me|mela|las)?)?|ia|ie|iem|em)\b"
            ),
            0.9,
        ),
        (
            _rx(
                r"\b(?:quiero|necesito|solicito|pido|hagan|hacer|quero|preciso|"
                r"solicitar|fazer|pedir) (?:el |un |o |um )?(?:bloqueo|bloqueio)\b"
            ),
            0.85,
        ),
        (
            _rx(
                r"\b(?:perdi|perdio|perdimos|perdeu|perdemos|extravie|"
                r"extravio|extraviad\w*|extraviei|perdid[ao]s?)\b"
            ),
            0.85,
        ),
        (
            _rx(
                r"\b(?:no encuentro|no encontramos|nao (?:acho|encontro))"
                r"(?: \S+){0,3} (?:tarjeta|cartao|billetera|cartera|carteira)\b"
            ),
            0.8,
        ),
        (
            _rx(
                r"\b(?:robaron|robo|robada|robado|asaltaron|afanaron|choraron|"
                r"roubaram|roubad\w*|roubo|furtaram|furtad\w*|furto|hurto|"
                r"hurtad\w*|assaltad\w*|assaltaram)\b"
            ),
            0.85,
        ),
        (_rx(r"\bcongel(?:ar|en|a|e|ala|ela|enla)\b"), 0.7),
    ],
    "card_unblock": [
        (_rx(r"\bdesbloque\w*\b"), 0.95),
        (_rx(r"\bunblock\w*\b"), 0.9),
        (_rx(r"\b(?:reactiv\w*|reativ\w*|rehabilit\w*|reabilit\w*)\b"), 0.9),
        (
            _rx(
                r"\b(?:activar|habilitar|ativar|activen|activa|ative)"
                r"(?: \S+){0,3} (?:otra vez|de nuevo|nuevamente|novamente|de novo)\b"
            ),
            0.85,
        ),
        (_rx(r"\bvolver a (?:activar|habilitar|usar)\b"), 0.8),
        (
            _rx(
                r"\b(?:reposicion|reponer\w*|repongan|reponga|reemplaz\w*|"
                r"substitu\w*|troca do cartao|trocar o cartao|"
                r"segunda via d[eo] (?:meu |minha |mi |la )?(?:cartao|tarjeta))\b"
            ),
            0.85,
        ),
        (
            _rx(
                r"\b(?:tarjeta nueva|nueva tarjeta|otra tarjeta|plastico nuevo|"
                r"cartao novo|novo cartao|outro cartao)\b"
                r"(?=.*\b(?:dan\w*|romp\w*|rot[ao]|quebr\w*|estrag\w*|vencid\w*|"
                r"desgast\w*|chip|banda|no lee|nao le|no funciona|nao funciona|"
                r"doblad\w*|partid\w*)\b)"
            ),
            0.85,
        ),
        (
            _rx(
                r"\b(?:se (?:me )?(?:dano|rompio|quebro|partio|doblo)|"
                r"(?:quebrou|estragou)|esta (?:danad|rot)\w*)\b"
                r"(?=.*\b(?:nueva|nuevo|otra|novo|nova|outro|reponer|mand\w*|"
                r"envi\w*)\b)"
            ),
            0.8,
        ),
    ],
    "block_reason": [
        (_rx(rf"\b{_WHY}\b(?:\s+\S+)*?\s+{_BLOCKED_STATE}\b"), 0.9),
        (_rx(rf"\b{_BLOCKED_STATE}\b(?:\s+\S+)*?\s+{_WHY}\b"), 0.9),
        (
            _rx(
                r"\b(?:me|nos|le) (?:la |lo |las |los )?(?:bloquearon|suspendieron|"
                r"inhabilitaron|deshabilitaron|desactivaron|congelaron)\b"
            ),
            0.75,
        ),
        (_rx(r"\b(?:bloquearam|suspenderam|desativaram) (?:o |meu |o meu )"), 0.75),
    ],
    "balance_inquiry": [
        (_rx(r"\bsaldo\b"), 0.9),
        (
            _rx(
                r"\bcuant[oa](?: plata| dinero)?(?: \S+){0,3} (?:debo|tengo|me queda|"
                r"queda|le debo|adeudo|hay|puedo gastar|puedo usar|"
                r"tengo que pagar|disponible)\b"
            ),
            0.85,
        ),
        (
            _rx(
                r"\bquant[oa](?: \S+){0,3} (?:devo|tenho|resta|sobra|posso gastar|"
                r"posso usar|tem|disponivel|falta pagar|preciso pagar)\b"
            ),
            0.85,
        ),
        (_rx(r"\b(?:cupo|limite)\b"), 0.8),
        (_rx(r"\b(?:disponible|disponivel)\b"), 0.6),
        (_rx(r"\b(?:pago|pagamento) minimo\b"), 0.9),
        (_rx(r"\b(?:deuda|divida|adeudo|lo que debo|o que devo)\b"), 0.8),
        (
            _rx(
                r"\b(?:vencimiento|vencimento|fecha (?:limite )?de pago|"
                r"data de pagamento|data (?:limite )?de vencimento|"
                r"(?:cuando|quando) (?:tengo que|debo|hay que|tenho que|devo) pagar|"
                r"(?:cuando|quando) vence (?:el pago|la factura|a fatura|o pagamento|"
                r"mi pago|la cuota))\b"
            ),
            0.85,
        ),
        (
            _rx(
                r"\b(?:valor|total|monto) d[ae] (?:minha |mi |la )?(?:fatura|factura)\b|"
                r"\b(?:quanto|cuanto) (?:e|es|veio|vino|esta|ficou|viene) "
                r"(?:a |la |minha |mi )?(?:fatura|factura)\b"
            ),
            0.85,
        ),
    ],
    "card_list": [
        (
            _rx(
                r"\b(?:que|cuales|cuantas|quais|quantos) (?:son (?:mis |las )?)?"
                r"(?:tarjetas|cartoes)\b"
            ),
            0.9,
        ),
        (
            _rx(
                r"\b(?:mis|meus|os meus|todas mis|todos os meus) (?:tarjetas|cartoes)\b"
            ),
            0.7,
        ),
        (
            _rx(
                r"\b(?:lista|listado|listagem|relacion) (?:de |dos |das )?"
                r"(?:mis |meus |las |os )?(?:tarjetas|cartoes)\b"
            ),
            0.85,
        ),
        (
            _rx(
                r"\b(?:tarjetas|cartoes) (?:tengo|tenho|eu tenho|estan a mi nombre|"
                r"estao no meu nome|a mi nombre|no meu nome)\b"
            ),
            0.85,
        ),
        (_rx(r"\btengo (?:alguna |otras? )?tarjetas?\b"), 0.6),
    ],
    "card_status": [
        (
            _rx(
                r"\b(?:esta|estan|sigue|siguen|anda|se encuentra|aparece|figura|"
                r"quedo|ficou|ta|continua|segue|fica)\s+(?:\S+\s+)?"
                r"(?:activ\w*|habilitad\w*|bloquead\w*|suspendid\w*|inactiv\w*|"
                r"vencid\w*|cancelad\w*|cerrad\w*|desactivad\w*|deshabilitad\w*|"
                r"inhabilitad\w*|ativ\w*|suspens\w*|funcionando|vigente|"
                r"operativ\w*|liberad\w*|desbloquead\w*|encerrad\w*)\b"
            ),
            0.85,
        ),
        (
            _rx(
                r"\b(?:estado|status|situacion|situacao|condicion)"
                r" (?:de |do |da |del )?(?:mi |la |el |o |meu |minha |a )?"
                rf"{_CARD}\b"
            ),
            0.9,
        ),
        (
            _rx(
                r"\b(?:en que|em que|cual es el|qual e o|qual a) (?:estado|situacao|status)\b"
            ),
            0.85,
        ),
        (_rx(r"\b(?:activa|ativo|ativa|habilitada) o (?:bloquead\w*|no|nao)\b"), 0.85),
        (_rx(rf"\b{_CARD}(?: \S+){{0,4}} (?:estado|status|situacao)\b"), 0.7),
        (
            _rx(r"\b(?:puedo|posso) (?:usar|seguir usando|utilizar) (?:mi|la|o|meu)\b"),
            0.5,
        ),
    ],
    "transaction_list": [
        (
            _rx(
                r"\b(?:movimientos|movimentos|consumos|compras|cargos|cobros|"
                r"transacciones|transacoes|lancamentos|gastos|operaciones|"
                r"operacoes|pagos|pagamentos|debitos|cobrancas)\b"
            ),
            0.85,
        ),
        (
            _rx(
                r"\b(?:que|en que|o que|com o que|no que)(?: \S+)? (?:compre|gaste|pague|"
                r"he comprado|he gastado|he hecho|hice|comprei|gastei|paguei|"
                r"he pagado)\b"
            ),
            0.85,
        ),
        (
            _rx(
                r"\b(?:cuanto|quanto)(?: \S+)? (?:gaste|he gastado|llevo gastado|"
                r"gastei|gastamos|tengo gastado)\b"
            ),
            0.85,
        ),
        (_rx(r"\b(?:extracto|extrato|historial|historico|estado de cuenta)\b"), 0.7),
        (_rx(r"\b(?:antes de eso|mas atras|mais antig\w*|antes disso)\b"), 0.6),
    ],
    "transaction_detail": [
        (
            _rx(
                r"\b(?:rechaz\w*|recusad\w*|recusou|recusaram|declinad\w*|"
                r"declinaron|denegad\w*|negad[ao]|negaron|rebotad\w*|rebot[oó])\b"
            ),
            0.9,
        ),
        (
            _rx(
                r"\b(?:no|nao) (?:me )?(?:la |lo )?(?:paso|pasa|pasaron|passou|"
                r"passa|acepto|aceptaron|aceptan|tomo|tomaron|agarro|agarra|"
                r"aceitou|aceitaram|funciono|funciona|funcionou|salio|saiu|entro|entrou)\b"
            ),
            0.8,
        ),
        (_rx(r"\b(?:pendiente|pendientes|pendente|pendentes|retenid\w*)\b"), 0.8),
        (
            _rx(
                r"\b(?:revertid\w*|reversad\w*|reversion|reverso|estornad\w*|"
                r"anulad[ao])\b"
            ),
            0.85,
        ),
        (_rx(r"\b(?:codigo|cod|code)\s+\d{2,3}\b"), 0.9),
        (
            _rx(
                r"\b(?:que|o que)\s+(?:es|significa|seria|fue|e|foi|quer dizer)"
                r"(?: \S+){0,3} (?:cargo|cobro|consumo|compra|pago|movimiento|"
                r"transaccion|debito|codigo|monto|cobranca|pagamento|transacao|"
                r"lancamento|valor)\b"
            ),
            0.85,
        ),
        (
            _rx(
                r"\b(?:me explic\w*|explicame|expliqueme|explica\w*)"
                r"(?: \S+){0,4} (?:cargo|cobro|consumo|compra|pago|movimiento|"
                r"transaccion|cobranca|pagamento|transacao|por que|porque)\b"
            ),
            0.8,
        ),
        (
            _rx(
                r"\b(?:ese|este|esa|esta|esse|essa|un|una|um|uma|el|la|o|a) "
                r"(?:cargo|cobro|consumo|compra|pago|movimiento|transaccion|"
                r"cobranca|pagamento|transacao|lancamento|debito)\b"
            ),
            0.4,
        ),
        (
            _rx(
                r"\bque (?:paso|sucedio|ocurrio) con (?:el|la|mi|ese|esa|este|esta) "
                r"(?:pago|compra|cargo|cobro|consumo|transaccion)\b"
            ),
            0.85,
        ),
    ],
    "conversation_end": [
        (_rx(r"\b(?:gracias|obrigad[oa]|valeu|agradezco|agradecid[oa])\b"), 0.7),
        (
            _rx(
                r"\b(?:eso es todo|eso era todo|eso era|era todo|era eso|es todo|"
                r"nada mas|mais nada|so isso|era isso|e isso|era so isso|"
                r"ya quede|ya esta|asi esta bien|esta bien asi|todo bien|"
                r"ta bom|esta bom|tudo certo obrigad\w*|listo|perfecto|"
                r"buenisimo|de nada)\b"
            ),
            0.75,
        ),
        (
            _rx(
                r"\b(?:hasta luego|hasta pronto|chau|chao|adios|nos vemos|"
                r"tchau|ate logo|ate mais|bye|que tenga buen dia|buen dia)\b"
            ),
            0.75,
        ),
    ],
}

# Out-of-scope phrases blanked before read intents are scored. Their match also
# gives out_of_scope its score when no intent fires.
_CONJ = r"(?!(?:y|e|o|pero|mas|ademas|tambien|tambem)\b)"
OUT_OF_SCOPE_MASKS: list[tuple[re.Pattern, float]] = [
    (
        _rx(
            r"\b(?:subir|suban|suba|subirme|aumentar|aumenten|aumente|aumentem|"
            r"ampliar|amplien|amplie|incrementar|elevar|aumento|subida|ampliacion)"
            r"(?: \S+){0,4} (?:cupo|limite)\b"
        ),
        0.85,
    ),
    (_rx(r"\b(?:mas|mayor|maior|mais) (?:cupo|limite)\b"), 0.8),
    (
        _rx(
            rf"\b(?:pagar|pague|paguen|abonar|quitar|pagando)\b(?:\s+{_CONJ}\S+){{0,4}}"
        ),
        0.8,
    ),
    (
        _rx(
            rf"\b(?:hacer|realizar|fazer|efetuar) (?:el |un |o |um )?(?:pago|pagamento)"
            rf"\b(?:\s+{_CONJ}\S+){{0,4}}"
        ),
        0.8,
    ),
    (
        _rx(
            rf"\b(?:transferi\w*|transferencia\w*|transfira|transferir|pix|"
            rf"giro|enviar dinero|enviar plata|mandar plata|mandar dinero|"
            rf"mandar dinheiro|enviar dinheiro)\b(?:\s+{_CONJ}\S+){{0,4}}"
        ),
        0.8,
    ),
    (
        _rx(
            r"\b(?:prestamo\w*|emprestimo\w*|credito personal|credito pessoal|"
            r"credito hipotecario|hipoteca|financiamiento|financiamento|"
            r"credito de libre inversion)\b"
        ),
        0.85,
    ),
    (
        _rx(
            r"\b(?:tipo de cambio|cotizacion|cotacao|a cuanto esta el (?:dolar|euro)|"
            r"quanto esta o (?:dolar|euro)|precio del dolar|valor del dolar)\b"
        ),
        0.85,
    ),
    (
        _rx(
            r"\b(?:cambiar|actualizar|mudar|atualizar|alterar)(?: \S+){0,2} "
            r"(?:direccion|domicilio|endereco|telefono|celular|correo|email|e mail)\b"
        ),
        0.85,
    ),
    (
        _rx(
            r"\b(?:(?:cuando|que dia|que fecha|quando|em que data) (?:se )?"
            r"(?:vence|caduca|expira|vencen|venca)(?: \S+){0,2} " + _CARD + r"|"
            r"(?:fecha de )?(?:vencimiento|expiracion|caducidad)(?: de| del)? "
            r"(?:mi |la |el )?" + _CARD + r"|"
            r"validade (?:do |de |da )?(?:meu |minha )?" + _CARD + r")\b"
        ),
        0.85,
    ),
    (
        _rx(
            r"\b(?:cancelar|cancelen|cancele|dar de baja|darme de baja|cerrar|"
            r"anular|encerrar|cancelem)(?: \S+){0,3} "
            r"(?:tarjeta|tarjetas|cuenta|cartao|conta|plastico)\b"
        ),
        0.8,
    ),
    (
        _rx(
            r"\b(?:sacar|solicitar|pedir|tramitar|contratar|abrir|obtener|tener|"
            r"quiero|quero|ter|adquirir)(?: una| um| uma| otra| outra)?"
            r"(?: nueva| nova| novo)? (?:tarjeta|cuenta|cartao|conta|cdt)\b"
            r"(?:\s+(?:de credito|de debito|de ahorros?|corriente|nueva|nuevo|novo|"
            r"nova|adicional|extra|digital|para mi \S+))*"
        ),
        0.8,
    ),
    (_rx(r"\b(?:cdt|seguro de vida|inversion|investimento|seguro)\b"), 0.7),
    (
        _rx(
            r"\b(?:segunda via|copia|duplicado) (?:da |de la |del |de )?"
            r"(?:fatura|factura|extracto|estado de cuenta|resumen)\b"
        ),
        0.85,
    ),
    (_rx(r"\b(?:sucursal|agencia|cajero|caixa eletronico|horario)\b"), 0.6),
]
GREETING = _rx(
    r"^(?:hola|buenas|buenos dias|buenas tardes|buenas noches|oi|ola|"
    r"bom dia|boa tarde|boa noite|que tal|hey)(?: \S+){0,2}$"
)

# Slots ---------------------------------------------------------------------

_PRODUCT_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "credit_card",
        _rx(
            r"\b(?:(?:tarjeta|tarjetas|cartao|cartoes|plastico)(?: de)? credito|"
            r"(?:la|el|o|a) de credito)\b"
        ),
    ),
    (
        "debit_card",
        _rx(
            r"\b(?:(?:tarjeta|tarjetas|cartao|cartoes|plastico)(?: de)? debito|"
            r"(?:la|el|o|a) de debito)\b"
        ),
    ),
    (
        "savings_account",
        _rx(
            r"\b(?:cuenta (?:de )?ahorros?|caja de ahorros?|conta poupanca|"
            r"poupanca|mis ahorros|cuenta de ahorro)\b"
        ),
    ),
    (
        "current_account",
        _rx(
            r"\b(?:cuenta corriente|conta corrente|cuenta de cheques|cuenta monetaria)\b"
        ),
    ),
    (
        "other_product",
        _rx(
            r"\b(?:prestamo|emprestimo|credito personal|credito hipotecario|"
            r"hipoteca|cdt|inversion|investimento)\b"
        ),
    ),
]
_GENERIC_CARD = _rx(rf"\b{_CARD}\b")

_LAST4_PATTERNS = [
    _rx(
        r"\b(?:termina|terminada|terminado|terminan|terminacion|terminacao|"
        r"final|finalizad[ao]|acaba|acabada|acabado|ultimos (?:4|cuatro|quatro)"
        r"(?: digitos| numeros)?|digitos)"
        r"(?: en| em| con| com| de| in| no| nos| numero)?(?: los| el| o| os)?"
        r"(?: digitos| numeros)?(?: en| em)? (\d{4})\b"
    ),
    _rx(r"\bcard (\d{4})\b"),
    _rx(r"\b(?:tarjeta|cartao|plastico)(?: numero| n| no| nro)? (\d{4})\b"),
]

_STATUS_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "declined",
        _rx(
            r"\b(?:rechaz\w*|declin\w*|denegad\w*|recusad\w*|recusou|recusaram|"
            r"negad[ao]s?|negaron|rebot\w*|(?:no|nao) (?:me )?(?:la |lo )?"
            r"(?:paso|pasa|pasaron|passou|passa|acepto|aceptaron|aceitou|"
            r"aceitaram|tomo|tomaron|agarro|salio|saiu|entro|entrou))\b"
        ),
    ),
    (
        "pending",
        _rx(r"\b(?:pendiente\w*|pendente\w*|en proceso|retenid\w*|em processamento)\b"),
    ),
    (
        "reversed",
        _rx(
            r"\b(?:revertid\w*|reversad\w*|reversion|reverso|estornad\w*|anulad[ao]s?)\b"
        ),
    ),
    ("approved", _rx(r"\b(?:aprobad\w*|aprovad\w*|exitos\w*)\b")),
]

_NUMBER_WORDS = {
    "un": 1,
    "uno": 1,
    "um": 1,
    "dos": 2,
    "dois": 2,
    "tres": 3,
    "cuatro": 4,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "sete": 7,
    "ocho": 8,
    "oito": 8,
    "diez": 10,
    "dez": 10,
    "quince": 15,
    "quinze": 15,
    "veinte": 20,
    "vinte": 20,
    "treinta": 30,
    "trinta": 30,
    "sesenta": 60,
    "sessenta": 60,
    "noventa": 90,
}
_NUM_TOKEN = r"(\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")"
_MONTHS = {
    "enero": 1,
    "janeiro": 1,
    "febrero": 2,
    "fevereiro": 2,
    "marzo": 3,
    "marco": 3,
    "abril": 4,
    "mayo": 5,
    "maio": 5,
    "junio": 6,
    "junho": 6,
    "julio": 7,
    "julho": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "setembro": 9,
    "octubre": 10,
    "outubro": 10,
    "noviembre": 11,
    "novembro": 11,
    "diciembre": 12,
    "dezembro": 12,
}
_MONTH = r"(" + "|".join(_MONTHS) + r")"
_WEEKDAYS = {
    "lunes": "mon",
    "martes": "tue",
    "miercoles": "wed",
    "jueves": "thu",
    "viernes": "fri",
    "sabado": "sat",
    "domingo": "sun",
    "segunda feira": "mon",
    "terca": "tue",
    "terca feira": "tue",
    "quarta": "wed",
    "quarta feira": "wed",
    "quinta": "thu",
    "quinta feira": "thu",
    "sexta": "fri",
    "sexta feira": "fri",
}


def _num(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


def _date_since(m: re.Match) -> str:
    return f"since:{_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"


def _date_day(m: re.Match) -> str:
    return f"date:{_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"


_DATE_PATTERNS: list[tuple[re.Pattern, object]] = [
    (
        _rx(
            rf"\b(?:desde|a partir)(?: de)?(?: el| del| do| da| o)? (\d{{1,2}}) de {_MONTH}\b"
        ),
        _date_since,
    ),
    (_rx(rf"\b(\d{{1,2}}) de {_MONTH}\b"), _date_day),
    (
        _rx(rf"\b(?:desde|a partir de)(?: el| o)? (?:mes de |mes de )?{_MONTH}\b"),
        lambda m: f"since:{_MONTHS[m.group(1)]:02d}-01",
    ),
    (
        _rx(
            rf"\b(?:en|em|de|del|no mes de|en el mes de|durante)(?: el| o)? {_MONTH}\b"
        ),
        lambda m: f"month:{_MONTHS[m.group(1)]:02d}",
    ),
    (_rx(r"\b(?:anteayer|antier|antes de ayer|anteontem)\b"), "day_before_yesterday"),
    (_rx(r"\b(?:ayer|ontem)\b"), "yesterday"),
    (_rx(r"\b(?:hoy|hoje|esta manana|hoy en la manana)\b"), "today"),
    (
        _rx(rf"\b(?:los |las |os |as )?(?:ultimos|ultimas|ultimo) {_NUM_TOKEN} dias\b"),
        lambda m: f"last_n_days:{_num(m.group(1))}",
    ),
    (
        _rx(rf"\b(?:hace|faz|ha) {_NUM_TOKEN} dias\b"),
        lambda m: f"n_days_ago:{_num(m.group(1))}",
    ),
    (
        _rx(r"\b(?:hace|faz|ha) (?:unos|algunos|pocos|uns|alguns|poucos) dias\b"),
        "few_days_ago",
    ),
    (_rx(r"\b(?:la |a )?ultima semana\b"), "last_n_days:7"),
    (_rx(r"\b(?:el |o )?ultimo mes\b"), "last_n_days:30"),
    (
        _rx(
            r"\b(?:la semana pasada|semana pasada|la semana anterior|semana passada|"
            r"semana anterior)\b"
        ),
        "last_week",
    ),
    (_rx(r"\b(?:esta semana|essa semana|nesta semana|nessa semana)\b"), "this_week"),
    (_rx(r"\b(?:el )?fin de semana|(?:no )?fim de semana\b"), "last_weekend"),
    (
        _rx(
            r"\b(?:el mes pasado|mes pasado|el mes anterior|mes anterior|"
            r"mes passado)\b"
        ),
        "last_month",
    ),
    (
        _rx(
            r"\b(?:este mes|en lo que va del mes|neste mes|este mes|deste mes|desse mes)\b"
        ),
        "this_month",
    ),
    (
        _rx(
            r"\b(?:el|del|este|el pasado|na|no|nesta|nessa|desde el) "
            r"(lunes|martes|miercoles|jueves|viernes|sabado|domingo|"
            r"segunda feira|terca(?: feira)?|quarta(?: feira)?|quinta(?: feira)?|"
            r"sexta(?: feira)?)\b"
        ),
        lambda m: f"weekday:{_WEEKDAYS[m.group(1)]}",
    ),
]

_NUM_RAW = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_CURRENCY_WORD = (
    r"d[oó]lares|d[oó]lar|usd|verdes|pesos colombianos|pesos argentinos|"
    r"pesos mexicanos|pesos|peso|reais|real|lucas|luca|cop|ars|mxn|brl"
)
_AMOUNT_PATTERNS = [
    re.compile(
        rf"(?P<cur>US\$|U\$S|u\$s|R\$|\$|USD|COP|ARS|MXN|BRL)\s?(?P<num>{_NUM_RAW})"
        rf"(?P<mil>\s+mil\b)?(?:\s+(?P<cur2>{_CURRENCY_WORD})\b)?",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?<![\w.,])(?P<num>{_NUM_RAW})(?P<mil>\s+mil)?\s*(?P<cur>{_CURRENCY_WORD})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<mil>mil)\s+(?P<cur>{_CURRENCY_WORD})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:cargo|cobro|consumo|compra|pago|transacci[oó]n|cobran[cç]a|"
        r"pagamento|d[eé]bito|valor|monto|importe)\s+(?:de|por)\s+"
        rf"(?P<num>{_NUM_RAW})(?![\d.,]*\s*(?:de\s+\w+|d[ií]as|dias))(?P<mil>\s+mil\b)?",
        re.IGNORECASE,
    ),
]
_CURRENCY_CODES = {
    "us$": "USD",
    "u$s": "USD",
    "usd": "USD",
    "dolar": "USD",
    "dolares": "USD",
    "verdes": "USD",
    "r$": "BRL",
    "brl": "BRL",
    "real": "BRL",
    "reais": "BRL",
    "cop": "COP",
    "pesos colombianos": "COP",
    "ars": "ARS",
    "pesos argentinos": "ARS",
    "mxn": "MXN",
    "pesos mexicanos": "MXN",
    "pesos": "PESO",
    "peso": "PESO",
    "lucas": "PESO",
    "luca": "PESO",
}

_MERCHANT = re.compile(
    r"\b(?:en|de|del|no|na|em|con|com|por|al|a)\s+"
    r"((?:[A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñüçãõâêô&'.-]*)"
    r"(?:\s+(?:(?:de|del|la|las|los|el|y|do|da)\s+)?"
    r"[A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñüçãõâêô&'.-]*)*)"
)
_NOT_MERCHANT = {
    "hola",
    "gracias",
    "oi",
    "ola",
    "olá",
    "pix",
    "visa",
    "mastercard",
    "banco",
    "méxico",
    "mexico",
    "colombia",
    "argentina",
    "brasil",
    "card",
    "cdt",
    "usd",
    "cop",
    "ars",
    "mxn",
    "brl",
}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


THOUSANDS_GROUP = 3
MAX_CODE_LEN = 4


def _is_code(name: str) -> bool:
    """Short all-caps tokens (USD, COP, PIN) are not merchants; "TV" in "Cable TV" is kept."""
    return name.isupper() and len(name) <= MAX_CODE_LEN


def _parse_number(raw: str) -> float:
    last_sep = max(raw.rfind("."), raw.rfind(","))
    if last_sep == -1:
        return float(raw)
    decimals = raw[last_sep + 1 :]
    integer = re.sub(r"[.,]", "", raw[:last_sep])
    if len(decimals) == THOUSANDS_GROUP:  # the last separator groups thousands
        return float(integer + decimals)
    return float(f"{integer}.{decimals}")


def _format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _extract_amount(text: str) -> str | None:
    for pattern in _AMOUNT_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        groups = m.groupdict()
        num = groups.get("num")
        value = _parse_number(num) if num else 1.0
        if groups.get("mil"):
            value *= 1000
        currency = None
        for key in ("cur2", "cur"):
            token = groups.get(key)
            if token:
                code = _CURRENCY_CODES.get(_fold(token).strip())
                if code:
                    currency = code
                    break
        if currency == "PESO" and _fold(groups.get("cur") or "").startswith("luca"):
            value *= 1000
        return (
            f"{_format_number(value)} {currency}" if currency else _format_number(value)
        )
    return None


def _extract_merchant(text: str) -> str | None:
    for m in _MERCHANT.finditer(text):
        name = m.group(1).rstrip(".-'")
        if _fold(name) in _NOT_MERCHANT or _is_code(name):
            continue
        if re.fullmatch(r"[A-Z]+_\d+", name):
            continue
        return name
    return None


def _first(patterns, norm: str):
    best = None
    for label, pattern in patterns:
        m = pattern.search(norm)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), label, m)
    return best


def _product_kind(norm: str) -> str | None:
    hit = _first(_PRODUCT_PATTERNS, norm)
    if hit:
        return hit[1]
    return "card" if _GENERIC_CARD.search(norm) else None


def _last4(norm: str) -> str | None:
    for pattern in _LAST4_PATTERNS:
        m = pattern.search(norm)
        if m:
            return m.group(1)
    return None


def _date(norm: str) -> str | None:
    best = None
    for pattern, value in _DATE_PATTERNS:
        m = pattern.search(norm)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), value(m) if callable(value) else value)
    return best[1] if best else None


def _tx_status(norm: str) -> str | None:
    hit = _first(_STATUS_PATTERNS, norm)
    return hit[1] if hit else None


_DUE = PATTERNS["balance_inquiry"][7][0]
_AVAILABLE = _rx(
    r"\b(?:disponible|disponivel|me queda de (?:limite|cupo)|(?:limite|cupo) que me queda|"
    r"(?:puedo|posso|ainda posso) (?:gastar|usar|comprar)|para (?:gastar|usar|comprar)|"
    r"cupo libre|limite livre|cuanto me queda(?: \S+){0,2} (?:limite|cupo|tarjeta)|"
    r"quanto (?:me )?resta(?: \S+){0,2} (?:limite|cartao))\b"
)


def _balance_item(norm: str) -> str:
    if _DUE.search(norm):
        return "due_date"
    if re.search(r"\b(?:pago|pagamento|pagar el|pagar o) minimo\b", norm):
        return "minimum_payment"
    if _AVAILABLE.search(norm):
        return "available_credit"
    if re.search(r"\b(?:cupo|limite)\b", norm):
        return "credit_limit"
    return "balance"


def extract_slots(text: str, intent: str | None = None) -> dict[str, str]:
    """Slots found in `text`; restricted to the slots of `intent` when it is given."""
    norm = normalize(text)
    found = {
        "product_kind": _product_kind(norm),
        "last4": _last4(norm),
        "date": _date(norm),
        "amount": _extract_amount(text),
        "merchant": _extract_merchant(text),
        "tx_status": _tx_status(norm),
        "balance_item": _balance_item(norm) if intent == "balance_inquiry" else None,
    }
    allowed = INTENT_SLOTS[intent] if intent else SLOTS
    return {k: v for k, v in found.items() if v is not None and k in allowed}


def _mask(norm: str) -> tuple[str, float]:
    masked = norm
    strength = 0.0
    for pattern, weight in OUT_OF_SCOPE_MASKS:
        hits = list(pattern.finditer(masked))
        for m in reversed(hits):
            masked = (
                masked[: m.start()] + " " * (m.end() - m.start()) + masked[m.end() :]
            )
        if hits:
            strength = 1 - (1 - strength) * (1 - weight)
    return masked, strength


def _score(norm: str, intent: str) -> tuple[float, int | None]:
    score, first = 0.0, None
    for pattern, weight in PATTERNS[intent]:
        m = pattern.search(norm)
        if m:
            score = 1 - (1 - score) * (1 - weight)
            first = m.start() if first is None else min(first, m.start())
    return score, first


# Safety signal ---------------------------------------------------------------
#
# Used by the runtime override in predict.py (decisions log 2026-10-03): when it fires,
# card_block is added to the conformal set, so a singleton of another intent becomes a
# clarifying question instead of a missed block request. It is deliberately broad, since a
# false signal only costs one question, and it covers wordings the baseline patterns above
# do not ("travar", "congelada", "apagar la tarjeta", "sumiu"). It is not used by `classify`,
# so the rules baseline stays as committed at fb05246.
BLOCK_SIGNAL_EXTRA = [
    _rx(r"\btrav(?:a|ar|ara|aram|arem|e|em|ei|ou|o|amos|ando|ado|ada|ados|adas)\b"),
    _rx(r"\bcongel\w*"),
    _rx(r"\b(?:clonaron|clonaram|clonad\w*|clonar\w*)\b"),
    _rx(r"\b(?:perda|extravio|extraviad\w*|robo|roubo|furto|hurto)\b"),
    # v2: verb forms and nouns v1 missed (decisions log 2026-10-04).
    _rx(r"\bbloque(?:eme|enmela|an|amos|o tempora\w*|io tempora\w*)\b"),
    _rx(
        r"\b(?:report\w*|denunci\w*|registr\w*|comunic\w*)(?: \S+){0,4} "
        r"(?:robad\w*|roubad\w*|furtad\w*|perdid\w*|robo|roubo|furto|perda)\b"
    ),
]
# Only with a card mentioned in the same message.
BLOCK_SIGNAL_WITH_CARD = [
    _rx(r"\b(?:paus(?:ar|a|as|an|o|e|en|ala|ame|ela|enla|em)|en pausa|em pausa)\b"),
    _rx(
        r"\b(?:apag(?:ar|a|as|an|o|ue|uen|uela|uenla|uenme|ame|ala|alo)|apaguen\w*|"
        r"desligar|desliga|desliguem)\b"
    ),
    _rx(
        r"\b(?:se me (?:quedo|olvido|cayo)|me olvide|olvide|deje|esqueci)"
        r"(?: \S+){0,2} (?:tarjeta|cartao|plastico|billetera|cartera|carteira)\b"
    ),
    _rx(r"\b(?:inhabilit(?:ar|en|e|a)|desactiv(?:ar|en|e|a)|desativ(?:ar|em|e|a))\b"),
    _rx(r"\b(?:sumiu|sumiram|desapareci\w*|no aparece|nao aparece|nao acho)\b"),
]


_ROBOT_PT = re.compile(r"\brob[ôÔ]s?\b", re.IGNORECASE)


def block_signal(text: str) -> bool:
    """True when the message may ask for a block now or report a lost or stolen card."""
    # Portuguese "robô" (robot) folds to Spanish "robo" (theft) once accents are removed.
    norm = normalize(_ROBOT_PT.sub("robot", text))
    if any(p.search(norm) for p, _ in PATTERNS["card_block"]):
        return True
    if any(p.search(norm) for p in BLOCK_SIGNAL_EXTRA):
        return True
    return bool(_GENERIC_CARD.search(norm)) and any(
        p.search(norm) for p in BLOCK_SIGNAL_WITH_CARD
    )


# Theft wording only (not loss): POL-ACT-12 offers the dispute handoff after a block whose
# request mentioned a theft or a fraud.
THEFT_SIGNAL = _rx(
    r"\b(?:robaron|robo|robad\w*|asaltaron|asaltad\w*|afanaron|chorearon|choraron|"
    r"atracaron|raparon|bolsearon|roubaram|roubad\w*|roubo|furtaram|furtad\w*|furto|"
    r"hurto|hurtad\w*|assaltad\w*|assaltaram|levaram)\b"
)

# Dispute or fraud signal: symmetric to block_signal (decisions log D-11). When it fires,
# predict.py adds charge_dispute to the conformal set, so a lone card_block becomes a
# clarifying question instead of skipping the dispute handoff (POL-ESC-01). Not used by
# `classify`, so the rules baseline stays as committed at fb05246.
DISPUTE_SIGNAL_EXTRA = [
    _rx(
        r"\b(?:fraude\w*|fraudulent\w*|estafa\w*|estafaron|estafad\w*|golpe|golpes|"
        r"golpista\w*|chargeback|contracargo|clonaron|clonaram|clonad\w*)\b"
    ),
    _rx(r"\b(?:no|nao) (?:la |lo |le |a |o )?(?:reconozco|reconoce\w*|reconhe\w*)\b"),
    _rx(
        r"\b(?:cobro|cargo|compra|consumo|cobranca|debito|pago|pagamento|transac\w*)s?"
        r"(?: que)?(?: yo| eu)? (?:no|nao) (?:hice|hize|fiz|realice|realizei|autorice|"
        r"autorizei|reconozco|reconheco)\b"
    ),
    _rx(
        r"\b(?:contest\w*|disput\w*|impugn\w*|desconoc\w*|reclam\w*)(?: \S+){0,3} "
        r"(?:cargo|cobro|compra|consumo|cobranca|debito|pago|pagamento|transac\w*|"
        r"lancamento)s?\b"
    ),
    _rx(r"\b(?:no autorizad\w*|nao autorizad\w*|indebid\w*|no fui yo|nao fui eu)\b"),
]


def theft_signal(text: str) -> bool:
    """True when the message reports a theft (not a loss)."""
    return bool(THEFT_SIGNAL.search(normalize(_ROBOT_PT.sub("robot", text))))


def dispute_signal(text: str) -> bool:
    """True when the message may dispute a charge or report a fraud."""
    norm = normalize(text)
    if any(p.search(norm) for p, _ in PATTERNS["charge_dispute"]):
        return True
    return any(p.search(norm) for p in DISPUTE_SIGNAL_EXTRA)


def intent_scores(text: str) -> dict[str, float]:
    """Raw rule score per intent (before precedence), 0 when no pattern fires."""
    norm = normalize(text)
    masked, oos = _mask(norm)
    scores = {}
    for intent in INTENTS:
        if intent == "out_of_scope":
            scores[intent] = oos
        elif intent in PRECEDENCE:
            scores[intent] = _score(norm, intent)[0]
        else:
            scores[intent] = _score(masked, intent)[0]
    return scores


def classify(text: str) -> tuple[str, float]:
    """Intent and its rule score, applying the labeling-guide precedence."""
    norm = normalize(text)
    masked, oos = _mask(norm)
    for intent in PRECEDENCE:
        score, _ = _score(norm, intent)
        if score > 0:
            return intent, round(score, 4)
    reads = []
    for intent in READ_INTENTS:
        score, first = _score(masked, intent)
        if score > 0:
            reads.append((first, -score, intent))
    if reads:
        first, neg_score, intent = min(reads)
        return intent, round(-neg_score, 4)
    end_score, _ = _score(masked, "conversation_end")
    if end_score > 0:
        return "conversation_end", round(end_score, 4)
    if oos > 0:
        return "out_of_scope", round(oos, 4)
    if GREETING.match(norm):
        return "out_of_scope", 0.8
    return "out_of_scope", FALLBACK_SCORE


def parse(text: str) -> dict:
    """Rule-based intent, slots and score: {"intent", "slots", "score"}."""
    intent, score = classify(text)
    return {"intent": intent, "slots": extract_slots(text, intent), "score": score}
