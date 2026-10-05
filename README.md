# Factored AI & Data Hackathon 2026 – key-peru

Card and account inquiries assistant (plan: [docs/proposal.md](docs/proposal.md)). Sub-projects: [ml/](ml/), [backend/](backend/), [frontend/](frontend/).

Docs consistency check: `python tools/check_docs.py` (no arguments; exits non-zero on any broken rule ID or cross-reference in docs/).

## Run the agent locally

You need Python 3.11, Node.js `^20.19` or `>=22.12` with pnpm (for the frontend), and
`ml/data/demo_gold.zip`. The zip is never in git: get it from the team, or build it with
`ml/scripts/make_demo_gold.py` if you have the full gold. The commands are for bash (Git Bash on Windows).

1. Create the backend environment and `backend/.env`:

   ```sh
   cd backend
   python -m venv .venv
   source .venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
   python -m pip install --upgrade pip  # the pip bundled with Python 3.11.0 cannot read scikit-learn 1.9's metadata
   pip install -r requirements.txt
   cp .env.example .env
   ```

   In `backend/.env`:
   - Keep `LLM_MODE=mock`, so no LLM is called and no API key is needed.
   - Keep `GOLD_DIR=../ml/data/demo_gold` and `RELOJ_SIMULADO=2026-06-18T10:00:00`, the clock of the golden
     conversations.
   - Replace `SECRET_KEY` and `AUDIT_KEY` with random values:
     `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   - Set `SEED_PASSWORD` to a password of 12 or more characters; every test user gets it.
   - Set `CARD_HASH_KEY` to the team's key, which only the ownership check of a full card number typed in
     the chat (golden dialogue 7) needs. With any other value, everything else works.

2. Unzip the demo gold into `GOLD_DIR`, create the test users, and start the API:

   ```sh
   python -m zipfile -e ../ml/data/demo_gold.zip ../ml/data/demo_gold
   python -m scripts.sembrar_usuarios
   uvicorn main:app --reload --port 8000
   ```

   The seed creates one customer per golden persona (`cli-<customer id in lowercase>@clientes.keyperu.example`),
   plus `agente@keyperu.example` and `jurado@keyperu.example`, all with `SEED_PASSWORD`.

3. In another terminal, sign in with each role. Each sign-in returns the token as a JSON string:

   ```sh
   API=http://localhost:8000
   PASS='<your SEED_PASSWORD>'
   token() { curl -s -X POST $API/autenticacion/iniciar-sesion -H 'Content-Type: application/json' \
     -d "{\"correo_electronico\": \"$1\", \"password\": \"$PASS\"}" | tr -d '"'; }

   CLIENTE=$(token cli-sqjocedjjncz@clientes.keyperu.example)
   curl -s $API/autenticacion/mi-perfil -H "Authorization: Bearer $CLIENTE"

   AGENTE=$(token agente@keyperu.example)
   curl -s $API/casos -H "Authorization: Bearer $AGENTE"

   JURADO=$(token jurado@keyperu.example)
   curl -s "$API/identidad/clientes?pais=Colombia&tamano=3" -H "Authorization: Bearer $JURADO"
   ```

4. As the jurado, start a test session for any customer in the gold (use a `customer_id` from the search),
   then chat as that customer:

   ```sh
   curl -s -X POST $API/identidad/sesion-prueba -H "Authorization: Bearer $JURADO" \
     -H 'Content-Type: application/json' -d '{"customer_id": "CLI-0N6WSFJ54FF2"}'
   ```

5. Try the terminal chat (`/otp` asks the test IdP for a step-up code, `/audit` shows the audit trail):

   ```sh
   python cli.py --usuario cli-sqjocedjjncz@clientes.keyperu.example
   python cli.py --jurado jurado@keyperu.example --cliente CLI-0N6WSFJ54FF2
   ```

6. Point the frontend at the API and start it (Node `^20.19` or `>=22.12`; Vite 8 does not run on older Node):

   ```sh
   cd ../frontend
   cp .env.example .env                  # BACKEND_URL=http://localhost:8000
   pnpm install
   pnpm dev
   ```

7. Open `http://localhost:5173` and sign in with the seeded users (password `SEED_PASSWORD`):
   - **A customer**, for example `cli-5b9vscp2gsml@clientes.keyperu.example` (golden dialogue 1). *Mis tarjetas*,
     *Transacciones* and *Mis casos* show their gold data. In *Consultas*:
     - ask "¿Cuál es mi saldo?", or open a declined transaction and press "¿Por qué fue rechazada?";
     - block a card from *Mis tarjetas*. When the chat asks for the code, press "Recibir el código por SMS
       simulado" (only with `ENV=development`), then answer "Sí".
   - **`agente@keyperu.example`** sees the case inbox, each case file and its audit trail.
   - **`jurado@keyperu.example`** has no web console yet: use the CLI (step 5).

The API the frontend uses is in [docs/contracts/chat_api.md](docs/contracts/chat_api.md), with captured
examples and the OpenAPI file.

### Deploy

- **Full gold on the server:** the server needs the full gold, never in git. Copy
  `ml/data/03_primary/gold/` (about 82 MB) to the server and point `GOLD_DIR` at it. The demo gold has only
  211 customers.
- **Behind the jurado login:**
  - Run with `ENV` unset or `production`, so open registration is closed.
  - Seed the users with a strong `SEED_PASSWORD` and give it only to the jury. The test IdP
    (`/identidad/*`) only works for the `jurado` role.
- **Secrets in the server environment:** `SECRET_KEY`, `AUDIT_KEY`, the team's `CARD_HASH_KEY`, and
  `OPENAI_API_KEY` if `LLM_MODE=openai`. They are never committed.
- **Database and TLS:** with `ENV` other than `development`, tables are not created at startup, so create
  them once (for example by running the seed script). Serve the frontend over HTTPS: its cookie is
  `secure`.
