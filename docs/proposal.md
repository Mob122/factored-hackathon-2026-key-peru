# Propuesta v3.1: Consultas de tarjetas y cuentas

Factored AI & Data Hackathon 2026 | Aldair y Martín | v3.1, 29 de septiembre de 2026 | Reemplaza v1, v2 y v3

Cambios frente a v3 (28 de septiembre): la consulta de saldo quedó aprobada por el equipo y es la intención central del alcance (hallazgo P4 del Día 2); las tools `list_balance_products` y `get_balance` pasan a los contratos congelados; el label nativo de transcripts sale de la sección 6; los clientes `Suspended` o `Closed` solo reciben una transferencia (POL-AUTH-09); cambia el reparto de los escenarios adversos y de `docs/operations.md`.

## 1. Qué vamos a construir

Un asistente de consultas de tarjetas y cuentas, en español y portugués, cuya intención central es la consulta de saldo de tarjetas de crédito y cuentas de ahorro, la única demanda que aparece en los transcripts del dataset (Día 2, P4). Sobre ese núcleo agrega el flujo de tarjetas: estado, transacciones, bloqueo con confirmación y verificación, y transferencia a un humano con un expediente completo cuando el caso lo excede. Solo afirma lo que puede verificar en los datos del cliente.

## 2. Por qué cambiamos de plan

El Día 1 descartó las dos propuestas de v1. Cargo Claro (A) no encontró ninguna de sus cinco causas raíz por encima del ruido del generador. Reclamo sin sorpresas (B) no encontró failure demand medible, los reclamos no se pueden unir a las interacciones, y ni `resolution_days` ni `sla_breached` tienen señal. Crédito tampoco es opción: `credit_score` y el resto de variables predicen la mora con AUC 0.50.

La regla de decisión de v1 asumía que al menos un track tenía señal en sus premisas. Como ninguno la tuvo, elegimos el workflow con la evidencia de motivos de contacto, que es lo que pide el criterio 1 de las bases. Este cambio se hizo después de ver los datos y queda declarado como enmienda en `docs/decision_day1.md`.

## 3. Evidencia que respalda la elección

Transaccional es el principal motivo de contacto: 35% de las interacciones (240,056). Los humanos lo resuelven con FCR de 91.5%, 221 s de atención y unos 120 s de espera. Ese es nuestro baseline del status quo: el asistente debe igualar esa resolución de forma segura y llevar la espera casi a cero.

La demanda que muestran los transcripts es la consulta de saldo. Los 546 textos distintos de los transcripts Transaccional (59,786 transcripts) son consultas de saldo: 50.07% de tarjeta de crédito y 49.93% de cuenta de ahorros; ninguno pregunta por un cargo, un rechazo, una transferencia o un bloqueo (P4, `docs/findings/day2/personas.md`). Por eso el saldo es la intención central. Los transcripts no dicen más: el label `contact_reason` es independiente del texto (P5), así que no podemos afirmar que el 35% Transaccional sean consultas de saldo, solo que es la única demanda escrita que el dataset trae.

El flujo de tarjetas es nuestra extensión, respaldada por P2 (`docs/findings/day1/P2_card_support.md`), no por los transcripts. Las tarjetas, su estado y sus transacciones existen y son consistentes (ninguna transacción pertenece a alguien distinto del titular), y el 31% de los titulares tiene dos o más tarjetas activas, así que "¿cuál tarjeta?" es una ambigüedad real que se resuelve con los últimos 4 dígitos.

## 4. Alcance del workflow

Flujo: autenticación con sesión mock y step-up para acciones; consulta de saldo de tarjetas de crédito y cuentas de ahorro (saldo y límite registrados, con la hora de los datos); identificar la tarjeta o la cuenta (aclarar si hay varias); leer el estado de una tarjeta; listar transacciones recientes de una tarjeta; describir una transacción o su código con una plantilla fija; bloquear una tarjeta (confirmación explícita y verificación releyendo el estado); y transferir a humano con expediente. Las 12 intenciones y sus slots están en `docs/intents.md`.

Los tres casos que exigen las bases: resolución normal (consulta de saldo, consulta de un cargo, bloqueo de tarjeta), ambiguo o fuera de alcance (varias tarjetas o productos, pedido que no cubrimos, crédito disponible) e intervención humana (disputa, desbloqueo, "¿por qué me bloquearon?", cliente con estado `Suspended` o `Closed`).

Lo que el sistema no hace, por decisión explícita: no calcula crédito disponible, pago mínimo ni fecha de pago, porque el diccionario no define el signo ni el significado del saldo de una tarjeta; no da saldos de tarjetas de débito ni de cuentas corrientes, ni movimientos de cuentas; no explica causas de rechazos ni de bloqueos, porque los códigos de respuesta son aleatorios y las tarjetas bloqueadas no tienen historial; no desbloquea tarjetas (siempre va a humano, porque no hay forma de verificar que el bloqueo fue legítimo); no atiende a clientes con estado `Suspended` o `Closed`, que reciben solo una transferencia (POL-AUTH-09); no mueve dinero; y no usa `fraud_score`, que filtra la etiqueta `is_fraud`.

## 5. Dónde va la IA y dónde las reglas

| Componente | Responsable | Por qué |
|---|---|---|
| Entender el mensaje (intención, producto, tarjeta, fecha, monto, comercio) | Clasificador aprendido | Lenguaje variable en español regional y portugués |
| Redactar respuestas | LLM, con PII redaction | Solo parafrasea hechos ya verificados; saldos, transacciones y bloqueos usan plantillas fijas |
| Permisos, sesión, step-up, estado del cliente | Reglas en el servicio | No pueden depender del texto del modelo |
| Bloqueo, confirmación, verificación | Action gateway | Acción con efecto; se reporta solo si se verificó |
| Cuándo aclarar, abstenerse o transferir | Conjuntos conformales + política | Umbral con garantía de cobertura, no un prompt |

## 6. Componente de ML

Clasificador de intención y slots en español y portugués, con conjuntos de predicción conformales: un solo candidato, actuar; varios, pedir aclaración; vacío o demasiado grande, transferir a humano. Taxonomía final de 12 intenciones, slots, guía de etiquetado y hard negatives en `docs/intents.md`.

Labels: utterances generadas por el equipo (tres variantes de español y portugués), declaradas como tales. De los transcripts no se usa ningún campo como label ni como feature: `main_topics` es una copia de `contact_reason` en el 100% de las filas (usarlo filtraría el label) y `detected_intents` solo toma `consulta_general` o nulo, así que no aporta información (P5, `docs/findings/day2/personas.md`). Split por grupo de semilla para que las paráfrasis y traducciones no crucen entre train, calibración y test, portugués evaluado aparte y una muestra validada por humano con kappa. Baselines: reglas, TF-IDF con regresión logística y LLM zero-shot. Métricas: macro-F1, cobertura empírica de los conjuntos, tasa de aclaración y resultados por idioma y variante. Detalle en `docs/eval_plan.md` sección 8.

## 7. Evaluación

Comparamos un agente LLM ingenuo, con las mismas tools pero sin policy engine, contra nuestro sistema, sobre los mismos escenarios held-out con estado oculto, usando pass^k. Reportamos las métricas de las bases: safe automated resolution, containment, escalation quality (transferencias faltantes e innecesarias), unsafe outcomes con conteos y denominadores, p50 y p95 de latencia y costo por caso. Casos adversos: sesión expirada, tarjeta de otro cliente, prompt injection, falla de tool, datos incorrectos o faltantes y ambigüedad multilingüe. Como la actividad real con tarjeta es escasa, las transacciones parecidas para la escena de desambiguación se inyectan como fixture declarado. Plan pre-registrado, definiciones de métricas, metas, costo estimado, tiempo de ejecución y plan de contingencia si se supera el presupuesto: `docs/eval_plan.md` (secciones 1 a 13); formato del reporte: `docs/contracts/eval_report.schema.json`.

## 8. Contratos congelados

| Tool | Entrada | Salida |
|---|---|---|
| `authenticate` | credenciales de prueba | sesión con expiración, nivel L1, idioma preferido y `customer_status` del cliente (POL-AUTH-09) |
| `step_up` | sesión, tarjeta, acción, código de un solo uso | nivel L2, ligado a esa tarjeta y acción, con expiración |
| `list_balance_products` | sesión | productos con saldo consultable: tarjetas de crédito y cuentas de ahorro no cerradas (id interno, tipo, últimos 4, estado) |
| `get_balance` | sesión, producto | tipo, últimos 4, estado, moneda, saldo, límite (solo crédito; puede ser nulo) y `as_of` (fin de la carga diaria de gold) |
| `list_cards` | sesión | id interno, últimos 4, tipo, estado |
| `get_card_status` | sesión, tarjeta | últimos 4, tipo, estado actual |
| `list_transactions` | sesión, tarjeta, rango y filtros | transacciones del titular |
| `describe_transaction` | sesión, transacción | campos de la transacción y plantillas que aplican |
| `block_card` | sesión step-up, tarjeta, token de confirmación | aceptación de la solicitud (`accepted`, `request_id`). El action gateway verifica el resultado releyendo `get_card_status`; solo un estado `Blocked` releído se reporta como hecho |
| `open_handoff` | sesión, expediente | id del caso |

Las tools de saldo leen la tabla gold `balance_products` (`gold-0.2`).

También quedan congelados: esquemas de gold (`docs/contracts/gold_tables.md`, `gold-0.2`), política de refresco (`docs/contracts/freshness_policy.md`, `fresh-0.2`), máquina de estados (`docs/contracts/state_machine.md`, `sm-0.3`), taxonomía de intenciones (`docs/intents.md`, `intents-1.0`), eventos del audit log (`docs/contracts/audit_log.md`, `audit-0.2`) y formato JSON del eval report (`docs/contracts/eval_report.schema.json`, `eval-report-0.2`). La política escrita es `docs/policy_cards.md` (SINTÉTICA, `cards-synthetic-0.4`).

## 9. Reparto

Aldair: tablas gold (clientes, tarjetas, transacciones, productos con saldo), contratos y calidad de datos, políticas como código, taxonomía de intenciones y dataset de utterances, clasificador con conformal, todos los escenarios (incluidas las plantillas adversas de sesión expirada, acceso no autorizado, prompt injection, falla de tool y ambigüedad multilingüe), customer simulator, evaluación, data card, model cards y el borrador de `docs/operations.md` (controles de acceso, retención, señales de monitoreo y trabajo pendiente antes del despliegue).

Martín: mock identity con step-up, mock bank sobre gold, orchestrator y state machine, action gateway y el manejo de los casos adversos en el sistema, chat y case inbox, audit log, tracing, bounded retries, safe fallback, deploy, y la sección de capacidad de `docs/operations.md` con la prueba de carga.

Compartido: la state machine (Aldair la especifica, Martín la implementa), la revisión de `docs/operations.md`, la demo y el ensayo.

## 10. Plan

| Día | Aldair | Martín | Checkpoint |
|---|---|---|---|
| 2 | Gold, contratos, P5, taxonomía de intents y guía de etiquetado, borrador de `docs/operations.md` | Identity, mock bank, contratos v1 | Contratos congelados |
| 3 | Políticas como código, utterances semilla, baselines del clasificador, tabla `balance_products` | State machine, gateway, case store | Happy path en terminal |
| 4 | Dataset etiquetado es/pt, 40 escenarios (incluidos los adversos) y grader, muestra de kappa | Chat e inbox conectados | End-to-end en español |
| 5 | Clasificador con conformal, simulator, set en portugués, corridas dev y reproyección de costo | Tracing, audit log, export del expediente | Portugués funcionando |
| 6 | Corrida completa contra el agente ingenuo | Manejo de los casos adversos | Primeros resultados |
| 7 | Error analysis, pass^k, resultados por idioma y segmento | Fixes, p50 y p95, clean-clone test, capacidad y prueba de carga en `docs/operations.md` | Feature freeze |
| 8 | Data card, model cards, write-up | Deploy, README, grabación | Entrega |

## 11. Limitaciones que declaramos

Los datos son sintéticos y casi no tienen estructura entre filas, así que los resultados describen el generador y no un banco real. Los transcripts solo contienen dos aperturas de consulta de saldo y su `contact_reason` es independiente del texto, así que no sabemos de qué trataban los contactos Transaccional. El saldo no tiene fecha propia (se muestra con la hora de la carga de gold) y el diccionario no define su significado para tarjetas de crédito: 1.27% de las tarjetas con límite tienen un saldo mayor al límite y 5.05% no tienen límite registrado. Los códigos de rechazo son aleatorios y las tarjetas bloqueadas no tienen historial. La baja actividad por cliente hace que la ambigüedad de transacciones sea rara en datos reales. El portugués y los labels del clasificador son generados por el equipo. MXN no aparece en los datos y las fechas de vigencia de las tarjetas son inconsistentes. Cualquier ahorro de negocio se presenta como proyección, no como resultado medido. Los resultados negativos del Día 1 (A, B y crédito) se reportan como evidencia del proceso.
