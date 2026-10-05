# Contract: chat API for the frontend

| Field | Value |
|---|---|
| Contract version | `chat-api-0.1` |
| Date | 2026-10-04 |
| Implementation | `backend/` (FastAPI): `routers/`, `schemas/`, `services/agente/` |
| Machine-readable spec | `docs/contracts/openapi.json` (OpenAPI 3.1, exported from the app) |
| Captured examples | `docs/contracts/chat_api_examples.json` (every call shown here, plus full audit trails) |
| Related contracts | `state_machine.md` (`sm-0.4`), `audit_log.md` (`audit-0.2`), `docs/policy_cards.md` (`cards-synthetic-0.8`) |

This is the backend API that three screens use: the **customer chat**, the **human agent inbox** and the
**jurado test console**. It describes the API as implemented. Every example below was captured from a
real call to the running app (section 12), so the JSON is what the backend returns today.

Field names are in Spanish (`correo_electronico`, `codigo_step_up`), as in the backend. The values of
`state`, the transition IDs and the rule IDs are those of `state_machine.md` and `policy_cards.md`.

## 1. Conventions

- **Base URL:** `BACKEND_URL`, `http://localhost:8000` by default. JSON in UTF-8 in both directions.
- **Authentication:** `Authorization: Bearer <token>`. The token is a JWT that only names a server-side
  session (`sesiones_identidad`). A session ends after 15 minutes without calls or 60 minutes after sign-in,
  whichever comes first (POL-AUTH-03). Every authenticated call counts as activity.
- **Times:** ISO 8601, UTC. Session and token expiry times use the real clock. The dates the assistant
  says in its replies (transactions, balance `as_of`) use the bank's clock, which a server can pin with
  `RELOJ_SIMULADO` (the golden conversations use `2026-06-18T10:00:00`).
- **Replies are plain text:** `reply` holds one or more sentences joined by spaces. A transaction list
  uses `- ` before each item. Render it as text, never as HTML or Markdown.
- **Errors** come in three shapes (section 9): `{"detail": {"codigo", "mensaje"}}` for session, role and
  chat errors; `{"detail": "<text>"}` for a few older endpoints; and FastAPI's validation list for 422.
- **Slow turns:** with `LLM_MODE=openai`, one chat turn can wait for the LLM (30 s timeout, up to 3
  retries with backoff) before it falls back to the code's sentences. Use a client timeout of at least
  130 s on `POST /chat/mensaje`, and keep the input disabled while a turn is in flight.

## 2. Authentication and the cookie flow

The browser never calls the backend. SvelteKit server code calls it and keeps the token in an httpOnly
cookie, so client-side JavaScript never sees a token. This is how `frontend/` works today:

1. The login form posts to the SvelteKit route `POST /api/auth?tipoAuth=login`.
2. That route calls `POST {BACKEND_URL}/autenticacion/iniciar-sesion`. The backend answers with the token
   as a JSON string.
3. The route stores it in the cookie `token` (`httpOnly`, `secure`, `sameSite=strict`, `path=/`).
4. On every request, `src/hooks.server.ts` calls `GET /autenticacion/mi-perfil` with the cookie's token and
   puts the user (`rol`, `customer_id`) in `event.locals.usuario`. If that call fails, it deletes the cookie,
   and `/app*` redirects to `/login`.

For the new screens, add SvelteKit server routes (for example `src/routes/api/chat/+server.ts`) that read
the cookie and forward the call with the `Authorization` header. Read the backend URL from
`$lib/server/backend` (`BACKEND_URL`; see `frontend/.env.example`). The backend's CORS is open (`*`), but that
is for local tools such as the CLI; the browser should still go through the server routes.

**Roles.** `rol` comes from `mi-perfil` and decides the screen:

| `rol` | Screen | Endpoints |
|---|---|---|
| `cliente` with a `customer_id` | customer chat | `/chat/*`, `/autenticacion/*` |
| `agente` | case inbox | `/casos`, `/casos/{case_id}`, `/auditoria/*` |
| `jurado` | test console | `/identidad/*`, `/auditoria/*`, and the chat with a test session token |

**The jurado's test session.** `POST /identidad/sesion-prueba` returns a second token, a *customer*
session for the chosen customer (`metodo: idp_prueba`). Keep it in its own httpOnly cookie (for example
`token_prueba`) and never overwrite the jurado's `token`. The console then uses the jurado token for
`/identidad/*` and `/auditoria/*`, and the test token for `/chat/*`. Always show the `aviso` text that comes
with it: the test IdP is simulated and must be labeled as such (POL-AUTH-13).

**Lifetimes.** The frontend currently gives the cookie a 7-day `maxAge`, but the backend session lasts at
most 60 minutes. Treat any `401` as "sign in again": delete the cookie and go to the login page. In the chat,
keep the `conversation_id` so the customer can resume after signing in (section 4.6).

**Language.** A customer can choose `es` or `pt` at sign-in (`idioma` in the login body), when the chat
starts, or in any turn (POL-GEN-03). Without a choice, the first message decides it.

**Registration.** `POST /autenticacion/registrar` only works with `ENV=development`. It creates a `cliente`
with no `customer_id`, which cannot chat (`403 NOT_A_CUSTOMER_SESSION`). Demo users come from the seed
script (`backend/scripts/sembrar_usuarios.py`): one per golden persona, plus `agente@keyperu.example` and
`jurado@keyperu.example`, all with the password in `SEED_PASSWORD`.

<!-- example: auth-login -->
`auth-login` · Seeded customer signs in

```http
POST /autenticacion/iniciar-sesion

{
  "correo_electronico": "cli-sqjocedjjncz@clientes.keyperu.example",
  "password": "<SEED_PASSWORD>"
}

HTTP 200
"<token>"
```
<!-- /example -->

<!-- example: auth-profile -->
`auth-profile` · Profile of the signed-in user

```http
GET /autenticacion/mi-perfil
Authorization: Bearer <customer token>

HTTP 200
{
  "nombre": "Cliente de prueba, diálogo 11 (CLI-SQJOCEDJJNCZ)",
  "correo_electronico": "cli-sqjocedjjncz@clientes.keyperu.example",
  "es_activo": true,
  "id": 11,
  "rol": "cliente",
  "customer_id": "CLI-SQJOCEDJJNCZ"
}
```
<!-- /example -->

<!-- example: auth-session -->
`auth-session` · Session level and expiry

```http
GET /autenticacion/mi-sesion
Authorization: Bearer <customer token>

HTTP 200
{
  "sesion_id": "ses_a0JcZJZe2Dfq5qvDaQ8Rqe3bk1gCRJQJ",
  "rol": "cliente",
  "nivel": "L1",
  "metodo": "contrasena",
  "customer_id": "CLI-SQJOCEDJJNCZ",
  "idioma": null,
  "expira_inactividad_en": "2026-10-05T04:50:43.017994Z",
  "expira_absoluta_en": "2026-10-05T05:35:42.988737Z"
}
```
<!-- /example -->

<!-- example: logout -->
`logout` · Sign out

```http
POST /autenticacion/cerrar-sesion
Authorization: Bearer <customer token>

HTTP 204
```
<!-- /example -->

<!-- example: err-after-logout -->
`err-after-logout` · The token stops working after sign-out

```http
GET /autenticacion/mi-sesion
Authorization: Bearer <customer token>

HTTP 401
{
  "detail": {
    "codigo": "SESSION_EXPIRED",
    "mensaje": "La sesión expiró o se cerró. Inicie sesión de nuevo."
  }
}
```
<!-- /example -->

## 3. Endpoint reference

| Method and path | Who | Purpose | Success |
|---|---|---|---|
| `POST /autenticacion/iniciar-sesion` | anyone | Sign in. Body `correo_electronico`, `password`, optional `idioma` (`es`, `pt`). | `200`, the token as a JSON string |
| `GET /autenticacion/mi-perfil` | any session | The user: `id`, `nombre`, `correo_electronico`, `es_activo`, `rol`, `customer_id` | `200` |
| `GET /autenticacion/mi-sesion` | any session | `sesion_id`, `rol`, `nivel` (`L1`, `L2`), `metodo` (`contrasena`, `idp_prueba`), `customer_id`, `idioma`, `expira_inactividad_en`, `expira_absoluta_en` | `200` |
| `POST /autenticacion/cerrar-sesion` | any session | Sign out; the token stops working | `204` |
| `POST /autenticacion/registrar` | anyone, `ENV=development` only | Customer user with no bank data | `201` |
| `POST /autenticacion/step-up` | customer session | Direct step-up for a card (`codigo`, `card_id`, `accion: block_card`). **Not used by the chat UI**: the chat takes the code in `codigo_step_up` (section 4.3). | `201` |
| `POST /chat/sesiones` | customer session | Start a conversation (turn 0), or resume one after re-authentication with `conversation_id` | `201` |
| `POST /chat/mensaje` | customer session | One turn: `mensaje` **or** `codigo_step_up`, optional `idioma` | `200` |
| `GET /casos?limite=&desplazamiento=` | `agente` | Case summaries, newest first (`limite` 1 to 200, default 50) | `200` |
| `GET /casos/{case_id}` | `agente` | Full case file (section 10) | `200` |
| `GET /auditoria/conversacion/{conversation_id}?limite=` | `agente`, `jurado` | Audit trail of one conversation, all its sessions, with `cadena_valida` | `200` |
| `GET /auditoria/{session_id}?limite=` | `agente`, `jurado` | Audit trail of one session (`limite` 1 to 2000, default 500) | `200` |
| `GET /identidad/clientes` | `jurado` | Search customers: `q` (customer ID prefix, up to 16 characters), `pais`, `segmento`, `estado_cliente`, `pagina`, `tamano` (1 to 20) | `200` |
| `POST /identidad/sesion-prueba` | `jurado` | Customer session for a customer in gold: `customer_id`, optional `idioma` | `201` |
| `POST /identidad/otp-prueba` | `jurado` | One-time code for a test session's step-up: `sesion_id` (valid 5 minutes) | `201` |
| `GET /` | anyone | Health check | `200` |

## 4. Customer chat

### 4.1 Start and send

`POST /chat/sesiones` with `{}` (or `{"idioma": "pt"}`) authenticates the conversation and returns the
greeting with `turn: 0`. Keep `conversation_id`. Each later message is `POST /chat/mensaje` with that ID.
Exactly one of `mensaje` (1 to 2000 characters) or `codigo_step_up` (6 digits) goes in each turn.

Every chat response has the same shape:

| Field | Meaning |
|---|---|
| `conversation_id` | The conversation |
| `reply` | What the assistant says, in `language` |
| `state` | The state after this turn (table in 4.2) |
| `language` | `es` or `pt` |
| `pending_confirmation` | Only in `AWAIT_CONFIRMATION`: `card_last4`, `card_type` (gold value, `Tarjeta Crédito` or `Tarjeta Débito`, also in Portuguese conversations), `expires_at` |
| `case_id` | Set once the conversation was handed to an agent |
| `turn` | Turn number; 0 is the greeting |

<!-- example: d11-t0 -->
`d11-t0` · Open the chat (turn 0)

```http
POST /chat/sesiones
Authorization: Bearer <customer token>

{}

HTTP 201
{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "reply": "Hola, ¿en qué puedo ayudarle?",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 0
}
```
<!-- /example -->

<!-- example: d11-t1 -->
`d11-t1` · Balance, two eligible products: clarification

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "mensaje": "Hola, ¿cuál es mi saldo?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "reply": "Puedo consultar el saldo de su tarjeta de crédito terminada en 5070 o de su cuenta de ahorros terminada en 1317. ¿Cuál quiere consultar?",
  "state": "SELECT_CARD",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 1
}
```
<!-- /example -->

<!-- example: d11-t2 -->
`d11-t2` · Product chosen by type

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "mensaje": "La tarjeta de crédito."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "reply": "El saldo actual de su tarjeta de crédito terminada en 5070 es de 8.741.863,41 COP y su límite de crédito es de 84.596.594,05 COP, según los datos del 3 de octubre de 2026 a las 23:34.",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 2
}
```
<!-- /example -->

### 4.2 States the UI must handle

Only waiting and terminal states reach the client. The transient states of `state_machine.md` section 1
(`ANSWERING`, `ACTION_PRECHECK`, `EXECUTING`, `HANDOFF`) are never returned.

| `state` | What happened | What the UI does |
|---|---|---|
| `IDLE` | The request was answered, or nothing is pending | Normal input |
| `CLARIFY_INTENT` | The assistant asked which of two things the customer meant | Normal input |
| `SELECT_CARD` | The assistant listed products and asked which one | Normal input; optional quick replies with the last 4 digits from the reply |
| `SELECT_TRANSACTION` | The assistant asked which transaction, or to confirm the one it found | Normal input |
| `OFFER_BLOCK` | A dispute: the assistant offered to block the card first | Normal input; optional "Sí"/"No" quick replies |
| `STEP_UP` | A block needs a one-time code | Show the verification widget (4.3); keep the text input |
| `AWAIT_CONFIRMATION` | The assistant named the card and asked for a clear yes | Show `pending_confirmation` and a countdown to `expires_at`; "Sí"/"No" quick replies send a normal `mensaje` |
| `HANDED_OFF` | An agent will take over; `case_id` is set (it can be null if the case went to the fallback queue, POL-HND-05) | Show the case reference; later messages are appended to the case (T-38) |
| `ENDED` | The customer closed the conversation | Close the input and offer "new conversation" (`POST /chat/sesiones` with no `conversation_id`) |
| `SESSION_EXPIRED` | The session expired during the conversation (G-01); no data was disclosed | Ask the customer to sign in again, then resume (4.6) |

A customer whose status is `Suspended` or `Closed` gets `HANDED_OFF` with a `case_id` already at turn 0
(T-51, POL-AUTH-09).

### 4.3 Step-up and confirmation (blocking a card)

1. The customer asks to block a card. The reply asks for a code and the state is `STEP_UP`.
2. The code is typed in a **separate widget**, never in the chat text, and sent as `codigo_step_up`
   (POL-AUTH-08). A code typed in the chat text is redacted and ignored. In the demo there is no SMS: the
   jurado console issues the code with `POST /identidad/otp-prueba` for that session (section 8).
3. A valid code moves to `AWAIT_CONFIRMATION` with `pending_confirmation`. The confirmation expires 120 s
   after the prompt (POL-ACT-02).
4. A clear yes in a later message runs the block. The reply says the card is blocked only after the bank
   read it back as `Blocked`. Anything else (no, an ambiguous answer, another card, an expired
   confirmation) cancels it, and nothing runs (POL-ACT-03).

A wrong or expired code keeps `STEP_UP` and asks again. After 3 wrong codes the step-up locks for the
session and the conversation is handed off with priority `security` (T-30, POL-AUTH-06). Any text message
in `STEP_UP` cancels the pending block or starts a new request (T-31).

<!-- example: d2-t1 -->
`d2-t1` · Block request: step-up required

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "mensaje": "Oi, perdi meu cartão de crédito. Quero bloquear agora."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "reply": "O seu cartão de crédito final 8407 está ativo. Para bloquear, preciso confirmar sua identidade com um código de verificação; digite-o na janela de verificação, não aqui no chat.",
  "state": "STEP_UP",
  "language": "pt",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 1
}
```
<!-- /example -->

<!-- example: d2-otp -->
`d2-otp` · Jurado console issues a test one-time code

```http
POST /identidad/otp-prueba
Authorization: Bearer <jurado token>

{
  "sesion_id": "ses_9HereTHHD5EDuiIBCr83zmC7JeZomp9o"
}

HTTP 201
{
  "sesion_id": "ses_9HereTHHD5EDuiIBCr83zmC7JeZomp9o",
  "codigo": "960532",
  "expira_en": "2026-10-05T04:40:45.363831Z",
  "aviso": "IdP de prueba simulado: no es un proveedor de identidad real (POL-AUTH-13)."
}
```
<!-- /example -->

<!-- example: d2-t2 -->
`d2-t2` · Code sent from the verification widget: confirmation prompt

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "codigo_step_up": "960532"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "reply": "Identidade confirmada. Vou bloquear o seu cartão de crédito final 8407. Depois do bloqueio ele deixa de funcionar e eu não consigo desbloqueá-lo; só um atendente pode fazer isso. Confirma o bloqueio do cartão final 8407? Responda sim ou não.",
  "state": "AWAIT_CONFIRMATION",
  "language": "pt",
  "pending_confirmation": {
    "card_last4": "8407",
    "card_type": "Tarjeta Crédito",
    "expires_at": "2026-10-05T04:37:45.413791+00:00"
  },
  "case_id": null,
  "turn": 2
}
```
<!-- /example -->

<!-- example: d2-t3 -->
`d2-t3` · Explicit yes: block executed and verified

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "mensaje": "Sim, pode bloquear."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "reply": "Pronto: o seu cartão de crédito final 8407 está bloqueado. Para desbloquear ou pedir um cartão novo, é preciso falar com um atendente; posso transferir você, se quiser.",
  "state": "IDLE",
  "language": "pt",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 3
}
```
<!-- /example -->

<!-- example: err-stepup-t2 -->
`err-stepup-t2` · Wrong code: asked again (T-29)

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-acc8-7eb1-9b85-b6887f489025",
  "codigo_step_up": "000000"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-acc8-7eb1-9b85-b6887f489025",
  "reply": "El código no es válido o venció. Ingréselo de nuevo en la ventana de verificación.",
  "state": "STEP_UP",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 2
}
```
<!-- /example -->

### 4.4 Handoff

<!-- example: d5-t3 -->
`d5-t3` · Block declined: handoff with a case ID

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "mensaje": "No, por ahora solo quiero el reclamo."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "reply": "No bloqueé la tarjeta. No puedo determinar si este cobro es válido; los reclamos los revisa un asesor. Un asesor revisará su caso, referencia CASE-3630960D3B49.",
  "state": "HANDED_OFF",
  "language": "es",
  "pending_confirmation": null,
  "case_id": "CASE-3630960D3B49",
  "turn": 3
}
```
<!-- /example -->

<!-- example: d5-t4 -->
`d5-t4` · Message after the handoff is appended to the case (T-38)

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "mensaje": "¿En cuánto tiempo me contactan?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "reply": "Agregué su mensaje a su caso, referencia CASE-3630960D3B49. Un asesor lo revisará.",
  "state": "HANDED_OFF",
  "language": "es",
  "pending_confirmation": null,
  "case_id": "CASE-3630960D3B49",
  "turn": 4
}
```
<!-- /example -->

### 4.5 Ended conversations

<!-- example: ended-message -->
`ended-message` · Message to an ended conversation: fixed reply, nothing runs

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "mensaje": "Hola de nuevo"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "reply": "Esta conversación terminó. Si necesita algo más, inicie una nueva.",
  "state": "ENDED",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 5
}
```
<!-- /example -->

### 4.6 Session expiry and resume

There are two ways to learn that a session expired:

- **During a chat turn**, `POST /chat/mensaje` still answers `200`, with `state: SESSION_EXPIRED` and a reply
  that discloses no data (G-01). Pending actions are dropped (POL-AUTH-07).
- **Any other call** answers `401` with `codigo: SESSION_EXPIRED`.

To resume, sign in again (or, for a test session, have the jurado open a new one) and call
`POST /chat/sesiones` with the old `conversation_id`. If the customer had a request pending, the reply asks
whether to pick it up again (G-02), and the answer goes through T-50. Resuming an `ENDED` or `HANDED_OFF`
conversation answers `409 CONVERSATION_CLOSED`. Resuming while the old session is still valid answers
`409 SESSION_STILL_ACTIVE`.

<!-- example: expiry-t2 -->
`expiry-t2` · Idle timeout: no data, sign in again (G-01)

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-d0c2-7b4f-8f14-82bee0b3f475",
  "mensaje": "La tarjeta de crédito."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-d0c2-7b4f-8f14-82bee0b3f475",
  "reply": "Su sesión expiró. Por favor, inicie sesión de nuevo para continuar.",
  "state": "SESSION_EXPIRED",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 2
}
```
<!-- /example -->

<!-- example: expiry-session -->
`expiry-session` · Any other endpoint answers 401

```http
GET /autenticacion/mi-sesion
Authorization: Bearer <test session token>

HTTP 401
{
  "detail": {
    "codigo": "SESSION_EXPIRED",
    "mensaje": "La sesión expiró o se cerró. Inicie sesión de nuevo."
  }
}
```
<!-- /example -->

<!-- example: expiry-resume -->
`expiry-resume` · New session resumes the conversation (G-02)

```http
POST /chat/sesiones
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-d0c2-7b4f-8f14-82bee0b3f475"
}

HTTP 201
{
  "conversation_id": "conv_01a10a58-d0c2-7b4f-8f14-82bee0b3f475",
  "reply": "Sesión iniciada. ¿Quiere retomar lo que estaba haciendo?",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 3
}
```
<!-- /example -->

<!-- example: expiry-t3 -->
`expiry-t3` · Customer accepts the resume question (T-50)

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-d0c2-7b4f-8f14-82bee0b3f475",
  "mensaje": "Sí"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-d0c2-7b4f-8f14-82bee0b3f475",
  "reply": "Puedo consultar el saldo de su tarjeta de crédito terminada en 5070 o de su cuenta de ahorros terminada en 1317. ¿Cuál quiere consultar?",
  "state": "SELECT_CARD",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 4
}
```
<!-- /example -->

## 5. Agent inbox

1. `GET /casos` lists case summaries, newest first, with `limite` and `desplazamiento` for paging. Sort or
   badge by `priority`: `urgent` > `security` > `normal` (POL-HND-15).
2. `GET /casos/{case_id}` returns the full case file (section 10).
3. `GET /auditoria/conversacion/{conversation_ref}` returns everything that happened in the case's
   conversation, across every session in it, plus `cadena_valida`. Use `cadena_valida` to show whether the
   trail's hash chain verifies.

The case file holds the customer ID and internal card and transaction IDs, because agents work inside the
bank's perimeter (POL-PII-05, POL-PII-07). These screens are for `agente` only; never show this data in the
customer chat.

<!-- example: agent-cases -->
`agent-cases` · Case inbox, newest first

```http
GET /casos?limite=10
Authorization: Bearer <agent token>

HTTP 200
[
  {
    "case_id": "CASE-3630960D3B49",
    "created_at": "2026-10-05T04:35:44.858850Z",
    "priority": "normal",
    "reason_rule_ids": [
      "POL-ESC-01"
    ],
    "language": "es",
    "customer_id": "CLI-AYAHYQEG16BZ",
    "auth_level": "L1"
  }
]
```
<!-- /example -->

<!-- example: agent-audit types=message_received,classification,tool_call,policy_decision turn=1 -->
`agent-audit` · Audit trail of the case's conversation (conversation_ref)

```http
GET /auditoria/conversacion/conv_01a10a58-a7c8-7435-9064-02068925b196
Authorization: Bearer <agent token>

HTTP 200
{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "total": 18,
  "cadena_valida": true,
  "eventos": [
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10a58-a7f9-7aaa-b892-37f4a7c8f47f",
      "event_type": "message_received",
      "occurred_at": "2026-10-05T04:35:44.761Z",
      "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
      "session_id": "ses_YXc3CtfmBn-jrWXNpaawiqGhbdmBHuGJ",
      "turn_index": 1,
      "trace_id": "79e87fb188128f9176ded752420ebcf4",
      "span_id": "eb8f27ac47be707b",
      "actor": "customer",
      "customer_ref": "56ae90b15d399e40ab227ab95354192b",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.8",
      "state_machine_version": "sm-0.4",
      "rule_ids": [
        "POL-PII-01",
        "POL-PII-04"
      ],
      "session_origin": {
        "method": "password",
        "user_id": 5,
        "role": "cliente"
      },
      "text_redacted": "No reconozco un cobro de Empresa Telefónica en mi tarjeta de crédito terminada en 4950. Quiero reclamarlo.",
      "detected_language": "es",
      "typed_card_numbers": [],
      "third_party_refs": [],
      "secrets_redacted": 0,
      "pii_scan": {
        "blocked": false,
        "placeholders": {},
        "hits": {}
      },
      "prev_event_hash": "ba3bdbab1474684c78dd8377d826500aee8beb4fc23fdcb9b7c731a127542008",
      "event_hash": "793ace1bc79abc1de2f7fcb44361b68ac57814d5046b783cd36f4fed4fba10ff"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10a58-a7fd-7237-907b-750570193771",
      "event_type": "classification",
      "occurred_at": "2026-10-05T04:35:44.765Z",
      "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
      "session_id": "ses_YXc3CtfmBn-jrWXNpaawiqGhbdmBHuGJ",
      "turn_index": 1,
      "trace_id": "79e87fb188128f9176ded752420ebcf4",
      "span_id": "d3a8d0251f299040",
      "actor": "orchestrator",
      "customer_ref": "56ae90b15d399e40ab227ab95354192b",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.8",
      "state_machine_version": "sm-0.4",
      "rule_ids": [
        "POL-ESC-06"
      ],
      "session_origin": {
        "method": "password",
        "user_id": 5,
        "role": "cliente"
      },
      "classifier_artifact_sha256": "a03e2969febf16b860e87d4020f01b6ab0a3be99f4325191a60bb6b8d6969c82",
      "classifier": "tfidf_word1-2_char2-5_logistic_regression",
      "top_intent": "charge_dispute",
      "top_score": 0.9106,
      "conformal_set": [
        "charge_dispute"
      ],
      "conformal_alpha": 0.1,
      "conformal_threshold": 0.6683924683762994,
      "max_set": 2,
      "scores": {
        "charge_dispute": 0.9106,
        "out_of_scope": 0.0236,
        "card_block": 0.0184,
        "transaction_detail": 0.0095,
        "card_status": 0.0085
      },
      "safety_override": [],
      "signals": {
        "block_or_theft": false,
        "theft": false,
        "dispute_or_fraud": true
      },
      "context_override": [],
      "fallback_reason": null,
      "slots": {
        "last4": "4950",
        "merchant": "Empresa Telefónica"
      },
      "routing": "act",
      "pii_scan": {
        "blocked": false,
        "placeholders": {},
        "hits": {}
      },
      "prev_event_hash": "793ace1bc79abc1de2f7fcb44361b68ac57814d5046b783cd36f4fed4fba10ff",
      "event_hash": "22485ac78bd2dfd0149fcf85138a98b768abb392963648215bcda0800b952a89"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10a58-a808-74c5-8091-286b57c2a91e",
      "event_type": "tool_call",
      "occurred_at": "2026-10-05T04:35:44.776Z",
      "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
      "session_id": "ses_YXc3CtfmBn-jrWXNpaawiqGhbdmBHuGJ",
      "turn_index": 1,
      "trace_id": "79e87fb188128f9176ded752420ebcf4",
      "span_id": "7462a4580780012d",
      "actor": "tool_gateway",
      "customer_ref": "56ae90b15d399e40ab227ab95354192b",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.8",
      "state_machine_version": "sm-0.4",
      "rule_ids": [],
      "session_origin": {
        "method": "password",
        "user_id": 5,
        "role": "cliente"
      },
      "tool_call_id": "c2",
      "tool": "list_cards",
      "attempt": 1,
      "retry_of": null,
      "allowed_in_state": true,
      "args": {},
      "status": "ok",
      "error_code": null,
      "latency_ms": 15,
      "result": [
        {
          "card_ref": "e173abf001493ae0db265fbf07db32ce",
          "last4": "1883",
          "type": "Tarjeta Débito",
          "status": "Active"
        },
        {
          "card_ref": "0bc8fdbcecb88a4fde9bddc61c642639",
          "last4": "4950",
          "type": "Tarjeta Crédito",
          "status": "Active"
        }
      ],
      "result_digest": "bab1b258eb7469145892576c602931db6a70e67ca96acc092633002521082123",
      "data_as_of": null,
      "fixture": null,
      "pii_scan": {
        "blocked": false,
        "placeholders": {},
        "hits": {}
      },
      "prev_event_hash": "22485ac78bd2dfd0149fcf85138a98b768abb392963648215bcda0800b952a89",
      "event_hash": "f6d5ca183fec3bc851a2f063be213eae0731db1ab9c4db7cfe4836e32d388f16"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10a58-a82a-7d43-b437-d9e703038376",
      "event_type": "policy_decision",
      "occurred_at": "2026-10-05T04:35:44.810Z",
      "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
      "session_id": "ses_YXc3CtfmBn-jrWXNpaawiqGhbdmBHuGJ",
      "turn_index": 1,
      "trace_id": "79e87fb188128f9176ded752420ebcf4",
      "span_id": "699fefb06d129d38",
      "actor": "orchestrator",
      "customer_ref": "56ae90b15d399e40ab227ab95354192b",
      "auth_level": "L1",
      "state": "SELECT_TRANSACTION",
      "policy_version": "cards-synthetic-0.8",
      "state_machine_version": "sm-0.4",
      "rule_ids": [
        "POL-PII-01",
        "POL-GEN-03",
        "POL-ESC-06",
        "POL-ESC-01",
        "POL-ANS-09",
        "POL-ANS-12",
        "POL-ANS-04",
        "POL-TXS-01",
        "POL-DEC-92"
      ],
      "session_origin": {
        "method": "password",
        "user_id": 5,
        "role": "cliente"
      },
      "state_before": "IDLE",
      "state_after": "SELECT_TRANSACTION",
      "transition_id": "T-43",
      "transitions": [
        "T-09",
        "T-43"
      ],
      "decision": "clarify",
      "intent": "charge_dispute",
      "tool_call_ids": [
        "c2",
        "c3",
        "c4"
      ],
      "facts_used": [
        {
          "fact": "card",
          "value": {
            "last4": "4950",
            "type": "Tarjeta Crédito",
            "status": "Active"
          },
          "tool_call_id": "c2"
        },
        {
          "fact": "transaction",
          "value": {
            "transaction_ref": "5c60036d1becb474c5a22a40e8232c11",
            "date": "2026-06-01 04:20:42",
            "type": "Purchase",
            "amount": "392.25",
            "currency": "USD",
            "merchant": "Empresa Telefónica",
            "status": "Approved",
            "response_code": "00"
          },
          "tool_call_id": "c4"
        }
      ],
      "grounding_check": {
        "passed": true,
        "unsupported_facts": 0,
        "fallback_template": null
      },
      "reply": {
        "text_redacted": "La compra del 1 de junio de 2026 por 392.25 USD en Empresa Telefónica con la tarjeta terminada en 4950 fue aprobada. ¿Es este el cobro que no reconoce?",
        "language": "es",
        "templates": [
          "POL-TXS-01"
        ],
        "llm_call_ids": []
      },
      "counters": {
        "clarify_turns": 0,
        "card_misses": 0,
        "stepup_fails": 0,
        "tool_fail_rounds": 0,
        "llm_fails": 0,
        "injection_hits": 0,
        "unauthorized_hits": 0
      },
      "then_handoff": false,
      "dispute": true,
      "pii_scan": {
        "blocked": false,
        "placeholders": {},
        "hits": {}
      },
      "prev_event_hash": "ba9eb7ff1780c2703c2f7295cd4014a43c609d6fc44969d36ed40ac6c5dabee5",
      "event_hash": "0d4011e5e680dcbd8f5de37f7a104c8d89f054801a5615537da0f79ec36a7efc"
    }
  ],
  "_excerpt": "4 of 18 events; the full trail is in chat_api_examples.json"
}
```
<!-- /example -->

## 6. LLM wording and fallback

With `LLM_MODE=openai`, an LLM rewords the sentences the code drafted. Policy templates (balances,
transaction lines, handoff references) are never sent to it. If the LLM call fails, times out or its
output fails the grounding check, the reply is built from the code's sentences, so the response is still
a normal `200` (POL-REL-04). The API returns no error for this. To spot a fallback, look in the audit
trail: the `llm_call` event has `status` `error` or `timeout`, and that turn's `policy_decision` lists
`POL-REL-04`. After 2 failed LLM calls in a session (`LLM_FAIL_MAX`), the next turn hands off to an agent
(G-06, POL-ESC-07).

The example below was captured with the LLM pointed at a closed local port: the reply is word for word
the one of `d11-t1`.

<!-- example: err-llm-fallback -->
`err-llm-fallback` · LLM unreachable: same reply from the code's sentences (POL-REL-04)

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-ad43-746b-801b-98175db34659",
  "mensaje": "Hola, ¿cuál es mi saldo?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-ad43-746b-801b-98175db34659",
  "reply": "Puedo consultar el saldo de su tarjeta de crédito terminada en 5070 o de su cuenta de ahorros terminada en 1317. ¿Cuál quiere consultar?",
  "state": "SELECT_CARD",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 1
}
```
<!-- /example -->

<!-- example: err-llm-fallback-audit types=llm_call,policy_decision turn=1 -->
`err-llm-fallback-audit` · Audit of the fallback turn

```http
GET /auditoria/ses_qyq46u1HZlFFEdZXcvCrHd0gmEW04G1t
Authorization: Bearer <jurado token>

HTTP 200
{
  "session_id": "ses_qyq46u1HZlFFEdZXcvCrHd0gmEW04G1t",
  "total": 8,
  "eventos": [
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10a58-cf95-731f-b08c-8b048def016d",
      "event_type": "llm_call",
      "occurred_at": "2026-10-05T04:35:54.901Z",
      "conversation_id": "conv_01a10a58-ad43-746b-801b-98175db34659",
      "session_id": "ses_qyq46u1HZlFFEdZXcvCrHd0gmEW04G1t",
      "turn_index": 1,
      "trace_id": "a150659386a2b7c3c137b67be1e2accd",
      "span_id": "d3b5fb3fb0eb146b",
      "actor": "orchestrator",
      "customer_ref": "23ff291e775e70afec32d927897b27a7",
      "auth_level": "L1",
      "state": "SELECT_CARD",
      "policy_version": "cards-synthetic-0.8",
      "state_machine_version": "sm-0.4",
      "rule_ids": [
        "POL-PII-01",
        "POL-PII-02",
        "POL-REL-04"
      ],
      "session_origin": {
        "method": "test_idp",
        "issued_by_user_id": 13
      },
      "llm_call_id": "llm_8f92cc87abb1",
      "purpose": "reply_wording",
      "provider": "openai",
      "model_id": "gpt-4o-mini",
      "prompt_template": "reformular-v1",
      "temperature": 0,
      "max_tokens": 400,
      "input_tokens": 0,
      "cached_input_tokens": 0,
      "output_tokens": 0,
      "latency_ms": 8719,
      "status": "error",
      "retries": 3,
      "cost_usd": 0.0,
      "request_pii_scan": {
        "blocked": false,
        "hits": 0
      },
      "prompt_sha256": "1c14c46fbab570255f63d1da1f79a5c6a551ba29201952df8bc5c4cee7156422",
      "pii_scan": {
        "blocked": false,
        "placeholders": {},
        "hits": {}
      },
      "prev_event_hash": "b98a06205fd95f1773d280e39aa3d0d7e7c518530fe54390efe460edf80873fe",
      "event_hash": "24ccc01aa14ade13d4ea540cf1bfbbb0806c428fcbe2461626ec5b86a8113f63"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10a58-cf97-7a31-81db-32e88a07e30f",
      "event_type": "policy_decision",
      "occurred_at": "2026-10-05T04:35:54.903Z",
      "conversation_id": "conv_01a10a58-ad43-746b-801b-98175db34659",
      "session_id": "ses_qyq46u1HZlFFEdZXcvCrHd0gmEW04G1t",
      "turn_index": 1,
      "trace_id": "a150659386a2b7c3c137b67be1e2accd",
      "span_id": "f03be7f0145bbd4d",
      "actor": "orchestrator",
      "customer_ref": "23ff291e775e70afec32d927897b27a7",
      "auth_level": "L1",
      "state": "SELECT_CARD",
      "policy_version": "cards-synthetic-0.8",
      "state_machine_version": "sm-0.4",
      "rule_ids": [
        "POL-PII-01",
        "POL-ESC-06",
        "POL-ANS-07",
        "POL-ANS-17",
        "POL-REL-04"
      ],
      "session_origin": {
        "method": "test_idp",
        "issued_by_user_id": 13
      },
      "state_before": "IDLE",
      "state_after": "SELECT_CARD",
      "transition_id": "T-05",
      "transitions": [
        "T-05"
      ],
      "decision": "clarify",
      "intent": "balance_inquiry",
      "tool_call_ids": [
        "c2"
      ],
      "facts_used": [],
      "grounding_check": {
        "passed": true,
        "unsupported_facts": 0,
        "fallback_template": "POL-REL-04"
      },
      "reply": {
        "text_redacted": "Puedo consultar el saldo de su tarjeta de crédito terminada en 5070 o de su cuenta de ahorros terminada en 1317. ¿Cuál quiere consultar?",
        "language": "es",
        "templates": [],
        "llm_call_ids": [
          "llm_8f92cc87abb1"
        ]
      },
      "counters": {
        "clarify_turns": 0,
        "card_misses": 0,
        "stepup_fails": 0,
        "tool_fail_rounds": 0,
        "llm_fails": 1,
        "injection_hits": 0,
        "unauthorized_hits": 0
      },
      "then_handoff": false,
      "dispute": false,
      "pii_scan": {
        "blocked": false,
        "placeholders": {},
        "hits": {}
      },
      "prev_event_hash": "24ccc01aa14ade13d4ea540cf1bfbbb0806c428fcbe2461626ec5b86a8113f63",
      "event_hash": "8f9b70ce753cf94cc775940149bcebabef2505a251833580a30a04a172f34508"
    }
  ],
  "_excerpt": "2 of 8 events; the full trail is in chat_api_examples.json"
}
```
<!-- /example -->

## 7. Customers and products in the demo data

The golden personas (`docs/golden_conversations.md`) have seeded users, `cli-<id in lowercase>@clientes.keyperu.example`.
Any other customer in gold can be used through the jurado's test session. Gold has no names, so the
search returns only `customer_id`, `country` and `segment` (POL-AUTH-11).

## 8. Jurado test console

1. **Search:** `GET /identidad/clientes` with filters (`pais`, `segmento`, `estado_cliente`) or a
   `customer_id` prefix in `q`. Pages hold at most 20 results; `hay_mas` tells whether there is a next page.
   Each jurado can search 10 times per minute; the 11th search answers `429 RATE_LIMITED`.
2. **Start a test session:** `POST /identidad/sesion-prueba` returns a customer token for that customer.
   The audit log records that the jurado opened it (POL-AUTH-12). Show `aviso`.
3. **Chat as that customer** with the test token (section 4).
4. **Get a code** when the chat is in `STEP_UP`: `POST /identidad/otp-prueba` with the test session's
   `sesion_id`. The code lasts 5 minutes. The console shows it so the tester can type it in the chat's
   verification widget.
5. **Audit:** `GET /auditoria/{sesion_id}` (one session) or `GET /auditoria/conversacion/{conversation_id}`
   (the whole conversation).

<!-- example: idp-search -->
`idp-search` · Search customers (filters and paging)

```http
GET /identidad/clientes?pais=M%C3%A9xico&segmento=Basic&estado_cliente=Active&tamano=3
Authorization: Bearer <jurado token>

HTTP 200
{
  "pagina": 1,
  "tamano": 3,
  "hay_mas": true,
  "resultados": [
    {
      "customer_id": "CLI-0N6WSFJ54FF2",
      "country": "México",
      "segment": "Basic"
    },
    {
      "customer_id": "CLI-1IKG56EOI0A5",
      "country": "México",
      "segment": "Basic"
    },
    {
      "customer_id": "CLI-2IEJH2Q8IM11",
      "country": "México",
      "segment": "Basic"
    }
  ],
  "aviso": "IdP de prueba simulado: no es un proveedor de identidad real (POL-AUTH-13)."
}
```
<!-- /example -->

<!-- example: idp-search-prefix -->
`idp-search-prefix` · Search by customer_id prefix

```http
GET /identidad/clientes?q=CLI-1IKG
Authorization: Bearer <jurado token>

HTTP 200
{
  "pagina": 1,
  "tamano": 20,
  "hay_mas": false,
  "resultados": [
    {
      "customer_id": "CLI-1IKG56EOI0A5",
      "country": "México",
      "segment": "Basic"
    }
  ],
  "aviso": "IdP de prueba simulado: no es un proveedor de identidad real (POL-AUTH-13)."
}
```
<!-- /example -->

<!-- example: idp-session -->
`idp-session` · Jurado starts a test session for a customer

```http
POST /identidad/sesion-prueba
Authorization: Bearer <jurado token>

{
  "customer_id": "CLI-1IKG56EOI0A5",
  "idioma": "es"
}

HTTP 201
{
  "token": "<token>",
  "tipo_token": "bearer",
  "sesion_id": "ses_gOVdR7yxPrB_bUNrsu5hevZuzqy_impJ",
  "customer_id": "CLI-1IKG56EOI0A5",
  "customer_status": "Active",
  "nivel": "L1",
  "idioma": "es",
  "expira_inactividad_en": "2026-10-05T04:50:45.558314Z",
  "expira_absoluta_en": "2026-10-05T05:35:45.558314Z",
  "aviso": "IdP de prueba simulado: no es un proveedor de identidad real (POL-AUTH-13)."
}
```
<!-- /example -->

<!-- example: idp-audit types=message_received,classification,tool_call,policy_decision turn=3 -->
`idp-audit` · Audit trail of the test session

```http
GET /auditoria/ses_gOVdR7yxPrB_bUNrsu5hevZuzqy_impJ
Authorization: Bearer <jurado token>

HTTP 200
{
  "session_id": "ses_gOVdR7yxPrB_bUNrsu5hevZuzqy_impJ",
  "total": 18,
  "eventos": [
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10a58-ab97-7c53-9bf1-31a24f7c8e8e",
      "event_type": "message_received",
      "occurred_at": "2026-10-05T04:35:45.687Z",
      "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
      "session_id": "ses_gOVdR7yxPrB_bUNrsu5hevZuzqy_impJ",
      "turn_index": 3,
      "trace_id": "717889d90cce89ef3314a4ca9c2ce07f",
      "span_id": "c9e3d8368a0f5f05",
      "actor": "customer",
      "customer_ref": "c0be5e51ff0ff8a544c4279334736247",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.8",
      "state_machine_version": "sm-0.4",
      "rule_ids": [
        "POL-PII-01",
        "POL-PII-04"
      ],
      "session_origin": {
        "method": "test_idp",
        "issued_by_user_id": 13
      },
      "text_redacted": "¿Qué movimientos tuvo esa tarjeta en el último mes?",
      "detected_language": "es",
      "typed_card_numbers": [],
      "third_party_refs": [],
      "secrets_redacted": 0,
      "pii_scan": {
        "blocked": false,
        "placeholders": {},
        "hits": {}
      },
      "prev_event_hash": "ab105d70b0c23252786e710071f7f50b8dd81b3b4d31ce5f2eaf5b70d09c5118",
      "event_hash": "6d980aae1611aa40936757848de403a75277c9938f80a0280ad93ca68baebc80"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10a58-ab9c-77e6-a930-7a95ba3f3732",
      "event_type": "classification",
      "occurred_at": "2026-10-05T04:35:45.692Z",
      "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
      "session_id": "ses_gOVdR7yxPrB_bUNrsu5hevZuzqy_impJ",
      "turn_index": 3,
      "trace_id": "717889d90cce89ef3314a4ca9c2ce07f",
      "span_id": "0e56228b5ab3144a",
      "actor": "orchestrator",
      "customer_ref": "c0be5e51ff0ff8a544c4279334736247",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.8",
      "state_machine_version": "sm-0.4",
      "rule_ids": [
        "POL-ESC-06"
      ],
      "session_origin": {
        "method": "test_idp",
        "issued_by_user_id": 13
      },
      "classifier_artifact_sha256": "a03e2969febf16b860e87d4020f01b6ab0a3be99f4325191a60bb6b8d6969c82",
      "classifier": "tfidf_word1-2_char2-5_logistic_regression",
      "top_intent": "transaction_list",
      "top_score": 0.9359,
      "conformal_set": [
        "transaction_list"
      ],
      "conformal_alpha": 0.1,
      "conformal_threshold": 0.6683924683762994,
      "max_set": 2,
      "scores": {
        "transaction_list": 0.9359,
        "transaction_detail": 0.0203,
        "out_of_scope": 0.01,
        "balance_inquiry": 0.0098,
        "card_block": 0.0064
      },
      "safety_override": [],
      "signals": {
        "block_or_theft": false,
        "theft": false,
        "dispute_or_fraud": false
      },
      "context_override": [],
      "fallback_reason": null,
      "slots": {
        "product_kind": "card",
        "date": "last_n_days:30"
      },
      "routing": "act",
      "pii_scan": {
        "blocked": false,
        "placeholders": {},
        "hits": {}
      },
      "prev_event_hash": "6d980aae1611aa40936757848de403a75277c9938f80a0280ad93ca68baebc80",
      "event_hash": "152b462bbd272ad3e8d29abbd3b66e850fc834ba762ce1e86cbdccc0e76378a3"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10a58-aba6-742f-9541-cbe9afd23c4d",
      "event_type": "tool_call",
      "occurred_at": "2026-10-05T04:35:45.702Z",
      "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
      "session_id": "ses_gOVdR7yxPrB_bUNrsu5hevZuzqy_impJ",
      "turn_index": 3,
      "trace_id": "717889d90cce89ef3314a4ca9c2ce07f",
      "span_id": "56028e8ed416aec0",
      "actor": "tool_gateway",
      "customer_ref": "c0be5e51ff0ff8a544c4279334736247",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.8",
      "state_machine_version": "sm-0.4",
      "rule_ids": [],
      "session_origin": {
        "method": "test_idp",
        "issued_by_user_id": 13
      },
      "tool_call_id": "c4",
      "tool": "list_cards",
      "attempt": 1,
      "retry_of": null,
      "allowed_in_state": true,
      "args": {},
      "status": "ok",
      "error_code": null,
      "latency_ms": 0,
      "result": [
        {
          "card_ref": "072ce832fbf132c5193471f3a49f86d3",
          "last4": "0990",
          "type": "Tarjeta Crédito",
          "status": "Active"
        }
      ],
      "result_digest": "30f1f0051f3ef725f46a3c867fd38e2e2773f3d000ba481c0cc516b18db27224",
      "data_as_of": null,
      "fixture": null,
      "pii_scan": {
        "blocked": false,
        "placeholders": {},
        "hits": {}
      },
      "prev_event_hash": "152b462bbd272ad3e8d29abbd3b66e850fc834ba762ce1e86cbdccc0e76378a3",
      "event_hash": "c16b6a24def32ec791b9b089654eaa842151ad04409370dc9f4f6d9254ba4e9c"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10a58-abbb-7d92-81ce-b52b389e244f",
      "event_type": "policy_decision",
      "occurred_at": "2026-10-05T04:35:45.723Z",
      "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
      "session_id": "ses_gOVdR7yxPrB_bUNrsu5hevZuzqy_impJ",
      "turn_index": 3,
      "trace_id": "717889d90cce89ef3314a4ca9c2ce07f",
      "span_id": "50f8e58820a81ef5",
      "actor": "orchestrator",
      "customer_ref": "c0be5e51ff0ff8a544c4279334736247",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.8",
      "state_machine_version": "sm-0.4",
      "rule_ids": [
        "POL-PII-01",
        "POL-ESC-06",
        "POL-ANS-02",
        "POL-ANS-03",
        "POL-GEN-02",
        "POL-GEN-07"
      ],
      "session_origin": {
        "method": "test_idp",
        "issued_by_user_id": 13
      },
      "state_before": "IDLE",
      "state_after": "IDLE",
      "transition_id": "T-18",
      "transitions": [
        "T-06",
        "T-18"
      ],
      "decision": "answer",
      "intent": "transaction_list",
      "tool_call_ids": [
        "c4",
        "c5"
      ],
      "facts_used": [
        {
          "fact": "transactions",
          "value": [
            {
              "transaction_ref": "39bda70613f1788363779a5af42df097",
              "date": "2026-05-24 05:28:38",
              "amount": "214.92",
              "currency": "USD",
              "merchant": null,
              "status": "Approved"
            }
          ],
          "tool_call_id": "c5"
        }
      ],
      "grounding_check": {
        "passed": true,
        "unsupported_facts": 0,
        "fallback_template": null
      },
      "reply": {
        "text_redacted": "Estas son las transacciones de su tarjeta de crédito terminada en 0990 entre el 19 de mayo de 2026 y el 18 de junio de 2026: - 24 de mayo de 2026, retiro, 214.92 USD, aprobada",
        "language": "es",
        "templates": [],
        "llm_call_ids": []
      },
      "counters": {
        "clarify_turns": 0,
        "card_misses": 0,
        "stepup_fails": 0,
        "tool_fail_rounds": 0,
        "llm_fails": 0,
        "injection_hits": 0,
        "unauthorized_hits": 0
      },
      "then_handoff": false,
      "dispute": false,
      "pii_scan": {
        "blocked": false,
        "placeholders": {},
        "hits": {}
      },
      "prev_event_hash": "1a02f56e79823870b5270d3501b7f474b4c057fd80b9276fcae6bb06c175735f",
      "event_hash": "f6b38e714138b4cb365b4236aaf96ff27c11b95764720902a8b656fc69cb6f50"
    }
  ],
  "_excerpt": "4 of 18 events; the full trail is in chat_api_examples.json"
}
```
<!-- /example -->

## 9. Errors

| HTTP | `detail` | Where | Meaning | Frontend action |
|---|---|---|---|---|
| 401 | `"Email o contraseña incorrectos."` (text) | `iniciar-sesion` | Wrong email or password | Show the message |
| 401 | `TOKEN_INVALID` | any call with a token | Malformed, forged or unknown token | Delete the cookie, go to login |
| 401 | `SESSION_EXPIRED` | any call with a token except `/chat/mensaje` | Idle 15 minutes, 60 minutes since sign-in, or signed out | Delete the cookie, go to login; keep `conversation_id` to resume |
| 401 | `SESSION_INVALID` | any call with a token | The session record is not usable | As above |
| 200 | `state: SESSION_EXPIRED` | `/chat/mensaje` | The session expired mid-conversation (G-01) | Show the reply, sign in, resume (4.6) |
| 200 | `state: STEP_UP` | `/chat/mensaje` | Step-up required before a block | Show the verification widget (4.3) |
| 200 | (normal reply) | `/chat/mensaje` | LLM fallback (section 6) | Nothing; the reply is valid |
| 400 | `STEP_UP_FAILED`, `ACTION_INVALID` | `/autenticacion/step-up` | Wrong or expired code; unknown action | The chat UI does not call this endpoint |
| 400 | `"El correo ya está registrado."` (text) | `registrar` | Email taken | Show the message |
| 403 | `ROLE_FORBIDDEN` | `/casos`, `/auditoria/*`, `/identidad/*` | The role cannot use this endpoint | Hide the screen for this role |
| 403 | `NOT_A_CUSTOMER_SESSION` | `/chat/*` | The token is an agent's or a jurado's, or a registered user with no customer | Use a customer session |
| 403 | `CONVERSATION_FORBIDDEN` | `/chat/mensaje` | The conversation belongs to another customer | Start a new conversation |
| 403 | `CUSTOMER_STATUS_REVIEW` | `step-up`, `otp-prueba` | The customer is `Suspended` or `Closed` | Nothing to retry; the chat already handed off |
| 403 | `STEP_UP_LOCKED` | `step-up`, `otp-prueba` | 3 wrong codes in this session | No more codes for this session |
| 403 | `"El registro abierto está deshabilitado en este entorno."` (text) | `registrar` | `ENV` is not `development` | Hide registration |
| 404 | `CONVERSATION_NOT_FOUND` | `/chat/*` | Unknown conversation; or, when resuming, another customer's | Start a new conversation |
| 404 | `CUSTOMER_NOT_FOUND` | `sesion-prueba` | The customer is not in gold | Show the message |
| 404 | `SESSION_NOT_FOUND` | `otp-prueba` | Unknown or expired test session | Open a new test session |
| 404 | `"Caso no encontrado."` (text) | `/casos/{case_id}` | Unknown case | Show the message |
| 409 | `CONVERSATION_CLOSED` | `/chat/sesiones` with `conversation_id` | The conversation ended or was handed off | Start a new conversation |
| 409 | `SESSION_STILL_ACTIVE` | `/chat/sesiones` with `conversation_id` | The conversation's session is still valid | Keep using that session |
| 409 | `SESSION_NOT_ATTACHED` | `/chat/mensaje` | This token's session is not the conversation's current session | Call `POST /chat/sesiones` with `conversation_id` first |
| 422 | FastAPI validation list | any | The body or query does not match the schema | Fix the request |
| 429 | `RATE_LIMITED` | `/identidad/clientes` | More than 10 searches per minute | Wait a minute |
| 503 | `GOLD_UNAVAILABLE` | `/identidad/*` | The server has no gold data loaded | Report to the operator |

When a bank tool fails inside a chat turn, the API still answers `200`: the assistant says the service could
not complete the request, claims no result, and hands off (POL-ESC-07).

Captured error responses:

<!-- example: err-login -->
`err-login` · Wrong password

```http
POST /autenticacion/iniciar-sesion

{
  "correo_electronico": "agente@keyperu.example",
  "password": "contrasena-incorrecta"
}

HTTP 401
{
  "detail": "Email o contraseña incorrectos."
}
```
<!-- /example -->

<!-- example: err-token-invalid -->
`err-token-invalid` · Malformed or forged token

```http
GET /autenticacion/mi-sesion
Authorization: Bearer <invalid token>

HTTP 401
{
  "detail": {
    "codigo": "TOKEN_INVALID",
    "mensaje": "No se pudo validar las credenciales."
  }
}
```
<!-- /example -->

<!-- example: err-role-forbidden -->
`err-role-forbidden` · A customer calls the agent inbox

```http
GET /casos
Authorization: Bearer <customer token>

HTTP 403
{
  "detail": {
    "codigo": "ROLE_FORBIDDEN",
    "mensaje": "Su rol no permite esta operación."
  }
}
```
<!-- /example -->

<!-- example: err-not-customer -->
`err-not-customer` · A jurado token cannot chat

```http
POST /chat/sesiones
Authorization: Bearer <jurado token>

{}

HTTP 403
{
  "detail": {
    "codigo": "NOT_A_CUSTOMER_SESSION",
    "mensaje": "Esta sesión no corresponde a un cliente."
  }
}
```
<!-- /example -->

<!-- example: err-no-customer -->
`err-no-customer` · A registered user without a customer cannot chat

```http
POST /chat/sesiones
Authorization: Bearer <customer token>

{}

HTTP 403
{
  "detail": {
    "codigo": "NOT_A_CUSTOMER_SESSION",
    "mensaje": "Esta sesión no corresponde a un cliente."
  }
}
```
<!-- /example -->

<!-- example: err-conversation-forbidden -->
`err-conversation-forbidden` · Another customer's conversation

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "mensaje": "Hola"
}

HTTP 403
{
  "detail": {
    "codigo": "CONVERSATION_FORBIDDEN",
    "mensaje": "Esta conversación no es de la sesión."
  }
}
```
<!-- /example -->

<!-- example: err-conversation-closed -->
`err-conversation-closed` · An ended conversation cannot be resumed

```http
POST /chat/sesiones
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69"
}

HTTP 409
{
  "detail": {
    "codigo": "CONVERSATION_CLOSED",
    "mensaje": "La conversación ya terminó."
  }
}
```
<!-- /example -->

<!-- example: err-validation -->
`err-validation` · Both a message and a code in one turn

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "mensaje": "Hola",
  "codigo_step_up": "123456"
}

HTTP 422
{
  "detail": [
    {
      "type": "value_error",
      "loc": [
        "body"
      ],
      "msg": "Value error, Envíe mensaje o codigo_step_up, uno de los dos.",
      "input": {
        "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
        "mensaje": "Hola",
        "codigo_step_up": "123456"
      },
      "ctx": {
        "error": {}
      }
    }
  ]
}
```
<!-- /example -->

<!-- example: err-customer-not-found -->
`err-customer-not-found` · Test session for a customer not in gold

```http
POST /identidad/sesion-prueba
Authorization: Bearer <jurado token>

{
  "customer_id": "CLI-000000000000"
}

HTTP 404
{
  "detail": {
    "codigo": "CUSTOMER_NOT_FOUND",
    "mensaje": "Cliente no encontrado."
  }
}
```
<!-- /example -->

<!-- example: err-rate-limited -->
`err-rate-limited` · Eleventh search in a minute

```http
GET /identidad/clientes
Authorization: Bearer <jurado token>

HTTP 429
{
  "detail": {
    "codigo": "RATE_LIMITED",
    "mensaje": "Demasiadas búsquedas. Espere un minuto."
  }
}
```
<!-- /example -->

## 10. Case file

The case file is the input to `open_handoff` (policy section 8, POL-HND-10 to 15). Its content fields are
`request`, `verified_facts`, `actions_taken`, `evidence` and `unresolved_questions`.

| Field | Content |
|---|---|
| `case_id`, `created_at` | Reference given to the customer; creation time (UTC) |
| `priority` | `normal`, `security` or `urgent` |
| `reason_rule_ids` | Policy rules that required the handoff, for example `POL-ESC-01` for a dispute |
| `language`, `customer_id`, `auth_level` | The customer's language, the session customer, `L1` or `L2` |
| `policy_version`, `conversation_ref` | Policy in force; the conversation, for `GET /auditoria/conversacion/{conversation_ref}` |
| `appended_messages` | Customer messages after the handoff: `text_redacted`, `received_at` |
| `request` | `last_message_redacted`, `summary`, `summary_generated_by` (`template` or `model`), `top_intent`, `conformal_set` |
| `verified_facts` | `{fact, value, tool_call_id}`: only facts read by a tool in this session |
| `actions_taken` | Blocks run in the conversation, with whether they were executed and verified |
| `evidence` | `tool_calls` (`tool_call_id`, `tool`, `called_at`, `status`, `result_ref`), `cards`, `transactions`, `security_events` |
| `unresolved_questions` | What the agent must resolve, in English |

<!-- example: agent-case -->
`agent-case` · Full case file of dialogue 5

```http
GET /casos/CASE-3630960D3B49
Authorization: Bearer <agent token>

HTTP 200
{
  "case_id": "CASE-3630960D3B49",
  "created_at": "2026-10-05T04:35:44.858850Z",
  "priority": "normal",
  "reason_rule_ids": [
    "POL-ESC-01"
  ],
  "language": "es",
  "customer_id": "CLI-AYAHYQEG16BZ",
  "auth_level": "L1",
  "policy_version": "cards-synthetic-0.8",
  "conversation_ref": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "appended_messages": [
    {
      "text_redacted": "¿En cuánto tiempo me contactan?",
      "received_at": "2026-10-05T04:35:44.897860+00:00"
    }
  ],
  "request": {
    "last_message_redacted": "No reconozco un cobro de Empresa Telefónica en mi tarjeta de crédito terminada en 4950. Quiero reclamarlo.",
    "summary": "Transfer by POL-ESC-01; customer request classified as charge_dispute.",
    "summary_generated_by": "template",
    "top_intent": "charge_dispute",
    "conformal_set": [
      "charge_dispute"
    ]
  },
  "verified_facts": [
    {
      "fact": "card",
      "value": {
        "last4": "4950",
        "type": "Tarjeta Crédito",
        "status": "Active"
      },
      "tool_call_id": "c2"
    },
    {
      "fact": "disputed_transaction",
      "value": {
        "transaction_id": "TRX-KFN7RMGYX8DR5AYBQ4QL",
        "date": "2026-06-01 04:20:42",
        "type": "Purchase",
        "amount": "392.25",
        "currency": "USD",
        "merchant": "Empresa Telefónica",
        "status": "Approved",
        "response_code": "00"
      },
      "tool_call_id": "c4"
    }
  ],
  "actions_taken": [],
  "evidence": {
    "tool_calls": [
      {
        "tool_call_id": "c1",
        "tool": "authenticate",
        "called_at": "04:35:44",
        "status": "ok",
        "result_ref": "audit://conv_01a10a58-a7c8-7435-9064-02068925b196/c1"
      },
      {
        "tool_call_id": "c2",
        "tool": "list_cards",
        "called_at": "04:35:44",
        "status": "ok",
        "result_ref": "audit://conv_01a10a58-a7c8-7435-9064-02068925b196/c2"
      },
      {
        "tool_call_id": "c3",
        "tool": "list_transactions",
        "called_at": "04:35:44",
        "status": "ok",
        "result_ref": "audit://conv_01a10a58-a7c8-7435-9064-02068925b196/c3"
      },
      {
        "tool_call_id": "c4",
        "tool": "describe_transaction",
        "called_at": "04:35:44",
        "status": "ok",
        "result_ref": "audit://conv_01a10a58-a7c8-7435-9064-02068925b196/c4"
      }
    ],
    "cards": [
      {
        "card_id": "PRD-TGMAN4NBB814",
        "last4": "4950"
      }
    ],
    "transactions": [
      "TRX-KFN7RMGYX8DR5AYBQ4QL"
    ],
    "security_events": []
  },
  "unresolved_questions": [
    "Customer does not recognize transaction TRX-KFN7RMGYX8DR5AYBQ4QL (392.25 USD, Empresa Telefónica, 2026-06-01) and confirmed it at turn 2; dispute review needed.",
    "The assistant cannot judge whether a charge is valid (POL-ANS-12).",
    "A block of card 4950 was offered (POL-ESC-01) and declined by the customer at turn 3; the card is still Active."
  ]
}
```
<!-- /example -->

## 11. Audit trail

Every event has the envelope of `audit_log.md` section 3: `schema_version`, `event_id` (UUIDv7),
`event_type`, `occurred_at`, `conversation_id`, `session_id`, `turn_index`, `trace_id`, `span_id`, `actor`,
`customer_ref`, `auth_level`, `state`, `policy_version`, `state_machine_version`, `rule_ids`,
`session_origin`, `pii_scan`, `prev_event_hash` and `event_hash`. The fields of each `event_type` are in
`audit_log.md` section 4. The types are `session`, `message_received`, `classification`, `tool_call`,
`policy_decision` (one per turn), `llm_call`, `confirmation`, `action_result`, `verification`, `handoff`
and `security`.

For display:

- Group by `turn_index`.
- Each turn's `policy_decision` has `transitions`, `decision`, `rule_ids`, `facts_used` and the redacted
  reply. It is the best one-line summary of a turn.
- Customers and IDs appear as keyed pseudonyms (`customer_ref`, `card_ref`, `transaction_ref`), and texts
  are redacted (AL-P3). The audit log never shows a raw ID.

Explanations shown to agents or reviewers must be rebuilt from these events, never from a model's
reasoning (POL-AUD-02).

## 12. How the examples were captured, and the OpenAPI file

`backend/scripts/capturar_contrato_api.py` captures the examples:

- **What runs:** the whole app in-process with FastAPI's `TestClient`: routes, validation, sessions, the
  orchestrator, the real intent classifier and the bank tools. Every response is the app's real answer.
- **Data and clock:** the demo gold (`ml/data/demo_gold`), the golden clock (`RELOJ_SIMULADO=2026-06-18T10:00:00`)
  and `LLM_MODE=mock`. As a result, balance `as_of` shows the gold snapshot's load time, which is later
  than the bank's clock.
- **Isolation:** the database and secrets are temporary, and the script never reads `backend/.env`.
- **Forced conditions:** only two examples force a condition. The expired session moves the identity clock
  16 minutes forward, and the LLM fallback points the OpenAI client to a closed local port.
- **Redaction:** tokens and the seed password are replaced by placeholders such as `<customer token>`.
  IDs, codes and timestamps come from that run.

The script fails if any call returns a different HTTP status or chat state than expected. Run it again
after any API change; it rewrites the example blocks of this file, `chat_api_examples.json` and
`openapi.json`:

```sh
cd backend
python -m scripts.capturar_contrato_api            # --gold <folder> for another gold
```

`openapi.json` is `app.openapi()`. It lists every route, body and response model. Use it to generate types
for the frontend, for example with `openapi-typescript`.

## Appendix A. Captured conversations

Golden dialogues 11, 1 and 5 (es), 12 and 2 (pt), and one test-IdP session for a customer who is not a
golden persona, chosen from the demo gold.

### Dialogue 11 (es): balance of a credit card

<!-- examples: d11- -->
`d11-t0` · Open the chat (turn 0)

```http
POST /chat/sesiones
Authorization: Bearer <customer token>

{}

HTTP 201
{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "reply": "Hola, ¿en qué puedo ayudarle?",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 0
}
```

`d11-t1` · Balance, two eligible products: clarification

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "mensaje": "Hola, ¿cuál es mi saldo?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "reply": "Puedo consultar el saldo de su tarjeta de crédito terminada en 5070 o de su cuenta de ahorros terminada en 1317. ¿Cuál quiere consultar?",
  "state": "SELECT_CARD",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 1
}
```

`d11-t2` · Product chosen by type

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "mensaje": "La tarjeta de crédito."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "reply": "El saldo actual de su tarjeta de crédito terminada en 5070 es de 8.741.863,41 COP y su límite de crédito es de 84.596.594,05 COP, según los datos del 3 de octubre de 2026 a las 23:34.",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 2
}
```

`d11-t3` · Available credit is never computed (POL-BAL-05)

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "mensaje": "¿Y cuánto tengo disponible para usar?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "reply": "No puedo calcular el crédito disponible; solo puedo indicarle el saldo y el límite registrados. Si lo necesita, puedo transferirle con un asesor.",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 3
}
```

`d11-t4` · Balance read again, never reused (POL-GEN-07)

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "mensaje": "Ok. ¿Y el saldo de la tarjeta sigue igual que hace un rato?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "reply": "El saldo actual de su tarjeta de crédito terminada en 5070 es de 8.741.863,41 COP y su límite de crédito es de 84.596.594,05 COP, según los datos del 3 de octubre de 2026 a las 23:34.",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 4
}
```

`d11-t5` · Closing

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "mensaje": "Gracias, eso es todo."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a10c-7e03-8427-d72c471ad2ad",
  "reply": "Con gusto. Hasta luego.",
  "state": "ENDED",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 5
}
```
<!-- /example -->

### Dialogue 1 (es): explain a declined charge

<!-- examples: d1- -->
`d1-t0` · Open the chat (turn 0)

```http
POST /chat/sesiones
Authorization: Bearer <customer token>

{}

HTTP 201
{
  "conversation_id": "conv_01a10a58-a6ee-79af-9a3a-a35b7836930e",
  "reply": "Hola, ¿en qué puedo ayudarle?",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 0
}
```

`d1-t1` · Declined charge explained with its response code

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a6ee-79af-9a3a-a35b7836930e",
  "mensaje": "Hola, hace unos días me rechazaron un pago en Uber con mi tarjeta terminada en 6873. ¿Qué pasó?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a6ee-79af-9a3a-a35b7836930e",
  "reply": "La compra del 6 de junio de 2026 por 127.37 USD en Uber con la tarjeta terminada en 6873 fue rechazada. Tiene registrado el código de respuesta 54, que en las redes de pago significa: tarjeta vencida. Este código es lo que muestra el registro; no me permite confirmar la causa. Si necesita saber por qué ocurrió, puedo transferirle con un asesor.",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 1
}
```

`d1-t2` · Card status; no expiration date is confirmed (POL-ANS-13)

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a6ee-79af-9a3a-a35b7836930e",
  "mensaje": "¿Entonces mi tarjeta está vencida?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a6ee-79af-9a3a-a35b7836930e",
  "reply": "Su tarjeta de crédito terminada en 6873 está activa. No puedo confirmar fechas de vencimiento, así que no puedo decirle si el código 54 corresponde al estado real de su tarjeta. Si lo necesita, puedo transferirle con un asesor.",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 2
}
```

`d1-t3` · Closing

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a6ee-79af-9a3a-a35b7836930e",
  "mensaje": "No, así está bien. Gracias."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a6ee-79af-9a3a-a35b7836930e",
  "reply": "Con gusto. Hasta luego.",
  "state": "ENDED",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 3
}
```
<!-- /example -->

### Dialogue 5 (es): dispute a charge, handoff

<!-- examples: d5- -->
`d5-t0` · Open the chat (turn 0)

```http
POST /chat/sesiones
Authorization: Bearer <customer token>

{}

HTTP 201
{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "reply": "Hola, ¿en qué puedo ayudarle?",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 0
}
```

`d5-t1` · Dispute: the transaction is found and must be confirmed

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "mensaje": "No reconozco un cobro de Empresa Telefónica en mi tarjeta de crédito terminada en 4950. Quiero reclamarlo."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "reply": "La compra del 1 de junio de 2026 por 392.25 USD en Empresa Telefónica con la tarjeta terminada en 4950 fue aprobada. ¿Es este el cobro que no reconoce?",
  "state": "SELECT_TRANSACTION",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 1
}
```

`d5-t2` · Confirmed: a block is offered

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "mensaje": "Sí, ese."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "reply": "Su tarjeta de crédito terminada en 4950 está activa. ¿Quiere que la bloquee antes de transferir su reclamo? Para eso le pediré un código de verificación y su confirmación.",
  "state": "OFFER_BLOCK",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 2
}
```

`d5-t3` · Block declined: handoff with a case ID

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "mensaje": "No, por ahora solo quiero el reclamo."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "reply": "No bloqueé la tarjeta. No puedo determinar si este cobro es válido; los reclamos los revisa un asesor. Un asesor revisará su caso, referencia CASE-3630960D3B49.",
  "state": "HANDED_OFF",
  "language": "es",
  "pending_confirmation": null,
  "case_id": "CASE-3630960D3B49",
  "turn": 3
}
```

`d5-t4` · Message after the handoff is appended to the case (T-38)

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "mensaje": "¿En cuánto tiempo me contactan?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a7c8-7435-9064-02068925b196",
  "reply": "Agregué su mensaje a su caso, referencia CASE-3630960D3B49. Un asesor lo revisará.",
  "state": "HANDED_OFF",
  "language": "es",
  "pending_confirmation": null,
  "case_id": "CASE-3630960D3B49",
  "turn": 4
}
```
<!-- /example -->

### Dialogue 12 (pt): savings balance, then a card

<!-- examples: d12- -->
`d12-t0` · Open the chat (turn 0)

```http
POST /chat/sesiones
Authorization: Bearer <customer token>

{}

HTTP 201
{
  "conversation_id": "conv_01a10a58-a8c9-774b-a00c-4de516464a5c",
  "reply": "Olá, em que posso ajudar?",
  "state": "IDLE",
  "language": "pt",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 0
}
```

`d12-t1` · Savings balance, only one eligible: no question

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a8c9-774b-a00c-4de516464a5c",
  "mensaje": "Oi, qual é o saldo da minha conta poupança?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a8c9-774b-a00c-4de516464a5c",
  "reply": "O saldo atual da sua conta poupança final 2700 é de 3,447.34 USD, segundo os dados de 3 de outubro de 2026 às 23:34.",
  "state": "IDLE",
  "language": "pt",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 1
}
```

`d12-t2` · Three credit cards: clarification

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a8c9-774b-a00c-4de516464a5c",
  "mensaje": "E o do cartão de crédito?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a8c9-774b-a00c-4de516464a5c",
  "reply": "Você tem três cartões de crédito: final 7858 (ativo), final 2960 (ativo) e final 2952 (bloqueado). De qual deles quer consultar o saldo? Informe os últimos 4 dígitos.",
  "state": "SELECT_CARD",
  "language": "pt",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 2
}
```

`d12-t3` · Card chosen by last 4

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a8c9-774b-a00c-4de516464a5c",
  "mensaje": "O 7858."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a8c9-774b-a00c-4de516464a5c",
  "reply": "O saldo atual do seu cartão de crédito final 7858 é de 1,126.12 USD e o limite de crédito é de 5,366.87 USD, segundo os dados de 3 de outubro de 2026 às 23:34.",
  "state": "IDLE",
  "language": "pt",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 3
}
```

`d12-t4` · Closing

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10a58-a8c9-774b-a00c-4de516464a5c",
  "mensaje": "Obrigado, era isso."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a8c9-774b-a00c-4de516464a5c",
  "reply": "Por nada. Até logo.",
  "state": "ENDED",
  "language": "pt",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 4
}
```
<!-- /example -->

### Dialogue 2 (pt): block a lost card with step-up

<!-- examples: d2- -->
`d2-session` · Jurado starts a test session for a customer

```http
POST /identidad/sesion-prueba
Authorization: Bearer <jurado token>

{
  "customer_id": "CLI-JPK27B33SV65",
  "idioma": "pt"
}

HTTP 201
{
  "token": "<token>",
  "tipo_token": "bearer",
  "sesion_id": "ses_9HereTHHD5EDuiIBCr83zmC7JeZomp9o",
  "customer_id": "CLI-JPK27B33SV65",
  "customer_status": "Active",
  "nivel": "L1",
  "idioma": "pt",
  "expira_inactividad_en": "2026-10-05T04:50:45.272723Z",
  "expira_absoluta_en": "2026-10-05T05:35:45.272723Z",
  "aviso": "IdP de prueba simulado: no es un proveedor de identidad real (POL-AUTH-13)."
}
```

`d2-t0` · Open the chat (turn 0)

```http
POST /chat/sesiones
Authorization: Bearer <test session token>

{}

HTTP 201
{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "reply": "Olá, em que posso ajudar?",
  "state": "IDLE",
  "language": "pt",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 0
}
```

`d2-t1` · Block request: step-up required

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "mensaje": "Oi, perdi meu cartão de crédito. Quero bloquear agora."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "reply": "O seu cartão de crédito final 8407 está ativo. Para bloquear, preciso confirmar sua identidade com um código de verificação; digite-o na janela de verificação, não aqui no chat.",
  "state": "STEP_UP",
  "language": "pt",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 1
}
```

`d2-otp` · Jurado console issues a test one-time code

```http
POST /identidad/otp-prueba
Authorization: Bearer <jurado token>

{
  "sesion_id": "ses_9HereTHHD5EDuiIBCr83zmC7JeZomp9o"
}

HTTP 201
{
  "sesion_id": "ses_9HereTHHD5EDuiIBCr83zmC7JeZomp9o",
  "codigo": "960532",
  "expira_en": "2026-10-05T04:40:45.363831Z",
  "aviso": "IdP de prueba simulado: no es un proveedor de identidad real (POL-AUTH-13)."
}
```

`d2-t2` · Code sent from the verification widget: confirmation prompt

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "codigo_step_up": "960532"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "reply": "Identidade confirmada. Vou bloquear o seu cartão de crédito final 8407. Depois do bloqueio ele deixa de funcionar e eu não consigo desbloqueá-lo; só um atendente pode fazer isso. Confirma o bloqueio do cartão final 8407? Responda sim ou não.",
  "state": "AWAIT_CONFIRMATION",
  "language": "pt",
  "pending_confirmation": {
    "card_last4": "8407",
    "card_type": "Tarjeta Crédito",
    "expires_at": "2026-10-05T04:37:45.413791+00:00"
  },
  "case_id": null,
  "turn": 2
}
```

`d2-t3` · Explicit yes: block executed and verified

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "mensaje": "Sim, pode bloquear."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "reply": "Pronto: o seu cartão de crédito final 8407 está bloqueado. Para desbloquear ou pedir um cartão novo, é preciso falar com um atendente; posso transferir você, se quiser.",
  "state": "IDLE",
  "language": "pt",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 3
}
```

`d2-t4` · Closing

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "mensaje": "Não, era só isso, valeu."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-a9f8-7a3f-9ba2-99710b2d8e84",
  "reply": "Por nada. Até logo.",
  "state": "ENDED",
  "language": "pt",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 4
}
```
<!-- /example -->

### Test-IdP session (es): any customer in gold

<!-- examples: idp-t -->
`idp-t0` · Open the chat (turn 0)

```http
POST /chat/sesiones
Authorization: Bearer <test session token>

{}

HTTP 201
{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "reply": "Hola, ¿en qué puedo ayudarle?",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 0
}
```

`idp-t1` · Balance: clarification between products

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "mensaje": "Hola, ¿cuál es mi saldo?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "reply": "Puedo consultar el saldo de su tarjeta de crédito terminada en 0990, de su cuenta de ahorros terminada en 5747 o de su cuenta de ahorros terminada en 1447. ¿Cuál quiere consultar?",
  "state": "SELECT_CARD",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 1
}
```

`idp-t2` · Credit card chosen by last 4

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "mensaje": "La terminada en 0990."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "reply": "El saldo actual de su tarjeta de crédito terminada en 0990 es de 1,032.68 USD y su límite de crédito es de 13,678.19 USD, según los datos del 3 de octubre de 2026 a las 23:34.",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 2
}
```

`idp-t3` · "That card" keeps the selected card (D-35)

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "mensaje": "¿Qué movimientos tuvo esa tarjeta en el último mes?"
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "reply": "Estas son las transacciones de su tarjeta de crédito terminada en 0990 entre el 19 de mayo de 2026 y el 18 de junio de 2026: - 24 de mayo de 2026, retiro, 214.92 USD, aprobada",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 3
}
```

`idp-t4` · Closing

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "mensaje": "Gracias, eso es todo."
}

HTTP 200
{
  "conversation_id": "conv_01a10a58-ab16-7da2-acb0-3a3d8ef89f69",
  "reply": "Con gusto. Hasta luego.",
  "state": "ENDED",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 4
}
```
<!-- /example -->
