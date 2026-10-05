# Contract: chat API for the frontend

| Field | Value |
|---|---|
| Contract version | `chat-api-0.2` (0.2 adds the simulated SMS of 4.3 and the customer portal of 4.7) |
| Date | 2026-10-05 |
| Implementation | `backend/` (FastAPI): `routers/`, `schemas/`, `services/agente/` |
| Machine-readable spec | `docs/contracts/openapi.json` (OpenAPI 3.1, exported from the app) |
| Captured examples | `docs/contracts/chat_api_examples.json` (every call shown here, plus full audit trails) |
| Related contracts | `state_machine.md` (`sm-0.4`), `audit_log.md` (`audit-0.2`), `docs/policy_cards.md` (`cards-synthetic-0.9`) |

This is the backend API that four screens use: the **customer chat**, the **customer portal**, the **human agent
inbox** and the **jurado test console**. It describes the API as implemented. Every example below was captured from a
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
   as a JSON string. The route answers the browser `{"ok": true}`, never the token.
3. The route stores the token in the cookie `token` (`httpOnly`, `sameSite=strict`, `path=/`, `maxAge` 60
   minutes). `secure` keeps SvelteKit's default: on, except on `http://localhost`.
4. On every request, `src/hooks.server.ts` calls `GET /autenticacion/mi-perfil` with the cookie's token and
   puts the user (`rol`, `customer_id`) in `event.locals.usuario`. If that call fails, it deletes the cookie,
   and `/app*` redirects to `/login?volver=<page>`, which returns there after signing in.
5. `POST /logout` closes the backend session (`/autenticacion/cerrar-sesion`) and deletes the cookie.

The other screens call the backend from SvelteKit server code with the cookie's token
(`$lib/server/backend`, which reads `BACKEND_URL`; see `frontend/.env.example`):

- **Page loads** (`+page.server.ts`) read the portal (`/cliente/*`), the inbox (`/casos`) and the audit trail.
- **The chat** posts from the browser to `src/routes/api/chat/[accion]/+server.ts`. It forwards `sesiones`
  to `POST /chat/sesiones`, `mensaje` to `POST /chat/mensaje` (135 s timeout) and `codigo` to
  `POST /autenticacion/otp-demo`.

The backend's CORS is open (`*`), but that is for local tools such as the CLI; the browser always goes
through the server routes.

**Roles.** `rol` comes from `mi-perfil` and decides the screen:

| `rol` | Screen | Endpoints |
|---|---|---|
| `cliente` with a `customer_id` | customer chat and portal | `/chat/*`, `/cliente/*`, `/autenticacion/*` |
| `agente` | case inbox | `/casos`, `/casos/{case_id}`, `/auditoria/*` |
| `jurado` | test console | `/identidad/*`, `/auditoria/*`, and the chat with a test session token |

**The jurado's test session.** `POST /identidad/sesion-prueba` returns a second token, a *customer*
session for the chosen customer (`metodo: idp_prueba`). Keep it in its own httpOnly cookie (for example
`token_prueba`) and never overwrite the jurado's `token`. The console then uses the jurado token for
`/identidad/*` and `/auditoria/*`, and the test token for `/chat/*`. Always show the `aviso` text that comes
with it: the test IdP is simulated and must be labeled as such (POL-AUTH-13).

**Lifetimes.** The cookie lasts 60 minutes, the backend session's maximum; the session can end earlier
(15 minutes idle, or sign-out). Treat any `401` as "sign in again": delete the cookie and go to the login
page. The chat keeps the `conversation_id` and the transcript in the tab's `sessionStorage`. After signing in
again, it resumes with `POST /chat/sesiones` and that `conversation_id` (section 4.6). If the tab is still in
the same session, it just continues the conversation.

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
  "sesion_id": "ses_X7XzBe1pqqerQ8bWKxWI4Pw0j_3sqhUc",
  "rol": "cliente",
  "nivel": "L1",
  "metodo": "contrasena",
  "customer_id": "CLI-SQJOCEDJJNCZ",
  "idioma": null,
  "expira_inactividad_en": "2026-10-05T08:44:22.718579Z",
  "expira_absoluta_en": "2026-10-05T09:29:22.672336Z"
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
| `POST /autenticacion/otp-demo` | customer session, `ENV=development` only | Simulated SMS: the session's own step-up code, only while its conversation is in `STEP_UP` (4.3, POL-AUTH-14) | `201` |
| `POST /chat/sesiones` | customer session | Start a conversation (turn 0), or resume one after re-authentication with `conversation_id` | `201` |
| `POST /chat/mensaje` | customer session | One turn: `mensaje` **or** `codigo_step_up`, optional `idioma` | `200` |
| `GET /cliente/tarjetas` | customer session | The customer's cards: `ref`, `last4`, `tipo`, `estado` (4.7) | `200` |
| `GET /cliente/transacciones?dias=` | customer session | Card transactions of the last `dias` days (1 to 90, default 30), per card | `200` |
| `GET /cliente/conversaciones` | customer session | The customer's conversations, newest first (at most 50) | `200` |
| `GET /cliente/casos` | customer session | The customer's cases: reference, date, priority, intent, card last 4 | `200` |
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
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
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
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
  "mensaje": "Hola, ¿cuál es mi saldo?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
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
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
  "mensaje": "La tarjeta de crédito."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
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
   (POL-AUTH-08). A code typed in the chat text is redacted and ignored. In the demo there is no real SMS.
   The code comes from one of two places. The jurado console issues it with `POST /identidad/otp-prueba`
   for that session (section 8). With `ENV=development`, the customer's own page can ask for it as a
   **simulated SMS** with `POST /autenticacion/otp-demo` (POL-AUTH-14). That call only works while a
   conversation of the session is in `STEP_UP` (`409 NOT_IN_STEP_UP` otherwise). Outside development it
   answers `403 DEMO_OTP_DISABLED`. Show the code labeled with its `aviso`, and let the customer type it in
   the widget.
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
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
  "mensaje": "Oi, perdi meu cartão de crédito. Quero bloquear agora."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
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
  "sesion_id": "ses_Mm8_hHJ6tan9U7nFAKN-updtq84U4mjC"
}

HTTP 201
{
  "sesion_id": "ses_Mm8_hHJ6tan9U7nFAKN-updtq84U4mjC",
  "codigo": "451615",
  "expira_en": "2026-10-05T08:34:27.312929Z",
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
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
  "codigo_step_up": "451615"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
  "reply": "Identidade confirmada. Vou bloquear o seu cartão de crédito final 8407. Depois do bloqueio ele deixa de funcionar e eu não consigo desbloqueá-lo; só um atendente pode fazer isso. Confirma o bloqueio do cartão final 8407? Responda sim ou não.",
  "state": "AWAIT_CONFIRMATION",
  "language": "pt",
  "pending_confirmation": {
    "card_last4": "8407",
    "card_type": "Tarjeta Crédito",
    "expires_at": "2026-10-05T08:31:27.380801+00:00"
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
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
  "mensaje": "Sim, pode bloquear."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
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
  "conversation_id": "conv_01a10b2e-a428-75c4-a3e9-25f3cee7f974",
  "codigo_step_up": "000000"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-a428-75c4-a3e9-25f3cee7f974",
  "reply": "El código no es válido o venció. Ingréselo de nuevo en la ventana de verificación.",
  "state": "STEP_UP",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 2
}
```
<!-- /example -->

The same block with the simulated SMS, for a customer signed in with a password:

<!-- example: sms-t1 -->
`sms-t1` · Block request: step-up required

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10b2e-a5b3-7ab6-bde9-603ad8096a0d",
  "mensaje": "Quiero bloquear mi tarjeta de débito."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-a5b3-7ab6-bde9-603ad8096a0d",
  "reply": "Su tarjeta de débito terminada en 4214 está activa. Para bloquearla necesito confirmar su identidad con un código de verificación; ingréselo en la ventana de verificación, no en el chat.",
  "state": "STEP_UP",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 1
}
```
<!-- /example -->

<!-- example: sms-otp -->
`sms-otp` · Simulated SMS: the customer's own code (development only)

```http
POST /autenticacion/otp-demo
Authorization: Bearer <customer token>

HTTP 201
{
  "codigo": "724979",
  "expira_en": "2026-10-05T08:34:29.081970Z",
  "canal": "sms_simulado",
  "aviso": "SMS simulado del IdP de prueba: un banco real enviaría este código a su teléfono (POL-AUTH-14)."
}
```
<!-- /example -->

<!-- example: sms-t2 -->
`sms-t2` · Code typed in the verification widget: confirmation prompt

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10b2e-a5b3-7ab6-bde9-603ad8096a0d",
  "codigo_step_up": "724979"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-a5b3-7ab6-bde9-603ad8096a0d",
  "reply": "Identidad confirmada. Voy a bloquear su tarjeta de débito terminada en 4214. Después del bloqueo la tarjeta deja de funcionar y yo no puedo desbloquearla; eso solo lo hace un asesor. ¿Confirma el bloqueo de la tarjeta terminada en 4214? Responda sí o no.",
  "state": "AWAIT_CONFIRMATION",
  "language": "es",
  "pending_confirmation": {
    "card_last4": "4214",
    "card_type": "Tarjeta Débito",
    "expires_at": "2026-10-05T08:31:29.172944+00:00"
  },
  "case_id": null,
  "turn": 2
}
```
<!-- /example -->

<!-- example: sms-t3 -->
`sms-t3` · A no cancels the block; nothing runs

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10b2e-a5b3-7ab6-bde9-603ad8096a0d",
  "mensaje": "No, mejor no."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-a5b3-7ab6-bde9-603ad8096a0d",
  "reply": "Entendido, no bloqueé la tarjeta.",
  "state": "IDLE",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 3
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
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
  "mensaje": "No, por ahora solo quiero el reclamo."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
  "reply": "No bloqueé la tarjeta. No puedo determinar si este cobro es válido; los reclamos los revisa un asesor. Un asesor revisará su caso, referencia CASE-ED908D0D6BC0.",
  "state": "HANDED_OFF",
  "language": "es",
  "pending_confirmation": null,
  "case_id": "CASE-ED908D0D6BC0",
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
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
  "mensaje": "¿En cuánto tiempo me contactan?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
  "reply": "Agregué su mensaje a su caso, referencia CASE-ED908D0D6BC0. Un asesor lo revisará.",
  "state": "HANDED_OFF",
  "language": "es",
  "pending_confirmation": null,
  "case_id": "CASE-ED908D0D6BC0",
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
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
  "mensaje": "Hola de nuevo"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
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
  "conversation_id": "conv_01a10b2e-cf52-7b2c-bfb6-f4c67c53833a",
  "mensaje": "La tarjeta de crédito."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-cf52-7b2c-bfb6-f4c67c53833a",
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
  "conversation_id": "conv_01a10b2e-cf52-7b2c-bfb6-f4c67c53833a"
}

HTTP 201
{
  "conversation_id": "conv_01a10b2e-cf52-7b2c-bfb6-f4c67c53833a",
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
  "conversation_id": "conv_01a10b2e-cf52-7b2c-bfb6-f4c67c53833a",
  "mensaje": "Sí"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-cf52-7b2c-bfb6-f4c67c53833a",
  "reply": "Puedo consultar el saldo de su tarjeta de crédito terminada en 5070 o de su cuenta de ahorros terminada en 1317. ¿Cuál quiere consultar?",
  "state": "SELECT_CARD",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 4
}
```
<!-- /example -->

### 4.7 Customer portal

Besides the chat, a customer session can read its own data for the portal screens (POL-PII-10):

- **Calls and checks.** All four calls are `GET` with the customer's token. Cards and transactions come
  from the same tools as the assistant, with the same checks. A customer whose status is `Suspended` or
  `Closed` gets `403 CUSTOMER_STATUS_REVIEW` for them (POL-AUTH-09), and still sees their case reference.
- **No internal IDs.** Responses never hold `card_id`, `transaction_id` or the `customer_id`. A card is
  named by `ref` (`t1`, `t2`, … in a stable order), which only groups rows on screen. To ask about a card or
  a transaction, open the chat with a message that names its type and last 4.
- **Transactions.** They come per card, at most 20 per card (the most recent; `truncada` says there were
  more), over the last `dias` days of the bank clock (`desde`, `hasta`).
- **Amounts.** `monto` is a decimal string in the transaction's currency. It is always positive; `tipo`
  (`Purchase`, `Withdrawal`, `Payment`) says what it is. Never add up amounts of different currencies.
- **Cases.** A case shows its reference and context, never the case file: that stays with agents.
  `motivo` is the request's intent (`docs/intents.md`), null for a handoff at sign-in.
- **No balances.** Only the assistant states them, read in the turn with their `as_of`.
- **Not audited.** These reads are not chat turns and do not write to the audit log.

<!-- example: portal-cards -->
`portal-cards` · The customer's cards, no internal IDs

```http
GET /cliente/tarjetas
Authorization: Bearer <customer token>

HTTP 200
[
  {
    "ref": "t1",
    "last4": "6898",
    "tipo": "Tarjeta Débito",
    "estado": "Active"
  },
  {
    "ref": "t2",
    "last4": "6873",
    "tipo": "Tarjeta Crédito",
    "estado": "Active"
  },
  {
    "ref": "t3",
    "last4": "0727",
    "tipo": "Tarjeta Crédito",
    "estado": "Blocked"
  }
]
```
<!-- /example -->

<!-- example: portal-transactions -->
`portal-transactions` · Card transactions of the last 30 days of the bank clock

```http
GET /cliente/transacciones?dias=30
Authorization: Bearer <customer token>

HTTP 200
{
  "desde": "2026-05-19",
  "hasta": "2026-06-18",
  "tarjetas": [
    {
      "ref": "t1",
      "last4": "6898",
      "tipo": "Tarjeta Débito",
      "estado": "Active",
      "truncada": false,
      "transacciones": []
    },
    {
      "ref": "t2",
      "last4": "6873",
      "tipo": "Tarjeta Crédito",
      "estado": "Active",
      "truncada": false,
      "transacciones": [
        {
          "fecha": "2026-06-06T19:43:19",
          "tipo": "Purchase",
          "monto": "127.37",
          "moneda": "USD",
          "comercio": "Uber",
          "estado": "Declined"
        },
        {
          "fecha": "2026-05-26T02:17:17",
          "tipo": "Purchase",
          "monto": "259.15",
          "moneda": "USD",
          "comercio": "Cine Premium",
          "estado": "Approved"
        }
      ]
    },
    {
      "ref": "t3",
      "last4": "0727",
      "tipo": "Tarjeta Crédito",
      "estado": "Blocked",
      "truncada": false,
      "transacciones": []
    }
  ]
}
```
<!-- /example -->

<!-- example: portal-conversations -->
`portal-conversations` · The customer's conversations, newest first

```http
GET /cliente/conversaciones
Authorization: Bearer <customer token>

HTTP 200
[
  {
    "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
    "estado": "HANDED_OFF",
    "turnos": 4,
    "idioma": "es",
    "case_id": "CASE-ED908D0D6BC0",
    "creada_en": "2026-10-05T08:29:25.562850Z",
    "actualizada_en": "2026-10-05T08:29:25.993312Z"
  }
]
```
<!-- /example -->

<!-- example: portal-cases -->
`portal-cases` · The customer's cases: reference and context, never the case file

```http
GET /cliente/casos
Authorization: Bearer <customer token>

HTTP 200
[
  {
    "case_id": "CASE-ED908D0D6BC0",
    "creado_en": "2026-10-05T08:29:25.871796Z",
    "prioridad": "normal",
    "motivo": "charge_dispute",
    "tarjetas_last4": [
      "4950"
    ],
    "mensajes_agregados": 1,
    "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7"
  }
]
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
    "case_id": "CASE-ED908D0D6BC0",
    "created_at": "2026-10-05T08:29:25.871796Z",
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
GET /auditoria/conversacion/conv_01a10b2e-9891-724a-9051-4550c8121ac7
Authorization: Bearer <agent token>

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
  "total": 18,
  "cadena_valida": true,
  "eventos": [
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10b2e-98e4-78e8-ad52-7c0045bb86e8",
      "event_type": "message_received",
      "occurred_at": "2026-10-05T08:29:25.604Z",
      "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
      "session_id": "ses_oIdSIQwgbqu-xfCK41xddCaKt8RqP2id",
      "turn_index": 1,
      "trace_id": "40e06af9acb113bf4bd08bfc6978e167",
      "span_id": "cbb927834effce50",
      "actor": "customer",
      "customer_ref": "765986de73b346dd7b9ba80a0d5578bf",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.9",
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
      "prev_event_hash": "2d8eae38f69425029c034ceafe578dad98eca9efd972e06fc505014041a9b7c8",
      "event_hash": "55ad09ce0c61972c72d901af295e11a38d4de4e5316bb47fc9218b35fdd69455"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10b2e-98f0-7002-89a7-451ced224828",
      "event_type": "classification",
      "occurred_at": "2026-10-05T08:29:25.616Z",
      "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
      "session_id": "ses_oIdSIQwgbqu-xfCK41xddCaKt8RqP2id",
      "turn_index": 1,
      "trace_id": "40e06af9acb113bf4bd08bfc6978e167",
      "span_id": "64e4f781210aae85",
      "actor": "orchestrator",
      "customer_ref": "765986de73b346dd7b9ba80a0d5578bf",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.9",
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
      "prev_event_hash": "55ad09ce0c61972c72d901af295e11a38d4de4e5316bb47fc9218b35fdd69455",
      "event_hash": "304ff7108cb6b4b6bed663ccdb5954b153ab463f08fd26abd1852b828d3b8d23"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10b2e-9905-771a-b991-2d49e28ea21d",
      "event_type": "tool_call",
      "occurred_at": "2026-10-05T08:29:25.637Z",
      "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
      "session_id": "ses_oIdSIQwgbqu-xfCK41xddCaKt8RqP2id",
      "turn_index": 1,
      "trace_id": "40e06af9acb113bf4bd08bfc6978e167",
      "span_id": "659f0caf5ebce25f",
      "actor": "tool_gateway",
      "customer_ref": "765986de73b346dd7b9ba80a0d5578bf",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.9",
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
          "card_ref": "c46ed1104e1f61ecc907d6746fbf5011",
          "last4": "1883",
          "type": "Tarjeta Débito",
          "status": "Active"
        },
        {
          "card_ref": "6708cb472dfac582a72f09688ff54ea4",
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
      "prev_event_hash": "304ff7108cb6b4b6bed663ccdb5954b153ab463f08fd26abd1852b828d3b8d23",
      "event_hash": "8ebe14db839965ae83f0866f378b5f27d1e1f40b9b77eafa3926e81b36e33800"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10b2e-9963-772d-bd24-c8d531c155bd",
      "event_type": "policy_decision",
      "occurred_at": "2026-10-05T08:29:25.731Z",
      "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
      "session_id": "ses_oIdSIQwgbqu-xfCK41xddCaKt8RqP2id",
      "turn_index": 1,
      "trace_id": "40e06af9acb113bf4bd08bfc6978e167",
      "span_id": "5d73783427483d57",
      "actor": "orchestrator",
      "customer_ref": "765986de73b346dd7b9ba80a0d5578bf",
      "auth_level": "L1",
      "state": "SELECT_TRANSACTION",
      "policy_version": "cards-synthetic-0.9",
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
            "transaction_ref": "5282a27a8deaed8865792a3c76a8cdcf",
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
      "prev_event_hash": "4eb5247a56f847ece59468fb717efff9555cea9c8e45407819045d49fecdae63",
      "event_hash": "184441b697e2a51d0ac0bf2798de033fe92f530270cc184558cf18f94ce84d9c"
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
  "conversation_id": "conv_01a10b2e-a738-7dd1-8baa-d1f0d1181450",
  "mensaje": "Hola, ¿cuál es mi saldo?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-a738-7dd1-8baa-d1f0d1181450",
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
GET /auditoria/ses_3NW0sp9wZup5YwZ0vykHFlwRvsE0Aywy
Authorization: Bearer <jurado token>

HTTP 200
{
  "session_id": "ses_3NW0sp9wZup5YwZ0vykHFlwRvsE0Aywy",
  "total": 8,
  "eventos": [
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10b2e-cbbc-7ab2-9cb4-a1a2ce89d236",
      "event_type": "llm_call",
      "occurred_at": "2026-10-05T08:29:38.620Z",
      "conversation_id": "conv_01a10b2e-a738-7dd1-8baa-d1f0d1181450",
      "session_id": "ses_3NW0sp9wZup5YwZ0vykHFlwRvsE0Aywy",
      "turn_index": 1,
      "trace_id": "3024bc00a2588aeca952e419d8e95046",
      "span_id": "2a71cf1a3ceef72e",
      "actor": "orchestrator",
      "customer_ref": "56f2fd4c9d84d0c4664f2f0561d59a1f",
      "auth_level": "L1",
      "state": "SELECT_CARD",
      "policy_version": "cards-synthetic-0.9",
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
      "llm_call_id": "llm_3f9f0943553d",
      "purpose": "reply_wording",
      "provider": "openai",
      "model_id": "gpt-4o-mini",
      "prompt_template": "reformular-v1",
      "temperature": 0,
      "max_tokens": 400,
      "input_tokens": 0,
      "cached_input_tokens": 0,
      "output_tokens": 0,
      "latency_ms": 9234,
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
      "prev_event_hash": "ec49193532064c83baef44278ee9ff56b090666433bf2ce70162664f2ca863cb",
      "event_hash": "d418ef28c1fc62244cdb9378ef87f11cace7260ed334b2b40416a5fa09a9da60"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10b2e-cbc2-71ff-8093-b5a57bcc6950",
      "event_type": "policy_decision",
      "occurred_at": "2026-10-05T08:29:38.626Z",
      "conversation_id": "conv_01a10b2e-a738-7dd1-8baa-d1f0d1181450",
      "session_id": "ses_3NW0sp9wZup5YwZ0vykHFlwRvsE0Aywy",
      "turn_index": 1,
      "trace_id": "3024bc00a2588aeca952e419d8e95046",
      "span_id": "e6125173100089b8",
      "actor": "orchestrator",
      "customer_ref": "56f2fd4c9d84d0c4664f2f0561d59a1f",
      "auth_level": "L1",
      "state": "SELECT_CARD",
      "policy_version": "cards-synthetic-0.9",
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
          "llm_3f9f0943553d"
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
      "prev_event_hash": "d418ef28c1fc62244cdb9378ef87f11cace7260ed334b2b40416a5fa09a9da60",
      "event_hash": "148abb13d4d950ddc13a2e36f7ddc2978bc97ab56e4fa21f85830164d7fc174e"
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
  "sesion_id": "ses_xcwzyyF1lohodqFO7zxSQAnn06M4-YjS",
  "customer_id": "CLI-1IKG56EOI0A5",
  "customer_status": "Active",
  "nivel": "L1",
  "idioma": "es",
  "expira_inactividad_en": "2026-10-05T08:44:27.635170Z",
  "expira_absoluta_en": "2026-10-05T09:29:27.635170Z",
  "aviso": "IdP de prueba simulado: no es un proveedor de identidad real (POL-AUTH-13)."
}
```
<!-- /example -->

<!-- example: idp-audit types=message_received,classification,tool_call,policy_decision turn=3 -->
`idp-audit` · Audit trail of the test session

```http
GET /auditoria/ses_xcwzyyF1lohodqFO7zxSQAnn06M4-YjS
Authorization: Bearer <jurado token>

HTTP 200
{
  "session_id": "ses_xcwzyyF1lohodqFO7zxSQAnn06M4-YjS",
  "total": 18,
  "eventos": [
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10b2e-a1bb-74df-b9f1-0020412ecd7f",
      "event_type": "message_received",
      "occurred_at": "2026-10-05T08:29:27.867Z",
      "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
      "session_id": "ses_xcwzyyF1lohodqFO7zxSQAnn06M4-YjS",
      "turn_index": 3,
      "trace_id": "ffd6e2bdd9fec3eff8d3db2429a6ac5b",
      "span_id": "4b647c1b5403d213",
      "actor": "customer",
      "customer_ref": "044e09dc492ee6a3e4c114f5167d15d6",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.9",
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
      "prev_event_hash": "03772bf7891f78eee3d572d93f81de6e55e84e36ca9aa31c63ef5a8bd230676f",
      "event_hash": "b499f65d11fc789d3975bd669f7ffb93edfa2c93f0aea06d9668ecfbe2314a6e"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10b2e-a1c2-7963-8802-1632c2840459",
      "event_type": "classification",
      "occurred_at": "2026-10-05T08:29:27.874Z",
      "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
      "session_id": "ses_xcwzyyF1lohodqFO7zxSQAnn06M4-YjS",
      "turn_index": 3,
      "trace_id": "ffd6e2bdd9fec3eff8d3db2429a6ac5b",
      "span_id": "1bbf679c3a13b89b",
      "actor": "orchestrator",
      "customer_ref": "044e09dc492ee6a3e4c114f5167d15d6",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.9",
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
      "prev_event_hash": "b499f65d11fc789d3975bd669f7ffb93edfa2c93f0aea06d9668ecfbe2314a6e",
      "event_hash": "27bd456303974fa71279bf26b1e66b46e0dbd46eb56d9d148d2c69bd7bcf0141"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10b2e-a1d2-7854-b3ac-238e2837beb8",
      "event_type": "tool_call",
      "occurred_at": "2026-10-05T08:29:27.890Z",
      "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
      "session_id": "ses_xcwzyyF1lohodqFO7zxSQAnn06M4-YjS",
      "turn_index": 3,
      "trace_id": "ffd6e2bdd9fec3eff8d3db2429a6ac5b",
      "span_id": "6b62404f010573b0",
      "actor": "tool_gateway",
      "customer_ref": "044e09dc492ee6a3e4c114f5167d15d6",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.9",
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
      "latency_ms": 15,
      "result": [
        {
          "card_ref": "9014f7fb37ed6e95a1d53e8849c69212",
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
      "prev_event_hash": "27bd456303974fa71279bf26b1e66b46e0dbd46eb56d9d148d2c69bd7bcf0141",
      "event_hash": "73eb3b573db1757fb434eae2555207e637d2a230f62e45a4bd0ae19a1eebe36b"
    },
    {
      "schema_version": "audit-0.2",
      "event_id": "01a10b2e-a1ef-7e73-8e7a-c53ea9465953",
      "event_type": "policy_decision",
      "occurred_at": "2026-10-05T08:29:27.919Z",
      "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
      "session_id": "ses_xcwzyyF1lohodqFO7zxSQAnn06M4-YjS",
      "turn_index": 3,
      "trace_id": "ffd6e2bdd9fec3eff8d3db2429a6ac5b",
      "span_id": "9658baf64f40e9ed",
      "actor": "orchestrator",
      "customer_ref": "044e09dc492ee6a3e4c114f5167d15d6",
      "auth_level": "L1",
      "state": "IDLE",
      "policy_version": "cards-synthetic-0.9",
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
              "transaction_ref": "75cbc34ea435b132547d503c22a32883",
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
      "prev_event_hash": "f2911ac2f924c052ea0e439bb94fc9b13b642c318c872e4a8ce8f1219c6ef25d",
      "event_hash": "893ce4e61a4f2173b7359c1e1b5d6b86b2f1a61dff94754a84dd6e0dc008a477"
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
| 403 | `NOT_A_CUSTOMER_SESSION` | `/chat/*`, `/cliente/*`, `otp-demo` | The token is an agent's or a jurado's, or a registered user with no customer | Use a customer session |
| 403 | `CONVERSATION_FORBIDDEN` | `/chat/mensaje` | The conversation belongs to another customer | Start a new conversation |
| 403 | `CUSTOMER_STATUS_REVIEW` | `step-up`, `otp-prueba`, `otp-demo`, `/cliente/tarjetas`, `/cliente/transacciones` | The customer is `Suspended` or `Closed` | Nothing to retry; the chat already handed off |
| 403 | `STEP_UP_LOCKED` | `step-up`, `otp-prueba`, `otp-demo` | 3 wrong codes in this session | No more codes for this session |
| 403 | `"El registro abierto está deshabilitado en este entorno."` (text) | `registrar` | `ENV` is not `development` | Hide registration |
| 403 | `DEMO_OTP_DISABLED` | `otp-demo` | `ENV` is not `development` | Take the code from the jurado console |
| 404 | `CONVERSATION_NOT_FOUND` | `/chat/*` | Unknown conversation; or, when resuming, another customer's | Start a new conversation |
| 404 | `CUSTOMER_NOT_FOUND` | `sesion-prueba` | The customer is not in gold | Show the message |
| 404 | `SESSION_NOT_FOUND` | `otp-prueba` | Unknown or expired test session | Open a new test session |
| 404 | `"Caso no encontrado."` (text) | `/casos/{case_id}` | Unknown case | Show the message |
| 409 | `CONVERSATION_CLOSED` | `/chat/sesiones` with `conversation_id` | The conversation ended or was handed off | Start a new conversation |
| 409 | `SESSION_STILL_ACTIVE` | `/chat/sesiones` with `conversation_id` | The conversation's session is still valid | Keep using that session |
| 409 | `SESSION_NOT_ATTACHED` | `/chat/mensaje` | This token's session is not the conversation's current session | Call `POST /chat/sesiones` with `conversation_id` first |
| 409 | `NOT_IN_STEP_UP` | `otp-demo` | No conversation of this session is waiting for a code | Ask only while the chat state is `STEP_UP` |
| 422 | FastAPI validation list | any | The body or query does not match the schema | Fix the request |
| 429 | `RATE_LIMITED` | `/identidad/clientes` | More than 10 searches per minute | Wait a minute |
| 503 | `GOLD_UNAVAILABLE` | `/identidad/*` | The server has no gold data loaded | Report to the operator |

When a bank tool fails inside a chat turn, the API still answers `200`: the assistant says the service could
not complete the request, claims no result, and hands off (POL-ESC-07).

Captured error responses:

<!-- example: err-sms-not-in-step-up -->
`err-sms-not-in-step-up` · Simulated SMS with no verification pending

```http
POST /autenticacion/otp-demo
Authorization: Bearer <customer token>

HTTP 409
{
  "detail": {
    "codigo": "NOT_IN_STEP_UP",
    "mensaje": "No hay una verificación pendiente en su conversación."
  }
}
```
<!-- /example -->

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
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
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
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138"
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
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
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
        "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
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
GET /casos/CASE-ED908D0D6BC0
Authorization: Bearer <agent token>

HTTP 200
{
  "case_id": "CASE-ED908D0D6BC0",
  "created_at": "2026-10-05T08:29:25.871796Z",
  "priority": "normal",
  "reason_rule_ids": [
    "POL-ESC-01"
  ],
  "language": "es",
  "customer_id": "CLI-AYAHYQEG16BZ",
  "auth_level": "L1",
  "policy_version": "cards-synthetic-0.9",
  "conversation_ref": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
  "appended_messages": [
    {
      "text_redacted": "¿En cuánto tiempo me contactan?",
      "received_at": "2026-10-05T08:29:25.968775+00:00"
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
        "called_at": "08:29:25",
        "status": "ok",
        "result_ref": "audit://conv_01a10b2e-9891-724a-9051-4550c8121ac7/c1"
      },
      {
        "tool_call_id": "c2",
        "tool": "list_cards",
        "called_at": "08:29:25",
        "status": "ok",
        "result_ref": "audit://conv_01a10b2e-9891-724a-9051-4550c8121ac7/c2"
      },
      {
        "tool_call_id": "c3",
        "tool": "list_transactions",
        "called_at": "08:29:25",
        "status": "ok",
        "result_ref": "audit://conv_01a10b2e-9891-724a-9051-4550c8121ac7/c3"
      },
      {
        "tool_call_id": "c4",
        "tool": "describe_transaction",
        "called_at": "08:29:25",
        "status": "ok",
        "result_ref": "audit://conv_01a10b2e-9891-724a-9051-4550c8121ac7/c4"
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
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
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
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
  "mensaje": "Hola, ¿cuál es mi saldo?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
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
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
  "mensaje": "La tarjeta de crédito."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
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
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
  "mensaje": "¿Y cuánto tengo disponible para usar?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
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
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
  "mensaje": "Ok. ¿Y el saldo de la tarjeta sigue igual que hace un rato?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
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
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
  "mensaje": "Gracias, eso es todo."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-8d70-7622-a28d-aeaf05eae097",
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
  "conversation_id": "conv_01a10b2e-9731-7190-af02-ea161931aa83",
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
  "conversation_id": "conv_01a10b2e-9731-7190-af02-ea161931aa83",
  "mensaje": "Hola, hace unos días me rechazaron un pago en Uber con mi tarjeta terminada en 6873. ¿Qué pasó?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9731-7190-af02-ea161931aa83",
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
  "conversation_id": "conv_01a10b2e-9731-7190-af02-ea161931aa83",
  "mensaje": "¿Entonces mi tarjeta está vencida?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9731-7190-af02-ea161931aa83",
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
  "conversation_id": "conv_01a10b2e-9731-7190-af02-ea161931aa83",
  "mensaje": "No, así está bien. Gracias."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9731-7190-af02-ea161931aa83",
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
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
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
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
  "mensaje": "No reconozco un cobro de Empresa Telefónica en mi tarjeta de crédito terminada en 4950. Quiero reclamarlo."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
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
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
  "mensaje": "Sí, ese."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
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
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
  "mensaje": "No, por ahora solo quiero el reclamo."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
  "reply": "No bloqueé la tarjeta. No puedo determinar si este cobro es válido; los reclamos los revisa un asesor. Un asesor revisará su caso, referencia CASE-ED908D0D6BC0.",
  "state": "HANDED_OFF",
  "language": "es",
  "pending_confirmation": null,
  "case_id": "CASE-ED908D0D6BC0",
  "turn": 3
}
```

`d5-t4` · Message after the handoff is appended to the case (T-38)

```http
POST /chat/mensaje
Authorization: Bearer <customer token>

{
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
  "mensaje": "¿En cuánto tiempo me contactan?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9891-724a-9051-4550c8121ac7",
  "reply": "Agregué su mensaje a su caso, referencia CASE-ED908D0D6BC0. Un asesor lo revisará.",
  "state": "HANDED_OFF",
  "language": "es",
  "pending_confirmation": null,
  "case_id": "CASE-ED908D0D6BC0",
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
  "conversation_id": "conv_01a10b2e-9c34-76b9-81ef-5f48380e30ed",
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
  "conversation_id": "conv_01a10b2e-9c34-76b9-81ef-5f48380e30ed",
  "mensaje": "Oi, qual é o saldo da minha conta poupança?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9c34-76b9-81ef-5f48380e30ed",
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
  "conversation_id": "conv_01a10b2e-9c34-76b9-81ef-5f48380e30ed",
  "mensaje": "E o do cartão de crédito?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9c34-76b9-81ef-5f48380e30ed",
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
  "conversation_id": "conv_01a10b2e-9c34-76b9-81ef-5f48380e30ed",
  "mensaje": "O 7858."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9c34-76b9-81ef-5f48380e30ed",
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
  "conversation_id": "conv_01a10b2e-9c34-76b9-81ef-5f48380e30ed",
  "mensaje": "Obrigado, era isso."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9c34-76b9-81ef-5f48380e30ed",
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
  "sesion_id": "ses_Mm8_hHJ6tan9U7nFAKN-updtq84U4mjC",
  "customer_id": "CLI-JPK27B33SV65",
  "customer_status": "Active",
  "nivel": "L1",
  "idioma": "pt",
  "expira_inactividad_en": "2026-10-05T08:44:27.191321Z",
  "expira_absoluta_en": "2026-10-05T09:29:27.191321Z",
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
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
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
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
  "mensaje": "Oi, perdi meu cartão de crédito. Quero bloquear agora."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
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
  "sesion_id": "ses_Mm8_hHJ6tan9U7nFAKN-updtq84U4mjC"
}

HTTP 201
{
  "sesion_id": "ses_Mm8_hHJ6tan9U7nFAKN-updtq84U4mjC",
  "codigo": "451615",
  "expira_en": "2026-10-05T08:34:27.312929Z",
  "aviso": "IdP de prueba simulado: no es un proveedor de identidad real (POL-AUTH-13)."
}
```

`d2-t2` · Code sent from the verification widget: confirmation prompt

```http
POST /chat/mensaje
Authorization: Bearer <test session token>

{
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
  "codigo_step_up": "451615"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
  "reply": "Identidade confirmada. Vou bloquear o seu cartão de crédito final 8407. Depois do bloqueio ele deixa de funcionar e eu não consigo desbloqueá-lo; só um atendente pode fazer isso. Confirma o bloqueio do cartão final 8407? Responda sim ou não.",
  "state": "AWAIT_CONFIRMATION",
  "language": "pt",
  "pending_confirmation": {
    "card_last4": "8407",
    "card_type": "Tarjeta Crédito",
    "expires_at": "2026-10-05T08:31:27.380801+00:00"
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
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
  "mensaje": "Sim, pode bloquear."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
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
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
  "mensaje": "Não, era só isso, valeu."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-9f17-7ad2-87ea-0566e4d7bd21",
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
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
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
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
  "mensaje": "Hola, ¿cuál es mi saldo?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
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
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
  "mensaje": "La terminada en 0990."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
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
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
  "mensaje": "¿Qué movimientos tuvo esa tarjeta en el último mes?"
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
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
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
  "mensaje": "Gracias, eso es todo."
}

HTTP 200
{
  "conversation_id": "conv_01a10b2e-a0d3-7f87-b478-277cc81a0138",
  "reply": "Con gusto. Hasta luego.",
  "state": "ENDED",
  "language": "es",
  "pending_confirmation": null,
  "case_id": null,
  "turn": 4
}
```
<!-- /example -->
