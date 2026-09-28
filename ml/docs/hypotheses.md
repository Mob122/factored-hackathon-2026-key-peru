# 5. Hipótesis y query plan del Día 1

| # | Hipótesis | Query o prueba | Si falla |
|---|-----------|----------------|-----------|
| C1 | Calidad real frente a la declarada | Duplicados, nulos y huérfanos por tabla; duplicado de PK frente a contenido | Se documenta y se ajustan contracts |
| A1 | Cargos no reconocidos son demanda relevante | `contact_reason` y categorías de complaints por país, canal y año | Descartar A |
| A2 | Hay reclamos por cargos cerrados como cargo válido | Texto de `resolution` y `compensation_granted` en esa categoría | Tesis solo con evidencia de industria |
| A3 | Existen preautorizaciones, moneda extranjera y dobles cobros | Pares Pending a Reversed; currency distinta a la local; mismo comercio y monto en minutos | Detectores con fixtures declarados |
| A4 | Hay recurrencia y estructura temporal por cliente | Periodicidad cercana a 30 días por `product_id` y merchant; next-event contra frecuencias | Se cae el sequence model; queda LightGBM |
| A5 | `fraud_score` no filtra a `is_fraud` | AUC de `fraud_score` solo | Se excluye como baseline |
| B1 | Hay failure demand medible | Contactos del mismo cliente entre `creation_date` y `closing_date`; `contact_reason` de seguimiento; `requires_followup` | Descartar B |
| B2 | `resolution_days` es predecible | Cox o gradient boosting survival con features de ingreso; C-index | Solo seguimiento, sin ETA |
| B3 | Hay volumen en canal Regulator y SLA incumplido | Conteo por `reception_channel` y `sla_breached`; orden temporal con contactos previos | Se usa solo el riesgo de SLA |
| B4 | `complaints` se une a `interacciones` | `origin_interaction_id` y join por cliente y fecha; tasa de match | Limitación declarada |