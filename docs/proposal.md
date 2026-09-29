# Propuesta v3: Consultas de tarjetas y transacciones

Factored AI & Data Hackathon 2026 | Aldair y Martín | v3, 28 de septiembre de 2026; revisión de consistencia del 29 de septiembre (secciones 6 a 8, sin cambio de alcance) | Reemplaza v1 y v2

## 1. Qué vamos a construir

Un asistente de consultas de tarjetas y transacciones, en español y portugués, que solo afirma lo que puede verificar en los datos del cliente, bloquea tarjetas con confirmación y verificación, y transfiere a un humano con un expediente completo cuando el caso lo excede.

## 2. Por qué cambiamos de plan

El Día 1 descartó las dos propuestas de v1. Cargo Claro (A) no encontró ninguna de sus cinco causas raíz por encima del ruido del generador. Reclamo sin sorpresas (B) no encontró failure demand medible, los reclamos no se pueden unir a las interacciones, y ni `resolution_days` ni `sla_breached` tienen señal. Crédito tampoco es opción: `credit_score` y el resto de variables predicen la mora con AUC 0.50.

La regla de decisión de v1 asumía que al menos un track tenía señal en sus premisas. Como ninguno la tuvo, elegimos el workflow con la evidencia de motivos de contacto, que es lo que pide el criterio 1 de las bases. Este cambio se hizo después de ver los datos y queda declarado como enmienda en `docs/decision_day1.md`.

## 3. Evidencia que respalda la elección

Transaccional es el principal motivo de contacto: 35% de las interacciones (240,056). Los humanos lo resuelven con FCR de 91.5%, 221 s de atención y unos 120 s de espera. Ese es nuestro baseline del status quo: el asistente debe igualar esa resolución de forma segura y llevar la espera casi a cero.

Las tarjetas, su estado y sus transacciones existen y son consistentes (ninguna transacción pertenece a alguien distinto del titular). El 31% de los titulares tiene dos o más tarjetas activas, así que "¿cuál tarjeta?" es una ambigüedad real que se resuelve con los últimos 4 dígitos.

## 4. Alcance del workflow

Flujo: autenticación con sesión mock y step-up para acciones, identificar la tarjeta (aclarar si tiene varias), leer su estado, listar transacciones recientes, describir una transacción o su código con una plantilla fija, bloquear la tarjeta (confirmación explícita y verificación releyendo el estado) y transferir a humano con expediente.

Los tres casos que exigen las bases: resolución normal (consulta de un cargo, bloqueo de tarjeta), ambiguo o fuera de alcance (varias tarjetas, pedido que no cubrimos) e intervención humana (disputa, desbloqueo, "¿por qué me bloquearon?").

Lo que el sistema no hace, por decisión explícita: no explica causas de rechazos ni de bloqueos, porque los códigos de respuesta son aleatorios y las tarjetas bloqueadas no tienen historial; no desbloquea tarjetas (siempre va a humano, porque no hay forma de verificar que el bloqueo fue legítimo); no mueve dinero; y no usa `fraud_score`, que filtra la etiqueta `is_fraud`.

## 5. Dónde va la IA y dónde las reglas

| Componente | Responsable | Por qué |
|---|---|---|
| Entender el mensaje (intención, tarjeta, fecha, monto, comercio) | Clasificador aprendido | Lenguaje variable en español regional y portugués |
| Redactar respuestas | LLM, con PII redaction | Solo parafrasea hechos ya verificados |
| Permisos, sesión, step-up | Reglas en el servicio | No pueden depender del texto del modelo |
| Bloqueo, confirmación, verificación | Action gateway | Acción con efecto; se reporta solo si se verificó |
| Cuándo aclarar, abstenerse o transferir | Conjuntos conformales + política | Umbral con garantía de cobertura, no un prompt |

## 6. Componente de ML

Clasificador de intención y slots en español y portugués, con conjuntos de predicción conformales: un solo candidato, actuar; varios, pedir aclaración; vacío o demasiado grande, transferir a humano.

Labels: utterances generadas por el equipo (tres variantes de español y portugués), declaradas como tales. El label nativo de transcripts se descartó: la verificación P5 lo refutó (`docs/findings/day2/personas.md`). Split por grupo de semilla para que las paráfrasis y traducciones no crucen entre train, calibración y test, portugués evaluado aparte y una muestra validada por humano con kappa. Baselines: reglas, TF-IDF con regresión logística y LLM zero-shot. Métricas: macro-F1, cobertura empírica de los conjuntos, tasa de aclaración y resultados por idioma y variante. Detalle en `docs/eval_plan.md` sección 8.

## 7. Evaluación

Comparamos un agente LLM ingenuo, con las mismas tools pero sin policy engine, contra nuestro sistema, sobre los mismos escenarios held-out con estado oculto, usando pass^k. Reportamos las métricas de las bases: safe automated resolution, containment, escalation quality (transferencias faltantes e innecesarias), unsafe outcomes con conteos y denominadores, p50 y p95 de latencia y costo por caso. Casos adversos: sesión expirada, tarjeta de otro cliente, prompt injection, falla de tool, datos incorrectos o faltantes y ambigüedad multilingüe. Como la actividad real con tarjeta es escasa, las transacciones parecidas para la escena de desambiguación se inyectan como fixture declarado. Plan pre-registrado, definiciones de métricas y metas: `docs/eval_plan.md`; formato del reporte: `docs/contracts/eval_report.schema.json`.

## 8. Contratos a congelar hoy

| Tool | Entrada | Salida |
|---|---|---|
| `authenticate` | credenciales de prueba | sesión con expiración, nivel L1 e idioma preferido |
| `step_up` | sesión, tarjeta, acción, código de un solo uso | nivel L2, ligado a esa tarjeta y acción, con expiración |
| `list_cards` | sesión | id interno, últimos 4, tipo, estado |
| `get_card_status` | sesión, tarjeta | últimos 4, tipo, estado actual |
| `list_transactions` | sesión, tarjeta, rango y filtros | transacciones del titular |
| `describe_transaction` | sesión, transacción | campos de la transacción y plantillas que aplican |
| `block_card` | sesión step-up, tarjeta, token de confirmación | aceptación de la solicitud (`accepted`, `request_id`). El action gateway verifica el resultado releyendo `get_card_status`; solo un estado `Blocked` releído se reporta como hecho |
| `open_handoff` | sesión, expediente | id del caso |
| `list_balance_products` | sesión | productos con saldo consultable: tarjetas de crédito y cuentas de ahorro (política 0.2, **pendiente de aprobación de Martín**) |
| `get_balance` | sesión, producto | saldo, límite (solo crédito), moneda y `as_of` (política 0.2, **pendiente de aprobación de Martín**) |

Las dos últimas tools vienen de la consulta de saldo que la política `cards-synthetic-0.2` agregó a partir del hallazgo P4 (los transcripts solo contienen consultas de saldo). No están en el alcance de la sección 4 hasta que el equipo las apruebe; ver la primera brecha abierta de `docs/requirements_matrix.md`.

También se congelan hoy: esquemas de gold (`docs/contracts/gold_tables.md`), política de refresco (`docs/contracts/freshness_policy.md`), máquina de estados (`docs/contracts/state_machine.md`), eventos del audit log (`docs/contracts/audit_log.md`) y formato JSON del eval report (`docs/contracts/eval_report.schema.json`). La política escrita es `docs/policy_cards.md` (SINTÉTICA).

## 9. Reparto

Aldair: tablas gold (clientes, tarjetas, transacciones), contratos y calidad de datos, políticas como código, dataset de utterances, clasificador con conformal, escenarios, customer simulator, evaluación, data card y model cards.

Martín: mock identity con step-up, mock bank sobre gold, orchestrator y state machine, action gateway, chat y case inbox, audit log, tracing, bounded retries, safe fallback y deploy.

Compartido: la state machine (Aldair la especifica, Martín la implementa), la demo y el ensayo.

## 10. Plan

| Día | Aldair | Martín | Checkpoint |
|---|---|---|---|
| 2 | Gold, contratos, P5, taxonomía de intents y guía de etiquetado | Identity, mock bank, contratos v1 | Contratos congelados |
| 3 | Políticas como código, utterances semilla, baselines del clasificador | State machine, gateway, case store | Happy path en terminal |
| 4 | Dataset etiquetado es/pt, 40 escenarios y grader | Chat e inbox conectados | End-to-end en español |
| 5 | Clasificador con conformal, simulator, set en portugués | Tracing, audit log, export del expediente | Portugués funcionando |
| 6 | Corrida completa contra el agente ingenuo | Casos adversos | Primeros resultados |
| 7 | Error analysis, pass^k, resultados por idioma y segmento | Fixes, p50 y p95, clean-clone test | Feature freeze |
| 8 | Data card, model cards, write-up | Deploy, README, grabación | Entrega |

## 11. Limitaciones que declaramos

Los datos son sintéticos y casi no tienen estructura entre filas, así que los resultados describen el generador y no un banco real. Los códigos de rechazo son aleatorios y las tarjetas bloqueadas no tienen historial. La baja actividad por cliente hace que la ambigüedad de transacciones sea rara en datos reales. El portugués y los labels del clasificador son generados por el equipo. MXN no aparece en los datos y las fechas de vigencia de las tarjetas son inconsistentes. Cualquier ahorro de negocio se presenta como proyección, no como resultado medido. Los resultados negativos del Día 1 (A, B y crédito) se reportan como evidencia del proceso.
