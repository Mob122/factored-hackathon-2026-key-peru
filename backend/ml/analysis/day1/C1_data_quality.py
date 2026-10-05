"""C1 - declared vs real data quality, over the 13 tables in data/02_intermediate.

Checks, per table:
  (a) full-row and PK duplicates (and, for PK duplicates, which columns differ),
      plus near-duplicates on business keys;
  (b) null rate per column vs the ~5% declared, NOT NULL violations, blank tokens,
      and whether each column's nulls are structural (explained by another column)
      or random, with a binomial dispersion test as the null baseline;
  (c) orphan rate for every FK in the data dictionary, plus cross-table consistency;
  (d) late arrivals: process_date minus event date;
  (e) schema evolution: raw headers and raw value formats per source file, and
      categorical values appearing or disappearing over time.
It ends with a proposed data contract per table.

Outputs:
  docs/findings/day1/C1.md                 (committed report)
  docs/findings/day1/C1_contracts.json     (machine-readable contracts)
  data/08_reporting/day1/C1.md             (copy of the report)
  data/08_reporting/day1/FINDINGS.md and docs/findings/day1/FINDINGS.md (C1 line)

Run from ml/:  .venv/Scripts/python analysis/day1/C1_data_quality.py
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import date
from pathlib import Path

import duckdb
import numpy as np

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
INTER = ML / "data" / "02_intermediate"
RAW = ML / "data" / "01_raw"
OUT_DATA = ML / "data" / "08_reporting" / "day1"
OUT_DOCS = REPO / "docs" / "findings" / "day1"

DATA_START, DATA_END = date(2023, 6, 17), date(2026, 6, 17)
DECLARED_DUP_RATE = 0.02
DECLARED_NULL_RATE = 0.05
LOW_CARD = 40  # max distinct values for a column to be treated as categorical
MIN_GROUP = 30  # min rows for a group to count as "always null"
# Tables whose process_date is inherited from the linked interaction
PARENT_PROCESS_DATE = {"call_transcripts", "satisfaction_surveys"}
SEED = 42

# --------------------------------------------------------------------------
# Data dictionary metadata (docs/data_dictionary.pdf)
# --------------------------------------------------------------------------
TABLES: dict[str, dict] = {
    "customers": dict(
        kind="dimension", declared_rows=150_000, pk=["customer_id"],
        unique=["document_number"],
        not_null=["customer_id", "document_number", "document_type", "first_name",
                  "last_name", "date_of_birth", "city", "state", "country", "segment",
                  "registration_date", "registration_branch_id", "customer_status",
                  "last_updated", "accepts_marketing"],
        enums=dict(document_type=["DNI", "CURP", "CC", "CE", "Passport"],
                   gender=["M", "F", "O"],
                   country=["Mexico", "Colombia", "Argentina"],
                   detected_accent=["mexican", "colombian", "argentine", "neutral"],
                   segment=["Premium", "Plus", "Basic", "Student"],
                   customer_status=["Active", "Inactive", "Suspended", "Closed"]),
        ranges=dict(credit_score=(300, 850)),
        business_keys=[["first_name", "last_name", "date_of_birth"]],
    ),
    "products": dict(
        kind="dimension", declared_rows=400_000, pk=["product_id"],
        unique=["product_number"],
        not_null=["product_id", "customer_id", "product_type", "product_number",
                  "currency", "current_balance", "opening_date", "opening_branch_id",
                  "product_status", "opening_channel", "has_linked_app", "last_updated"],
        enums=dict(currency=["MXN", "COP", "ARS", "USD"],
                   product_status=["Active", "Blocked", "Closed", "Suspended"],
                   opening_channel=["Branch", "Web", "App", "Call Center"]),
        ranges={},
        business_keys=[],
    ),
    "branches": dict(
        kind="dimension", declared_rows=350, pk=["branch_id"], unique=["branch_code"],
        not_null=["branch_id", "branch_code", "branch_name", "branch_type", "address",
                  "city", "state", "country", "geographic_zone", "phone", "opening_time",
                  "closing_time", "has_atms", "has_teller_windows",
                  "branch_opening_date", "branch_status"],
        enums=dict(branch_type=["Main", "Express", "Premium", "Corporate"],
                   geographic_zone=["Urban", "Suburban", "Rural"],
                   branch_status=["Active", "Temporarily Closed", "Closed"]),
        ranges={},
        business_keys=[["branch_name"]],
    ),
    "service_agents": dict(
        kind="dimension", declared_rows=1_200, pk=["agent_id"], unique=["employee_code"],
        not_null=["agent_id", "employee_code", "first_name", "last_name", "email",
                  "native_accent", "country_of_origin", "agent_type",
                  "experience_level", "languages", "hire_date", "agent_status",
                  "work_shift"],
        enums=dict(native_accent=["mexican", "colombian", "argentine"],
                   agent_type=["Phone", "In-Person", "Digital", "Hybrid"],
                   experience_level=["Junior", "Mid-Senior", "Senior", "Specialist"],
                   agent_status=["Active", "Vacation", "Leave", "Inactive"],
                   work_shift=["Morning", "Afternoon", "Night", "Rotating"]),
        ranges=dict(avg_csat=(1, 5)),
        business_keys=[["email"]],
    ),
    "marketing_campaigns": dict(
        kind="dimension", declared_rows=200, pk=["campaign_id"], unique=[],
        not_null=["campaign_id", "campaign_name", "campaign_type", "campaign_objective",
                  "start_date", "end_date", "campaign_status"],
        enums=dict(campaign_type=["Email", "SMS", "Push", "WhatsApp", "Voice", "Mix"],
                   campaign_objective=["Acquisition", "Retention", "Cross-sell",
                                       "Up-sell", "Reactivation"],
                   campaign_status=["Planned", "Active", "Paused", "Completed"]),
        ranges=dict(expected_conversion_rate=(0, 100)),
        business_keys=[["campaign_name"]],
    ),
    "daily_exchange_rates": dict(
        kind="reference", declared_rows=3_000,
        pk=["date", "source_currency", "target_currency"], unique=[],
        not_null=["date", "source_currency", "target_currency", "exchange_rate"],
        enums=dict(source_currency=["MXN", "COP", "ARS", "USD"],
                   target_currency=["MXN", "COP", "ARS", "USD"]),
        ranges={},
        business_keys=[],
    ),
    "transactions": dict(
        kind="fact", declared_rows=5_000_000, pk=["transaction_id"], unique=[],
        event_ts="transaction_date", group_col="channel",
        not_null=["transaction_id", "transaction_date", "process_date", "product_id",
                  "customer_id", "transaction_type", "amount", "currency", "channel",
                  "transaction_country", "transaction_status", "is_fraud"],
        enums=dict(currency=["MXN", "COP", "ARS", "USD"],
                   channel=["ATM", "Branch", "Web", "App", "POS", "Transfer"],
                   transaction_status=["Approved", "Declined", "Pending", "Reversed"]),
        ranges=dict(fraud_score=(0, 100)),
        business_keys=[["customer_id", "product_id", "transaction_date", "amount"]],
    ),
    "call_center_interactions": dict(
        kind="fact", declared_rows=800_000, pk=["interaction_id"], unique=[],
        event_ts="interaction_date", group_col="channel",
        not_null=["interaction_id", "interaction_date", "process_date", "customer_id",
                  "interaction_type", "channel", "contact_reason", "reason_category",
                  "requires_followup", "was_escalated", "has_transcript",
                  "has_recording"],
        enums=dict(interaction_type=["Inbound Call", "Outbound Call", "Chat", "Email",
                                     "Video"],
                   channel=["Phone", "Web Chat", "WhatsApp", "Email", "App"],
                   detected_sentiment=["Positive", "Neutral", "Negative",
                                       "Very Negative"]),
        ranges=dict(sentiment_score=(-1, 1), duration_seconds=(0, None),
                    wait_time_seconds=(0, None)),
        business_keys=[["customer_id", "interaction_date"]],
    ),
    "call_transcripts": dict(
        kind="fact", declared_rows=200_000, pk=["transcript_id"], unique=[],
        event_ts=None, group_col="audio_quality",
        not_null=["transcript_id", "interaction_id", "process_date", "customer_id",
                  "agent_id", "full_text", "detected_language", "transcription_model",
                  "duration_seconds"],
        enums=dict(audio_quality=["High", "Medium", "Low"]),
        notes=["duration_seconds is declared NOT NULL but is null exactly when the linked "
               "interaction is Chat or Email; otherwise it equals "
               "call_center_interactions.duration_seconds. Contract: nullable, and must "
               "equal the interaction's value."],
        ranges=dict(accent_confidence=(0, 1), duration_seconds=(0, None)),
        business_keys=[["interaction_id"]],
    ),
    "satisfaction_surveys": dict(
        kind="fact", declared_rows=250_000, pk=["survey_id"], unique=[],
        event_ts="survey_date", group_col="send_channel",
        not_null=["survey_id", "survey_date", "process_date", "customer_id",
                  "survey_type", "send_channel", "main_score"],
        enums=dict(survey_type=["CSAT", "NPS", "CES"],
                   send_channel=["Email", "SMS", "IVR", "App", "Web"],
                   nps_category=["Promoter", "Passive", "Detractor"]),
        ranges=dict(main_score=(0, 10), question_1_response=(1, 5),
                    question_2_response=(1, 5), question_3_response=(1, 5)),
        business_keys=[["interaction_id", "survey_type"]],
    ),
    "digital_events": dict(
        kind="fact", declared_rows=10_000_000, pk=["event_id"], unique=[],
        event_ts="event_date", group_col="channel",
        not_null=["event_id", "event_date", "process_date", "session_id", "event_type",
                  "event_category", "channel", "is_mobile"],
        enums=dict(channel=["Android App", "iOS App", "Desktop Web", "Mobile Web"],
                   platform=["Android", "iOS", "Windows", "MacOS", "Linux"]),
        ranges=dict(duration_seconds=(0, None)),
        business_keys=[["session_id", "event_date", "event_type"]],
    ),
    "complaints": dict(
        kind="fact", declared_rows=80_000, pk=["complaint_id"], unique=[],
        event_ts="creation_date", group_col="reception_channel",
        not_null=["complaint_id", "creation_date", "process_date", "customer_id",
                  "case_type", "category", "reception_channel", "description",
                  "priority", "status", "sla_breached", "is_repeat_complainer"],
        enums=dict(case_type=["Complaint", "Claim", "Request", "Suggestion"],
                   reception_channel=["Call Center", "Email", "Web", "App", "Branch",
                                      "Regulator"],
                   currency=["MXN", "COP", "ARS", "USD"],
                   priority=["Low", "Medium", "High", "Critical"],
                   status=["Open", "In Process", "Escalated", "Resolved", "Closed",
                           "Rejected"]),
        ranges=dict(resolution_satisfaction=(1, 5), resolution_days=(0, None)),
        business_keys=[["customer_id", "creation_date"]],
    ),
    "campaign_sends": dict(
        kind="fact", declared_rows=2_000_000, pk=["send_id"], unique=[],
        event_ts="send_date", group_col="send_channel",
        not_null=["send_id", "send_date", "process_date", "campaign_id", "customer_id",
                  "send_channel", "send_status", "was_delivered", "had_conversion"],
        enums=dict(send_channel=["Email", "SMS", "Push", "WhatsApp", "Voice"],
                   send_status=["Sent", "Failed", "Bounced", "Blocked"]),
        ranges=dict(click_count=(0, None)),
        business_keys=[["campaign_id", "customer_id", "send_date"]],
    ),
}

FKS = [  # (child table, child column, parent table, parent column)
    ("products", "customer_id", "customers", "customer_id"),
    ("transactions", "customer_id", "customers", "customer_id"),
    ("call_center_interactions", "customer_id", "customers", "customer_id"),
    ("call_transcripts", "customer_id", "customers", "customer_id"),
    ("satisfaction_surveys", "customer_id", "customers", "customer_id"),
    ("digital_events", "customer_id", "customers", "customer_id"),
    ("complaints", "customer_id", "customers", "customer_id"),
    ("campaign_sends", "customer_id", "customers", "customer_id"),
    ("customers", "registration_branch_id", "branches", "branch_id"),
    ("products", "opening_branch_id", "branches", "branch_id"),
    ("service_agents", "assigned_branch_id", "branches", "branch_id"),
    ("transactions", "branch_id", "branches", "branch_id"),
    ("complaints", "related_branch_id", "branches", "branch_id"),
    ("call_center_interactions", "agent_id", "service_agents", "agent_id"),
    ("call_transcripts", "agent_id", "service_agents", "agent_id"),
    ("satisfaction_surveys", "agent_id", "service_agents", "agent_id"),
    ("complaints", "assigned_agent_id", "service_agents", "agent_id"),
    ("transactions", "product_id", "products", "product_id"),
    ("digital_events", "product_id", "products", "product_id"),
    ("complaints", "affected_product_id", "products", "product_id"),
    ("campaign_sends", "campaign_id", "marketing_campaigns", "campaign_id"),
    ("call_transcripts", "interaction_id", "call_center_interactions", "interaction_id"),
    ("satisfaction_surveys", "interaction_id", "call_center_interactions",
     "interaction_id"),
    ("complaints", "origin_interaction_id", "call_center_interactions",
     "interaction_id"),
]

# Cross-table consistency: rows whose linked parent exists but disagrees.
# (rule, child, child join column, parent, parent key, violation predicate on c./p.)
# Each rule is also evaluated against a shuffled parent (every child row linked to a
# random parent row) as the null baseline: if observed ~ shuffled, the generator
# does not model the relationship.
CONSISTENCY = [
    ("call_transcripts.customer_id = interaction.customer_id", "call_transcripts",
     "interaction_id", "call_center_interactions", "interaction_id",
     "c.customer_id IS DISTINCT FROM p.customer_id"),
    ("call_transcripts.agent_id = interaction.agent_id", "call_transcripts",
     "interaction_id", "call_center_interactions", "interaction_id",
     "p.agent_id IS NOT NULL AND c.agent_id IS DISTINCT FROM p.agent_id"),
    ("call_transcripts.duration_seconds = interaction.duration_seconds",
     "call_transcripts", "interaction_id", "call_center_interactions", "interaction_id",
     "c.duration_seconds IS DISTINCT FROM p.duration_seconds"),
    ("call_transcripts.process_date = interaction.process_date", "call_transcripts",
     "interaction_id", "call_center_interactions", "interaction_id",
     "c.process_date <> p.process_date"),
    ("satisfaction_surveys.customer_id = interaction.customer_id", "satisfaction_surveys",
     "interaction_id", "call_center_interactions", "interaction_id",
     "c.customer_id IS DISTINCT FROM p.customer_id"),
    ("satisfaction_surveys.agent_id = interaction.agent_id", "satisfaction_surveys",
     "interaction_id", "call_center_interactions", "interaction_id",
     "c.agent_id IS NOT NULL AND p.agent_id IS NOT NULL AND c.agent_id <> p.agent_id"),
    ("satisfaction_surveys.survey_date >= interaction.interaction_date",
     "satisfaction_surveys", "interaction_id", "call_center_interactions",
     "interaction_id", "c.survey_date < p.interaction_date"),
    ("satisfaction_surveys.process_date = interaction.process_date",
     "satisfaction_surveys", "interaction_id", "call_center_interactions",
     "interaction_id", "c.process_date <> p.process_date"),
    ("transactions.customer_id = owner of product_id", "transactions", "product_id",
     "products", "product_id", "c.customer_id IS DISTINCT FROM p.customer_id"),
    ("transactions.currency = product.currency", "transactions", "product_id",
     "products", "product_id", "c.currency IS DISTINCT FROM p.currency"),
    ("transactions.transaction_date >= product.opening_date", "transactions",
     "product_id", "products", "product_id",
     "CAST(c.transaction_date AS DATE) < p.opening_date"),
    ("complaints.customer_id = owner of affected_product_id", "complaints",
     "affected_product_id", "products", "product_id",
     "c.customer_id IS DISTINCT FROM p.customer_id"),
    ("digital_events.customer_id = owner of product_id", "digital_events",
     "product_id", "products", "product_id",
     "c.customer_id IS NOT NULL AND c.customer_id <> p.customer_id"),
    ("campaign_sends.send_date within campaign start/end", "campaign_sends",
     "campaign_id", "marketing_campaigns", "campaign_id",
     "CAST(c.send_date AS DATE) NOT BETWEEN p.start_date AND p.end_date"),
    ("products.opening_date >= customer.registration_date", "products", "customer_id",
     "customers", "customer_id", "c.opening_date < CAST(p.registration_date AS DATE)"),
] + [
    (f"{t}.{ts} >= customer.registration_date", t, "customer_id", "customers",
     "customer_id", f"c.{ts} < p.registration_date")
    for t, ts in [("transactions", "transaction_date"),
                  ("call_center_interactions", "interaction_date"),
                  ("complaints", "creation_date"),
                  ("satisfaction_surveys", "survey_date"),
                  ("campaign_sends", "send_date")]
]

# Within-row rules, written as the predicate of a VIOLATION.
ROW_RULES: dict[str, list[tuple[str, str]]] = {
    "customers": [
        ("registration_date <= last_updated", "registration_date > last_updated"),
        ("age at registration in [18, 100]",
         "date_diff('year', date_of_birth, CAST(registration_date AS DATE)) "
         "NOT BETWEEN 18 AND 100"),
    ],
    "products": [
        ("expiration_date >= opening_date", "expiration_date < opening_date"),
        ("current_balance >= 0", "current_balance < 0"),
    ],
    "branches": [
        ("closing_time > opening_time", "closing_time <= opening_time"),
        ("has_atms = false => atm_count in (0, NULL)",
         "NOT has_atms AND coalesce(atm_count, 0) <> 0"),
    ],
    "service_agents": [],
    "marketing_campaigns": [("end_date >= start_date", "end_date < start_date")],
    "daily_exchange_rates": [
        ("exchange_rate > 0", "exchange_rate <= 0"),
        ("buy_rate <= sell_rate", "buy_rate > sell_rate"),
        ("source_currency <> target_currency", "source_currency = target_currency"),
    ],
    "transactions": [
        ("amount > 0", "amount <= 0"),
        ("currency = USD => amount_usd = amount",
         "currency = 'USD' AND amount_usd IS NOT NULL AND amount_usd <> amount"),
        ("transaction_date within dataset range",
         f"CAST(transaction_date AS DATE) NOT BETWEEN DATE '{DATA_START}' "
         f"AND DATE '{DATA_END}'"),
    ],
    "call_center_interactions": [
        ("(soft) was_resolved = true => requires_followup = false",
         "was_resolved AND requires_followup"),
    ],
    "call_transcripts": [],
    "satisfaction_surveys": [
        ("CSAT main_score in [1, 5]",
         "survey_type = 'CSAT' AND main_score NOT BETWEEN 1 AND 5"),
        ("NPS main_score in [0, 10]",
         "survey_type = 'NPS' AND main_score NOT BETWEEN 0 AND 10"),
        ("nps_category only for NPS", "survey_type <> 'NPS' AND nps_category IS NOT NULL"),
        ("nps_category consistent with main_score (9-10 / 7-8 / 0-6)",
         "survey_type = 'NPS' AND nps_category IS NOT NULL AND nps_category <> "
         "CASE WHEN main_score >= 9 THEN 'Promoter' WHEN main_score >= 7 "
         "THEN 'Passive' ELSE 'Detractor' END"),
        ("question_k_text null <=> question_k_response null",
         "(question_1_text IS NULL) <> (question_1_response IS NULL) OR "
         "(question_2_text IS NULL) <> (question_2_response IS NULL) OR "
         "(question_3_text IS NULL) <> (question_3_response IS NULL)"),
    ],
    "digital_events": [
        ("is_mobile consistent with channel",
         "(channel IN ('Android App', 'iOS App', 'Mobile Web')) <> is_mobile"),
    ],
    "complaints": [
        ("first_response_date >= creation_date", "first_response_date < creation_date"),
        ("resolution_date >= creation_date", "resolution_date < creation_date"),
        ("closing_date >= resolution_date", "closing_date < resolution_date"),
        ("resolution_days = days(creation_date, resolution_date)",
         "resolution_days IS NOT NULL AND resolution_date IS NOT NULL AND "
         "resolution_days <> date_diff('day', creation_date, resolution_date)"),
        ("claimed_amount null <=> currency null",
         "(claimed_amount IS NULL) <> (currency IS NULL)"),
    ],
    "campaign_sends": [
        ("was_opened = true => was_delivered = true", "was_opened AND NOT was_delivered"),
        ("open_date >= send_date", "open_date < send_date"),
        ("click_date >= open_date", "click_date < open_date"),
        ("had_conversion = true => conversion_date not null",
         "had_conversion AND conversion_date IS NULL"),
        ("was_delivered = (send_status = 'Sent')",
         "was_delivered <> (send_status = 'Sent')"),
    ],
}

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
con = duckdb.connect()
con.sql("SET enable_progress_bar = false")
for _t in TABLES:
    con.sql(f"CREATE VIEW {_t} AS SELECT * FROM read_parquet('{(INTER / f'{_t}.parquet').as_posix()}')")


def q(sql: str) -> list[tuple]:
    return con.sql(sql).fetchall()


def q1(sql: str) -> tuple:
    return con.sql(sql).fetchone()


def qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def columns(table: str) -> dict[str, str]:
    return {r[0]: r[1] for r in q(f"DESCRIBE {table}") if r[0] != "source_file"}


def pct(x: float, digits: int = 2) -> str:
    return f"{100 * x:.{digits}f}%"


def fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


def md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ")
                                     for c in r) + " |")
    return "\n".join(out)


def dispersion(counts: list[tuple[int, int]]) -> tuple[float, float, int] | None:
    """Binomial dispersion index over groups: counts = [(n_g, k_g)].

    Under H0 (the event hits every group with the same probability) the index is
    ~1 with sd sqrt(2 / (G - 1)). Returns (index, z, G) or None.
    """
    counts = [(n, k) for n, k in counts if n > 0]
    n_tot = sum(n for n, _ in counts)
    k_tot = sum(k for _, k in counts)
    g = len(counts)
    if g < 2 or k_tot == 0 or k_tot == n_tot:
        return None
    p = k_tot / n_tot
    chi2 = sum((k - n * p) ** 2 / (n * p * (1 - p)) for n, k in counts)
    d = chi2 / (g - 1)
    return d, (d - 1) / math.sqrt(2 / (g - 1)), g


def disp_str(res) -> str:
    if res is None:
        return "n/a"
    d, z, g = res
    verdict = "random" if abs(z) < 3 else "NOT random"
    return f"D={d:.2f} (z={z:+.1f}, G={g}) {verdict}"


LOG: list[str] = []


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    LOG.append(line)
    print(line, flush=True)


# --------------------------------------------------------------------------
# Profiles shared by several sections
# --------------------------------------------------------------------------
def profile(table: str) -> dict:
    cols = columns(table)
    exprs = []
    for c, t in cols.items():
        exprs.append(f"count({qi(c)})")
        exprs.append(f"approx_count_distinct({qi(c)})")
        if t == "VARCHAR":
            exprs.append(
                f"count(*) FILTER (WHERE trim({qi(c)}) IN "
                "('', 'nan', 'NaN', 'None', 'NULL', 'null', 'N/A', 'NA', '-'))")
            # a null rendered into text, e.g. "Oferta especial en nan!"
            exprs.append(
                f"count(*) FILTER (WHERE (contains({qi(c)}, 'nan') OR contains({qi(c)}, 'None')) AND "
                f"regexp_matches({qi(c)}, '(^|[^[:alpha:]])(nan|None)([^[:alpha:]]|$)') "
                f"AND trim({qi(c)}) NOT IN ('nan', 'None'))")
        else:
            exprs.append("0")
            exprs.append("0")
    r = q1(f"SELECT count(*), count(DISTINCT source_file), {', '.join(exprs)} FROM {table}")
    n, files = r[0], r[1]
    prof = {}
    for i, (c, t) in enumerate(cols.items()):
        nn, nd, blank, embedded = r[2 + 4 * i: 6 + 4 * i]
        prof[c] = dict(type=t, nulls=n - nn, distinct=nd, blank=blank, embedded_nan=embedded)
    return dict(n=n, files=files, cols=prof)


def categorical_values(table: str, col: str) -> list[tuple]:
    return q(f"SELECT {qi(col)}, count(*) FROM {table} GROUP BY 1 ORDER BY 2 DESC, 1")


# --------------------------------------------------------------------------
# (a) duplicates
# --------------------------------------------------------------------------
def duplicates(table: str, meta: dict, prof: dict) -> dict:
    pk = ", ".join(qi(c) for c in meta["pk"])
    cols = list(prof["cols"])
    r = q1(f"""
        SELECT count(*),
               (SELECT count(*) FROM (SELECT DISTINCT {pk} FROM {table})),
               (SELECT count(*) FROM (SELECT DISTINCT * EXCLUDE (source_file) FROM {table})),
               (SELECT count(*) FROM (SELECT DISTINCT * FROM {table})),
               (SELECT count(*) FROM (SELECT DISTINCT * EXCLUDE ({pk}, source_file)
                                      FROM {table}))
        FROM {table}""")
    n, n_pk, n_content, n_content_file, n_no_pk = r
    res = dict(n=n, pk_extra=n - n_pk, full_extra=n - n_content,
               full_extra_same_file=n - n_content_file, no_pk_extra=n - n_no_pk,
               pk_groups=0, pk_identical_groups=0, pk_diff_cols={}, pk_cross_file=0,
               business_keys=[])
    # Case/whitespace variants of the key
    norm = ", ".join(f"upper(trim(CAST({qi(c)} AS VARCHAR)))" for c in meta["pk"])
    res["pk_norm_extra"] = n - q1(f"SELECT count(*) FROM (SELECT DISTINCT {norm} FROM {table})")[0]

    if res["pk_extra"] > 0:
        others = [c for c in cols if c not in meta["pk"]]
        per_col = ", ".join(
            f"count(DISTINCT coalesce(CAST({qi(c)} AS VARCHAR), '<NULL>')) > 1 AS {qi('d_' + c)}"
            for c in others)
        rows = q(f"""
            WITH g AS (
                SELECT {pk}, count(DISTINCT source_file) > 1 AS cross_file, {per_col}
                FROM {table} GROUP BY {pk} HAVING count(*) > 1)
            SELECT count(*), count(*) FILTER (WHERE cross_file),
                   {', '.join(f'count(*) FILTER (WHERE {qi("d_" + c)})' for c in others)},
                   count(*) FILTER (WHERE NOT ({' OR '.join(qi('d_' + c) for c in others)}))
            FROM g""")[0]
        res["pk_groups"], res["pk_cross_file"] = rows[0], rows[1]
        res["pk_diff_cols"] = {c: v for c, v in zip(others, rows[2:-1]) if v}
        res["pk_identical_groups"] = rows[-1]

    for bk in meta.get("business_keys", []):
        keys = ", ".join(qi(c) for c in bk)
        nn = " AND ".join(f"{qi(c)} IS NOT NULL" for c in bk)
        b = q1(f"""
            SELECT count(*), coalesce(sum(k), 0) FROM (
                SELECT count(*) AS k FROM {table} WHERE {nn}
                GROUP BY {keys} HAVING count(*) > 1)""")
        res["business_keys"].append(dict(key=bk, groups=b[0], rows=int(b[1])))
    for u in meta.get("unique", []):
        b = q1(f"""SELECT count(*) - count(DISTINCT {qi(u)}) FROM {table}
                   WHERE {qi(u)} IS NOT NULL""")
        res["business_keys"].append(dict(key=[u], groups=b[0], rows=b[0], declared_unique=True))
    return res


# --------------------------------------------------------------------------
# (b) nulls: structural vs random
# --------------------------------------------------------------------------
def null_analysis(table: str, meta: dict, prof: dict) -> dict:
    n = prof["n"]
    cols = prof["cols"]
    targets = [c for c, p in cols.items() if 0 < p["nulls"] < n]
    out = {}
    if not targets:
        return out
    cands = [c for c, p in cols.items()
             if 2 <= p["distinct"] + (p["nulls"] > 0) <= LOW_CARD and c not in meta["pk"]
             and p["type"] not in ("TIMESTAMP", "DATE", "TIME")]
    # candidate = low-card column value, or null-indicator of another column
    gexpr = [f"coalesce(CAST({qi(c)} AS VARCHAR), '<NULL>') AS g{i}" for i, c in enumerate(cands)]
    gnames = [("col", c) for c in cands]
    for c in targets:
        gexpr.append(f"CASE WHEN {qi(c)} IS NULL THEN 'null' ELSE 'not null' END AS g{len(gnames)}")
        gnames.append(("isnull", c))
    tgt = [f"({qi(c)} IS NULL)::INT AS {qi('t_' + c)}" for c in targets]
    gsets = ", ".join(f"(g{i})" for i in range(len(gnames)))
    sql = f"""
        WITH b AS (SELECT {', '.join(gexpr)}, {', '.join(tgt)} FROM {table})
        SELECT {', '.join(f'g{i}' for i in range(len(gnames)))}, count(*),
               {', '.join(f'sum({qi("t_" + c)})' for c in targets)}
        FROM b GROUP BY GROUPING SETS ({gsets})"""
    rows = q(sql)
    G = len(gnames)
    groups: dict[int, list] = {i: [] for i in range(G)}
    for r in rows:
        gi = next(i for i in range(G) if r[i] is not None)
        groups[gi].append((r[gi], r[G], list(r[G + 1:])))

    ev = meta.get("event_ts")
    for ti, c in enumerate(targets):
        k_tot = cols[c]["nulls"]
        base = min(k_tot, n - k_tot)
        best = None
        for gi, (kind, gc) in enumerate(gnames):
            if gc == c:
                continue
            imp = sum(min(nulls[ti], ng - nulls[ti]) for _, ng, nulls in groups[gi])
            expl = 1 - imp / base
            score = (round(expl, 4), kind == "col")  # prefer real columns on ties
            if best is None or score > best[0]:
                best = (score, gi, expl)
        _, gi, expl = best
        kind, gc = gnames[gi]
        grp = sorted(((v, ng, nulls[ti]) for v, ng, nulls in groups[gi]),
                     key=lambda x: -x[1])
        # a group only counts as "always null" if it is big enough to mean something
        full = [(v, ng, k) for v, ng, k in grp if k / ng > 0.99 and ng >= MIN_GROUP]
        rest = [(v, ng, k) for v, ng, k in grp if (v, ng, k) not in full]
        rest_n = sum(ng for _, ng, _ in rest)
        rest_k = sum(k for _, _, k in rest)
        rest_rate = rest_k / rest_n if rest_n else None
        co_null = None
        if kind == "isnull" and expl >= 0.5:
            # nulls travel with another column's nulls: report both conditionals
            d = dict((v, (ng, k)) for v, ng, k in grp)
            p_if_null = d["null"][1] / d["null"][0] if "null" in d else None
            p_if_not = d["not null"][1] / d["not null"][0] if "not null" in d else None
            co_null = (p_if_null, p_if_not)
        if expl >= 0.98:
            cls = "structural"
        elif co_null:
            cls = "co-null"
        elif full and rest_k > 0:
            cls = "structural + random"
        else:
            cls = "random"
        explainer = gc if kind == "col" else f"{gc} IS NULL"
        disp_x = (dispersion([(ng, k) for _, ng, k in rest])
                  if cls in ("random", "structural + random") else None)
        # MCAR over time within the non-structural part (fact tables only)
        disp_t = None
        if ev and cls != "structural":
            cond = "TRUE"
            if full:
                col_expr = (f"coalesce(CAST({qi(gc)} AS VARCHAR), '<NULL>')" if kind == "col"
                            else f"CASE WHEN {qi(gc)} IS NULL THEN 'null' ELSE 'not null' END")
                vals = ", ".join("'" + str(v).replace("'", "''") + "'" for v, _, _ in full)
                cond = f"{col_expr} NOT IN ({vals})"
            m = q(f"""SELECT date_trunc('month', {qi(ev)}), count(*),
                             count(*) FILTER (WHERE {qi(c)} IS NULL)
                      FROM {table} WHERE {cond} GROUP BY 1""")
            disp_t = dispersion([(a, b) for _, a, b in m])
        out[c] = dict(rate=k_tot / n, cls=cls, explainer=explainer, explained=expl,
                      co_null=co_null,
                      always_null_when=[(v, ng) for v, ng, _ in full],
                      groups=[(v, ng, k / ng) for v, ng, k in grp[:12]],
                      residual_rate=rest_rate, disp_x=disp_x, disp_t=disp_t)
    return out


# --------------------------------------------------------------------------
# (c) orphans
# --------------------------------------------------------------------------
def id_shape(col: str) -> str:
    return f"left({col}, 4) || length({col})"


def orphans() -> list[dict]:
    res = []
    for child, col, parent, pcol in FKS:
        ev = TABLES[child].get("event_ts")
        r = q1(f"""
            SELECT count(*), count(c.{col}),
                   count(*) FILTER (WHERE c.{col} IS NOT NULL AND p.k IS NULL),
                   count(DISTINCT c.{col}) FILTER (WHERE c.{col} IS NOT NULL AND p.k IS NULL),
                   count(*) FILTER (WHERE c.{col} IS NOT NULL AND p.k IS NULL
                                    AND {id_shape('c.' + col)} IN
                                        (SELECT DISTINCT {id_shape(pcol)} FROM {parent}))
            FROM {child} c
            LEFT JOIN (SELECT DISTINCT {pcol} AS k FROM {parent}) p ON c.{col} = p.k""")
        n, nn, orph, orph_d, orph_fmt = r
        samples = q(f"""SELECT DISTINCT c.{col} FROM {child} c
                        WHERE c.{col} IS NOT NULL
                          AND c.{col} NOT IN (SELECT {pcol} FROM {parent})
                        ORDER BY 1 LIMIT 3""") if orph else []
        disp_t = None
        if ev and orph:
            m = q(f"""SELECT date_trunc('month', c.{ev}), count(*),
                             count(*) FILTER (WHERE p.k IS NULL)
                      FROM {child} c
                      LEFT JOIN (SELECT DISTINCT {pcol} AS k FROM {parent}) p ON c.{col} = p.k
                      WHERE c.{col} IS NOT NULL GROUP BY 1""")
            disp_t = dispersion([(a, b) for _, a, b in m])
        res.append(dict(child=child, col=col, parent=parent, pcol=pcol, n=n, non_null=nn,
                        orphans=orph, orphan_distinct=orph_d, orphan_same_format=orph_fmt,
                        rate=orph / nn if nn else None, samples=[s[0] for s in samples],
                        disp_t=disp_t))
    return res


def shuffled(parent: str, pk: str) -> str:
    """Parent table where each key carries the attributes of a random other row."""
    return f"""(SELECT a.{pk}, b.* EXCLUDE ({pk}, rn) FROM
                  (SELECT {pk}, row_number() OVER (ORDER BY {pk}) AS rn FROM {parent}) a
                  JOIN (SELECT *, row_number() OVER (ORDER BY hash({pk}, {SEED})) AS rn
                        FROM {parent}) b USING (rn))"""


def consistency() -> list[dict]:
    res = []
    for name, child, ck, parent, pk, viol in CONSISTENCY:
        sql = ("SELECT count(*), count(*) FILTER (WHERE {v}) FROM {c} c "
               "JOIN {p} p ON c.{ck} = p.{pk}")
        r = q1(sql.format(v=viol, c=child, p=parent, ck=ck, pk=pk))
        b = q1(sql.format(v=viol, c=child, p=shuffled(parent, pk), ck=ck, pk=pk))
        res.append(dict(rule=name, checked=r[0], violations=r[1],
                        baseline=b[1] / b[0] if b[0] else None))
    # has_transcript flag vs presence of a transcript (no parent-attribute baseline)
    r = q1("""SELECT count(*), count(*) FILTER (WHERE c.has_transcript
                                                 IS DISTINCT FROM (t.interaction_id IS NOT NULL))
              FROM call_center_interactions c
              LEFT JOIN (SELECT DISTINCT interaction_id FROM call_transcripts) t
              USING (interaction_id)""")
    res.append(dict(rule="interaction.has_transcript = (transcript exists)",
                    checked=r[0], violations=r[1], baseline=None))
    return res


def product_currency_by_country() -> list[tuple]:
    return q("""SELECT c.country, p.currency, count(*) FROM products p
                JOIN customers c USING (customer_id) GROUP BY 1, 2 ORDER BY 1, 2""")


# --------------------------------------------------------------------------
# (d) late arrivals
# --------------------------------------------------------------------------
PART_DATE = ("make_date(CAST(regexp_extract(source_file, 'year=(\\d+)', 1) AS INT), "
             "CAST(regexp_extract(source_file, 'month=(\\d+)', 1) AS INT), "
             "CAST(regexp_extract(source_file, 'day=(\\d+)', 1) AS INT))")


def late_arrivals(table: str, meta: dict) -> dict:
    ev = meta.get("event_ts")
    if ev:
        frm, ev_expr, grp = table + " t", f"t.{ev}", f"t.{meta['group_col']}"
        ev_label = ev
    else:  # call_transcripts: event date comes from the linked interaction
        frm = (f"{table} t JOIN call_center_interactions i USING (interaction_id)")
        ev_expr, grp, ev_label = "i.interaction_date", f"t.{meta['group_col']}", \
            "call_center_interactions.interaction_date (via interaction_id)"
    base = f"""SELECT date_diff('day', CAST({ev_expr} AS DATE), t.process_date) AS lag,
                      date_trunc('month', {ev_expr}) AS m, {grp} AS g,
                      t.source_file, t.process_date
               FROM {frm}"""
    dist = q(f"SELECT lag, count(*) FROM ({base}) GROUP BY 1 ORDER BY 1")
    total = sum(c for _, c in dist)
    qs = q1(f"""SELECT quantile_cont(lag, [0.5, 0.9, 0.95, 0.99]), min(lag), max(lag),
                       avg(lag), avg(lag) FILTER (WHERE lag > 0),
                       count(*) FILTER (WHERE {PART_DATE.replace('source_file', 'source_file')}
                                        <> process_date)
                FROM ({base})""")
    by_m = q(f"SELECT m, count(*), count(*) FILTER (WHERE lag > 0) FROM ({base}) GROUP BY 1")
    by_g = q(f"SELECT g, count(*), count(*) FILTER (WHERE lag > 0) FROM ({base}) GROUP BY 1")
    by_y = q(f"""SELECT year(m), count(*), count(*) FILTER (WHERE lag > 0),
                        max(lag) FROM ({base}) GROUP BY 1 ORDER BY 1""")
    unmatched = 0
    if not ev:
        unmatched = q1(f"""SELECT count(*) FROM {table} t
                           WHERE interaction_id NOT IN
                                 (SELECT interaction_id FROM call_center_interactions)""")[0]
    ev_range = q1(f"SELECT min({ev_expr}), max({ev_expr}), min(t.process_date), "
                  f"max(t.process_date) FROM {frm}")
    # Business-day cutoff model: process_date = CAST(event_ts - h hours AS DATE).
    hours = list(range(0, 13))
    agree = q1(f"""SELECT {', '.join(
        f"avg((t.process_date = CAST({ev_expr} - INTERVAL {h} HOUR AS DATE))::INT)"
        for h in hours)} FROM {frm}""")
    best_h = max(hours, key=lambda h: agree[h])
    neg_hours = q(f"""SELECT hour({ev_expr}),
                             avg((t.process_date < CAST({ev_expr} AS DATE))::INT)
                      FROM {frm} GROUP BY 1 ORDER BY 1""")
    late = [(lag, c) for lag, c in dist if lag > 0]
    return dict(event=ev_label, total=total, dist=dist, quantiles=qs[0], min=qs[1],
                max=qs[2], mean=qs[3], mean_late=qs[4], partition_mismatch=qs[5],
                late=sum(c for _, c in late), negative=sum(c for lag, c in dist if lag < 0),
                disp_t=dispersion([(a, b) for _, a, b in by_m]),
                disp_g=dispersion([(a, b) for _, a, b in by_g]),
                by_g=sorted(((g, a, b / a) for g, a, b in by_g), key=lambda x: -x[1]),
                by_y=by_y, unmatched=unmatched, range=ev_range,
                group_col=meta["group_col"], cutoff_h=best_h, cutoff_agree=agree[best_h],
                agree_h0=agree[0], neg_hours=neg_hours)


def late_samples(table: str, meta: dict) -> list[tuple]:
    ev = meta.get("event_ts")
    if not ev:
        return q(f"""SELECT t.{meta['pk'][0]}, i.interaction_date, t.process_date,
                            date_diff('day', CAST(i.interaction_date AS DATE), t.process_date),
                            t.source_file
                     FROM {table} t JOIN call_center_interactions i USING (interaction_id)
                     ORDER BY 4, 1 LIMIT 3""")
    return q(f"""SELECT {meta['pk'][0]}, {ev}, process_date,
                        date_diff('day', CAST({ev} AS DATE), process_date), source_file
                 FROM {table} ORDER BY 4, 1 LIMIT 3""")


# --------------------------------------------------------------------------
# (e) schema evolution
# --------------------------------------------------------------------------
TABLE_GLOBS = {t: (f"{t}.csv" if TABLES[t]["kind"] != "fact" else f"{t}/**/*.csv")
               for t in TABLES}


def raw_headers(table: str) -> dict:
    files = sorted(RAW.glob(TABLE_GLOBS[table]))
    headers: dict[str, list[str]] = {}
    bom = crlf = 0
    for f in files:
        with open(f, "rb") as fh:
            line = fh.readline()
        bom += line.startswith(b"\xef\xbb\xbf")
        crlf += line.endswith(b"\r\n")
        h = line.decode("utf-8-sig").strip()
        headers.setdefault(h, []).append(f.relative_to(RAW).as_posix())
    days = sorted(date(int(m[1]), int(m[2]), int(m[3])) for f in files
                  if (m := re.search(r"_(\d{4})(\d{2})(\d{2})\.csv$", f.name)))
    gaps = ((days[-1] - days[0]).days + 1 - len(set(days))) if days else None
    return dict(files=len(files), variants=[(h.split(","), fs[0], fs[-1], len(fs))
                                            for h, fs in headers.items()],
                bom=bom, crlf=crlf, first_day=days[0] if days else None,
                last_day=days[-1] if days else None, missing_days=gaps)


def raw_formats(table: str, prof: dict, meta: dict) -> list[dict]:
    """Value 'shapes' of typed and key columns in the raw CSV, per source file."""
    ids = set(meta["pk"]) | {c for ch, c, _, _ in FKS if ch == table}
    typed = [c for c, p in prof["cols"].items() if p["type"] != "VARCHAR"]
    cols = [c for c in prof["cols"] if c in ids or c in typed]
    shapes = []
    for c in cols:
        t = prof["cols"][c]["type"]
        if t == "BOOLEAN":
            s = qi(c)
        elif c in ids and t == "VARCHAR":
            s = f"left({qi(c)}, 4) || '<' || length({qi(c)}) || '>'"
        else:
            s = (f"regexp_replace(regexp_replace({qi(c)}, '[0-9]+', '9', 'g'), "
                 "'[A-Za-z]+', 'a', 'g')")
        shapes.append(f"{s} AS {qi(c)}")
    glob = (RAW / TABLE_GLOBS[table]).as_posix()
    rows = q(f"""
        SELECT col, shape, count(*), count(DISTINCT filename), min(filename), max(filename)
        FROM (UNPIVOT (SELECT filename, {', '.join(shapes)}
                       FROM read_csv('{glob}', header=true, all_varchar=true,
                                     union_by_name=true, filename=true))
              ON {', '.join(qi(c) for c in cols)} INTO NAME col VALUE shape)
        GROUP BY 1, 2 ORDER BY 1, 3 DESC""")
    def fdate(path: str) -> date | None:
        m = re.search(r"_(\d{4})(\d{2})(\d{2})\.csv$", path)
        return date(int(m[1]), int(m[2]), int(m[3])) if m else None

    all_dates = [fdate(r[4]) for r in rows] + [fdate(r[5]) for r in rows]
    all_dates = [d for d in all_dates if d]
    span = (min(all_dates), max(all_dates)) if all_dates else None
    out = []
    for c in cols:
        rs = [r for r in rows if r[0] == c]
        total = sum(r[2] for r in rs)
        shapes = []
        for r in rs:
            first, last = fdate(r[4]), fdate(r[5])
            if span is None or len(rs) == 1:
                status = "only shape" if len(rs) == 1 else "single file"
            elif (first - span[0]).days > 45 or (span[1] - last).days > 45:
                status = "time-bounded"
            elif r[3] < prof["files"]:
                status = "sporadic"
            else:
                status = "every file"
            shapes.append(dict(shape=r[1], rows=r[2], share=r[2] / total, files=r[3],
                               first=Path(r[4]).name, last=Path(r[5]).name, status=status))
        out.append(dict(col=c, type=prof["cols"][c]["type"], shapes=shapes,
                        drift=any(s["status"] == "time-bounded" for s in shapes)))
    return out


def categorical_drift(table: str, meta: dict, prof: dict) -> list[dict]:
    ev = meta.get("event_ts")
    if not ev:
        return []
    cats = [c for c, p in prof["cols"].items()
            if p["type"] == "VARCHAR" and p["distinct"] <= LOW_CARD and c not in meta["pk"]]
    span = q1(f"SELECT min(date_trunc('month', {ev})), max(date_trunc('month', {ev})) "
              f"FROM {table}")
    out = []
    for c in cats:
        rows = q(f"""SELECT {qi(c)}, min(date_trunc('month', {ev})), max(date_trunc('month', {ev})),
                            count(*) FROM {table} WHERE {qi(c)} IS NOT NULL GROUP BY 1""")
        for v, first, last, cnt in rows:
            if (first - span[0]).days > 45 or (span[1] - last).days > 45:
                out.append(dict(col=c, value=v, first=first, last=last, rows=cnt))
    return out


# --------------------------------------------------------------------------
# Value domain (for contracts)
# --------------------------------------------------------------------------
def domains(table: str, meta: dict, prof: dict) -> dict:
    res = dict(categorical={}, numeric={}, temporal={})
    for c, p in prof["cols"].items():
        t = p["type"]
        if t in ("VARCHAR", "BOOLEAN") and p["distinct"] <= LOW_CARD and c not in meta["pk"]:
            res["categorical"][c] = categorical_values(table, c)
        elif t.startswith(("DECIMAL", "INTEGER", "DOUBLE", "BIGINT")):
            r = q1(f"SELECT min({qi(c)}), max({qi(c)}), avg({qi(c)}), "
                   f"count(*) FILTER (WHERE {qi(c)} < 0) FROM {table}")
            res["numeric"][c] = dict(min=r[0], max=r[1], mean=r[2], negatives=r[3])
        elif t in ("DATE", "TIMESTAMP", "TIME"):
            r = q1(f"SELECT min({qi(c)}), max({qi(c)}) FROM {table}")
            res["temporal"][c] = dict(min=r[0], max=r[1])
        elif t == "VARCHAR":
            res["categorical_high"] = res.get("categorical_high", {})
            res["categorical_high"][c] = p["distinct"]
    viol = []
    for name, pred in ROW_RULES.get(table, []):
        r = q1(f"SELECT count(*) FILTER (WHERE {pred}) FROM {table}")
        viol.append(dict(rule=name, violations=r[0]))
    res["row_rules"] = viol
    res["range_violations"] = {}
    for c, (lo, hi) in meta.get("ranges", {}).items():
        conds = []
        if lo is not None:
            conds.append(f"{qi(c)} < {lo}")
        if hi is not None:
            conds.append(f"{qi(c)} > {hi}")
        r = q1(f"SELECT count(*) FILTER (WHERE {' OR '.join(conds)}) FROM {table}")
        res["range_violations"][c] = dict(lo=lo, hi=hi, violations=r[0])
    res["enum_violations"] = {}
    for c, allowed in meta.get("enums", {}).items():
        vals = res["categorical"].get(c) or categorical_values(table, c)
        extra = [(v, k) for v, k in vals if v is not None and v not in allowed]
        missing = [a for a in allowed if a not in {v for v, _ in vals}]
        res["enum_violations"][c] = dict(extra=extra, missing=missing)
    return res


def exchange_completeness() -> dict:
    r = q1("""SELECT count(DISTINCT date), min(date), max(date),
                     count(DISTINCT (source_currency, target_currency))
              FROM daily_exchange_rates""")
    days = (r[2] - r[1]).days + 1
    pairs = q("""SELECT source_currency, target_currency, count(*),
                        count(DISTINCT date) FROM daily_exchange_rates
                 GROUP BY 1, 2 ORDER BY 1, 2""")
    return dict(dates=r[0], first=r[1], last=r[2], calendar_days=days, pairs=r[3],
                per_pair=pairs, expected=days * r[3])


# --------------------------------------------------------------------------
# Contracts
# --------------------------------------------------------------------------
def build_contract(table: str, meta: dict, prof: dict, dup: dict, nulls: dict,
                   fk: list[dict], late: dict | None, dom: dict) -> dict:
    n = prof["n"]
    nullable = {}
    for c, info in nulls.items():
        if info["cls"] == "structural":
            rule = f"structural: null determined by `{info['explainer']}`"
            if info["always_null_when"]:
                rule += " = " + ", ".join(f"`{v}`" for v, _ in info["always_null_when"])
        elif info["cls"] == "co-null":
            a, b = info["co_null"]
            rule = (f"co-null with `{info['explainer'].replace(' IS NULL', '')}` "
                    f"(null in {pct(a, 1)} of rows where it is null, "
                    f"{pct(b, 1)} where it is not)")
        elif info["cls"] == "structural + random":
            rule = (f"null when `{info['explainer']}` = "
                    + ", ".join(f"`{v}`" for v, _ in info["always_null_when"])
                    + f"; otherwise random at ~{pct(info['residual_rate'], 1)}")
        else:
            rule = f"random at ~{pct(info['rate'], 1)}"
        nullable[c] = dict(observed_null_rate=round(info["rate"], 4), rule=rule)
    allowed = {}
    for c, vals in dom["categorical"].items():
        if prof["cols"][c]["type"] == "BOOLEAN":
            continue
        allowed[c] = [v for v, _ in vals if v is not None]
    ranges = {}
    for c, s in dom["numeric"].items():
        decl = meta.get("ranges", {}).get(c)
        ranges[c] = dict(observed=[_num(s["min"]), _num(s["max"])],
                         declared=list(decl) if decl else None)
    fks = [dict(column=f["col"], references=f"{f['parent']}.{f['pcol']}",
                observed_orphan_rate=round(f["rate"], 5) if f["rate"] is not None else None,
                policy=_fk_policy(f))
           for f in fk if f["child"] == table]
    contract = dict(
        table=table, kind=meta["kind"], grain=f"one row per {' + '.join(meta['pk'])}",
        primary_key=meta["pk"], unique=meta.get("unique", []),
        required=[c for c in meta["not_null"] if prof["cols"][c]["nulls"] == 0],
        relaxed_not_null=[c for c in meta["not_null"] if prof["cols"][c]["nulls"] > 0],
        notes=meta.get("notes", []), nullable=nullable, allowed_values=allowed,
        numeric_ranges=ranges, foreign_keys=fks,
        row_rules=[r["rule"] for r in dom["row_rules"]],
        dedup_rule=_dedup_rule(meta, dup),
    )
    if late:
        if table in PARENT_PROCESS_DATE:
            rule = ("process_date = process_date of the linked interaction (100% observed); "
                    "the row can land in a partition before its own event time")
        else:
            rule = (f"process_date = CAST({late['event']} - INTERVAL {late['cutoff_h']} HOUR "
                    f"AS DATE) (business-day cutoff at {late['cutoff_h']:02d}:00, "
                    f"{pct(late['cutoff_agree'], 3)} of rows agree); lag in "
                    f"[{late['min']}, {late['max']}] days")
        contract["late_arrival"] = dict(
            partition_key="process_date", event_time=late["event"],
            observed_lag_days=[late["min"], late["max"]], cutoff_hour=late["cutoff_h"],
            rule=rule + "; partition path date must equal process_date")
    embedded = [c for c, p in prof["cols"].items() if p.get("embedded_nan")]
    if embedded:
        contract["text_rules"] = [f"`{c}` must not contain a rendered null ('nan'/'None')"
                                  for c in embedded]
    return contract


def _num(x):
    if x is None:
        return None
    return float(x) if not isinstance(x, int) else x


def _fk_policy(f: dict) -> str:
    if f["non_null"] == 0:
        return "column is always null: FK unusable; drop or treat as unknown"
    if f["orphans"] == 0:
        return "enforce (fail on orphan)"
    return "keep row, flag `<col>_orphan = true`; inner joins drop it"


def _dedup_rule(meta: dict, dup: dict) -> str:
    pk = " + ".join(meta["pk"])
    if meta["kind"] == "fact":
        return (f"unique on {pk}. On violation keep the row with the latest process_date, "
                "then latest source_file; alert if the kept and dropped rows differ outside "
                "process_date/source_file")
    return f"unique on {pk} (single snapshot file); fail on violation"


# --------------------------------------------------------------------------
# Report rendering
# --------------------------------------------------------------------------
def render(results: dict) -> str:
    R = results
    L: list[str] = []
    w = L.append
    tables = list(TABLES)
    total_rows = sum(R["prof"][t]["n"] for t in tables)

    # ---- headline numbers
    dup_rows = sum(R["dup"][t]["pk_extra"] + R["dup"][t]["full_extra"] for t in tables)
    dup_rate = dup_rows / total_rows
    nn_viol = [(t, c, R["prof"][t]["cols"][c]["nulls"] / R["prof"][t]["n"])
               for t in tables for c in TABLES[t]["not_null"]
               if R["prof"][t]["cols"].get(c, {}).get("nulls", 0) > 0]
    uq_viol = [(t, b["key"][0], b["rows"]) for t in tables
               for b in R["dup"][t]["business_keys"] if b.get("declared_unique") and b["rows"]]
    nullable_cols = [(t, c, i) for t in tables for c, i in R["nulls"][t].items()]

    def random_rate(i):
        if i["cls"] == "random":
            return i["rate"]
        if i["cls"] == "structural + random":
            return i["residual_rate"]
        return None

    rnd = [(t, c, random_rate(i)) for t, c, i in nullable_cols if random_rate(i)]
    near5 = [x for x in rnd if abs(x[2] - DECLARED_NULL_RATE) <= 0.01]
    rate_hist: dict[str, int] = {}
    for _, _, r in rnd:
        k = pct(round(r * 100) / 100, 0)
        rate_hist[k] = rate_hist.get(k, 0) + 1
    n_struct = sum(1 for _, _, i in nullable_cols if i["cls"] in ("structural", "co-null"))
    orph = [f for f in R["fk"] if f["orphans"] > 0]
    broken = [f for f in orph if f["rate"] > 0.5]
    small = [f for f in orph if f["rate"] <= 0.05]
    dead = [f for f in R["fk"] if f["non_null"] == 0]
    late_tot = sum(R["late"][t]["late"] for t in R["late"])
    late_n = sum(R["late"][t]["total"] for t in R["late"])
    neg_tot = sum(R["late"][t]["negative"] for t in R["late"])
    drift = [(t, f["col"]) for t in tables for f in R["fmt"][t] if f["drift"]]
    hdr_var = [t for t in tables if len(R["hdr"][t]["variants"]) > 1]
    enum_bad = [(t, c, v) for t in tables for c, v in R["dom"][t]["enum_violations"].items()
                if v["extra"]]
    rowcount_off = [t for t in tables
                    if abs(R["prof"][t]["n"] / TABLES[t]["declared_rows"] - 1) > 0.05]
    cons = {c["rule"]: c for c in R["consistency"]}
    embedded = [(t, c, p["embedded_nan"]) for t in tables
                for c, p in R["prof"][t]["cols"].items() if p.get("embedded_nan")]

    def status(ok: bool, partial: bool = False) -> str:
        return "supported" if ok else ("partially supported" if partial else "refuted")

    claims = {
        "duplicates ~2%": status(0.01 <= dup_rate <= 0.03, dup_rate > 0.002),
        "nulls ~5% in nullable fields": status(False, bool(near5)),
        "small % of FK orphans": status(bool(small) and not broken, bool(orph)),
        "late arrivals": status(late_tot > 0),
        "schema evolution": status(bool(drift or hdr_var)),
    }
    n_ok = sum(v == "supported" for v in claims.values())

    w("# C1 - Declared vs real data quality\n")
    w(f"Generated by `ml/analysis/day1/C1_data_quality.py` on {date.today()} over "
      f"`ml/data/02_intermediate/` ({len(tables)} tables, {total_rows:,} rows). "
      "All numbers are raw: no deduplication or cleaning has been applied.\n")
    w("## Hypothesis\n")
    w("The real quality issues match the ones the data dictionary declares: ~2% "
      "duplicates, ~5% nulls in nullable fields, late-arriving partitions, schema "
      "evolution, and a small percentage of FK orphans. The NOT NULL / UNIQUE "
      "constraints and the enumerations hold.\n")
    w(f"## Verdict: **refuted as stated** ({n_ok} of {len(claims)} declared "
      "characteristics hold)\n")
    w("The data is cleaner than declared on the axes the dictionary advertises (no "
      "duplicates, no late arrivals, no schema drift). It is dirtier on axes the "
      "dictionary does not mention: broken FKs, relationships that are random, "
      "Spanish labels, currency, and UNIQUE violations.\n")
    w("| declared characteristic | verdict | evidence |")
    w("|---|---|---|")
    w(f"| Duplicates ~2% | {claims['duplicates ~2%']} | {dup_rows} duplicate rows out "
      f"of {total_rows:,} ({pct(dup_rate, 3)}), counting both full-row and PK-only. "
      "There are also 0 case/whitespace variants of the PK, and 0 rows identical once "
      "the PK is ignored (except `daily_exchange_rates`, where equal rates on different "
      "dates are legitimate). |")
    w(f"| Nulls ~5% in nullable fields | {claims['nulls ~5% in nullable fields']} | "
      f"{len(nullable_cols)} columns have nulls. {n_struct} of them are structural or "
      "co-null (e.g. `credit_limit` is null for non-credit products). "
      f"{len(rnd)} have a random component, and only {len(near5)} of those sit at "
      "5% ± 1pp. Random rates are round generator parameters: "
      + ", ".join(f"{k} x{v}" for k, v in sorted(rate_hist.items(),
                                                   key=lambda x: float(x[0][:-1]))) + ". |")
    w(f"| Small % of FK orphans | {claims['small % of FK orphans']} | "
      f"{len(orph)} of {len(R['fk'])} FKs have orphans"
      + (": " + ", ".join(f"`{f['child']}.{f['col']}` {pct(f['rate'], 2)}" for f in orph)
         if orph else "")
      + f". {len(dead)} FK is 100% null"
      + (": " + ", ".join(f"`{f['child']}.{f['col']}`" for f in dead) if dead else "")
      + ". Every other FK has 0 orphans. |")
    w(f"| Late arrivals | {claims['late arrivals']} | {late_tot:,} of {late_n:,} fact "
      "rows have process_date > event date. The "
      f"{neg_tot:,} rows ({pct(neg_tot / late_n, 1)}) with process_date < event date "
      "come from a business-day cutoff (06:00 or 08:00), not from late delivery. "
      "See (d). |")
    w(f"| Schema evolution | {claims['schema evolution']} | {len(hdr_var)} tables have "
      f"more than one header variant, and {len(drift)} typed/key columns have a raw "
      "format bounded in time. Some formats are sporadic (scientific notation in "
      "`latitude`/`longitude`), but they cast fine. |")
    w(f"| NOT NULL holds | {status(not nn_viol)} | "
      + (", ".join(f"`{t}.{c}` {pct(r, 1)} null" for t, c, r in nn_viol) or "0 violations")
      + ". |")
    w(f"| UNIQUE holds | {status(not uq_viol)} | "
      + (", ".join(f"`{t}.{c}` {v} duplicate values" for t, c, v in uq_viol)
         or "0 violations") + ". |")
    w(f"| Enumerations hold | {status(not enum_bad)} | {len(enum_bad)} columns have "
      "values outside the dictionary. Most are Spanish labels where the dictionary is "
      "English (`México`, `Pasaporte`, `Negativo`, `Urbana`). See Value domains. |")
    w(f"| Declared row counts | {status(not rowcount_off)} | {len(rowcount_off)} tables "
      "are more than 5% away from the declared count. See the row-count table. |")
    w("")
    w("### Problems the dictionary does not declare\n")
    rc = cons.get("complaints.customer_id = owner of affected_product_id")
    de = cons.get("digital_events.customer_id = owner of product_id")
    reg = cons.get("transactions.transaction_date >= customer.registration_date")
    cur = R["currency_by_country"]
    mx = [(c, k, n) for c, k, n in cur if c.startswith("M")]
    w("1. **Branch FKs are broken.** "
      + "; ".join(f"`{f['child']}.{f['col']}` has {pct(f['rate'], 2)} orphans, with "
                  f"{f['orphan_distinct']:,} distinct well-formed IDs that point nowhere"
                  for f in broken)
      + ". Registration branch and agent branch cannot be joined.")
    if rc:
        w(f"2. **`complaints.affected_product_id` is not owned by the complaining "
          f"customer** in {pct(rc['violations'] / rc['checked'], 1)} of "
          f"{rc['checked']:,} rows (shuffled baseline {pct(rc['baseline'], 1)}). "
          "The product link is random, so complaint to product to transactions cannot be "
          "traced (relevant for Track A). "
          + (f"`digital_events.product_id` belongs to its customer in "
             f"{pct(1 - de['violations'] / de['checked'], 1)} of rows (baseline "
             f"{pct(1 - de['baseline'], 1)}), so that link is partial." if de else ""))
    if reg:
        w(f"3. **Customer registration dates are unrelated to activity.** "
          f"{pct(reg['violations'] / reg['checked'], 1)} of transactions predate the "
          f"customer's registration_date, against a shuffled baseline of "
          f"{pct(reg['baseline'], 1)}. The same holds for every fact table. Do not "
          "use tenure = event - registration_date as a feature without flagging this.")
    w(f"4. **`complaints.origin_interaction_id` is 100% null**, so B4 cannot use the "
      "declared link and must fall back to matching by customer and date.")
    w("5. **Currency.** MXN never appears. Mexican products are "
      + ", ".join(f"{k} ({n:,})" for _, k, n in mx)
      + ", while Colombia and Argentina use local currency plus some USD. Every "
      "transaction inherits its product's currency.")
    if embedded:
        w("6. **Nulls rendered into text**: "
          + ", ".join(f"`{t}.{c}` ({k:,} rows)" for t, c, k in embedded)
          + ", e.g. `¡Oferta especial en nan!`.")
    w("")
    w("**Consequence (from 'Si falla'): document the gaps and adjust the contracts.** "
      "The contracts are at the end of this report and in "
      "`docs/findings/day1/C1_contracts.json`. For `03_primary`:\n"
      "- Dedup: only a uniqueness assertion is needed; no rows to drop today.\n"
      "- Nulls: follow the structural rules per column, not a blanket 5%.\n"
      "- Labels: map Spanish labels to the dictionary enums, or accept them.\n"
      "- Broken branch FKs: flag them.\n"
      "- Partitions: select on the event timestamp, not process_date. process_date is "
      "a business day with a cutoff, so date-sliced features must be computed from "
      "event time. Surveys can land in a partition before they happen, which is a "
      "leakage risk for time splits.\n")
    # ---- row counts
    w("## Row counts vs declared\n")
    rows = []
    for t in tables:
        n, d = R["prof"][t]["n"], TABLES[t]["declared_rows"]
        rows.append([t, TABLES[t]["kind"], fmt(d), fmt(n), f"{n / d:.2f}x",
                     R["prof"][t]["files"]])
    w(md_table(["table", "kind", "declared rows", "actual rows", "ratio", "source files"],
               rows))
    ex = R["exchange"]
    w(f"\n`daily_exchange_rates`: {ex['dates']:,} distinct dates "
      f"({ex['first']} to {ex['last']}, calendar = {ex['calendar_days']:,} days) x "
      f"{ex['pairs']} currency pairs = {ex['expected']:,} expected rows, and "
      f"{R['prof']['daily_exchange_rates']['n']:,} actual rows. The declared 3,000 rows "
      "is a dictionary error, not missing data. Per pair: "
      + ", ".join(f"{s}->{tg} {c:,}" for s, tg, c, _ in ex["per_pair"]) + ".\n")

    # ---- (a)
    w("## (a) Duplicates\n")
    w("Query: `count(*)` against `count(DISTINCT pk)`, `count(DISTINCT * EXCLUDE "
      "(source_file))`, and `count(DISTINCT * EXCLUDE (pk, source_file))` (rows that "
      "differ only in their ID). \"Norm. PK\" upper-cases and trims the key before "
      "counting.\n")
    rows = []
    for t in tables:
        d = R["dup"][t]
        rows.append([t, fmt(d["n"]), d["full_extra"], pct(d["full_extra"] / d["n"], 3),
                     d["pk_extra"], pct(d["pk_extra"] / d["n"], 3), d["pk_norm_extra"],
                     d["no_pk_extra"], d["pk_identical_groups"],
                     ", ".join(f"{c} ({v})" for c, v in d["pk_diff_cols"].items()) or "-"])
    w(md_table(["table", "rows", "full-row dup rows", "rate", "PK dup rows", "rate",
                "norm. PK dup rows", "dup ignoring PK", "PK groups identical",
                "PK groups: differing columns"], rows))
    w(f"\nDeclared rate: {pct(DECLARED_DUP_RATE, 0)}. For the null baseline: with "
      f"{total_rows:,} rows, a true 2% rate would give ~{int(total_rows * 0.02):,} "
      "duplicates. Seeing 0 has probability ~0 under that rate, so the declared "
      "duplicate injection is simply absent from this delivery. PK duplicates are 0, "
      "so the content-comparison step (identical vs differing columns) has nothing "
      "to report.\n")
    w("Business-key near-duplicates (same natural key, different PK):\n")
    rows = []
    for t in tables:
        for b in R["dup"][t]["business_keys"]:
            rows.append([t, " + ".join(b["key"]) + (" (declared UNIQUE)" if b.get("declared_unique") else ""),
                         b["groups"], b["rows"]])
    w(md_table(["table", "key", "groups with >1 row", "rows in those groups"], rows))
    w("")
    w("Sample of business-key collisions (to judge whether they are duplicates or "
      "legitimate repeats):\n")
    for t, sample in R["bk_samples"].items():
        w(f"*{t}*\n")
        w(md_table(sample["cols"], sample["rows"]))
        w("")

    # ---- (b)
    w("## (b) Nulls\n")
    w(f"NOT NULL violations: {len(nn_viol)}"
      + (" (" + ", ".join(f"`{t}.{c}` {pct(r, 1)}" for t, c, r in nn_viol) + ")"
         if nn_viol else "") + ". "
      "Blank or null-like strings ('', 'nan', 'None', 'NULL', 'N/A', '-') stored as "
      "whole values: "
      + (", ".join(f"{t}.{c} ({p['blank']})" for t in tables
                   for c, p in R["prof"][t]["cols"].items() if p["blank"]) or "none")
      + ", so nulls are real SQL NULLs. Nulls rendered inside text: "
      + (", ".join(f"`{t}.{c}` ({k:,})" for t, c, k in embedded) or "none") + ".\n")
    w("How to read the tables below:")
    w("- **class**:")
    w("  - `structural`: another column predicts the null almost perfectly (>= 98% of "
      "the impurity explained).")
    w("  - `co-null`: the column is mostly null together with another column's null.")
    w(f"  - `structural + random`: always null for some values of the explainer "
      f"(groups of {MIN_GROUP} rows or more), and randomly null elsewhere.")
    w("  - `random`: nothing explains it.")
    w("- **residual**: the random-null rate outside the always-null groups. Compare it "
      "with the declared 5%.")
    w("- **by explainer / by month**: binomial dispersion index D of the residual null "
      "rate across the explainer's groups and across event months. Under the null "
      "baseline (nulls independent of the grouping), D ~ 1 with sd sqrt(2/(G-1)). "
      "|z| < 3 reads as generator noise. About 100 tests run here, so an isolated "
      "|z| of 3-4 is expected by chance.\n")
    for t in tables:
        info = R["nulls"][t]
        prof = R["prof"][t]
        w(f"### {t}\n")
        nn_cols = TABLES[t]["not_null"]
        bad = [c for c in nn_cols if prof["cols"][c]["nulls"]]
        w(f"Rows: {prof['n']:,}. Declared NOT NULL: {len(nn_cols)} columns, "
          + (f"violations in {', '.join(bad)}." if bad else "all with 0 nulls."))
        no_null = [c for c, p in prof["cols"].items() if p["nulls"] == 0 and c not in nn_cols]
        if no_null:
            w(f"Nullable but 0 nulls: {', '.join(no_null)}.")
        w("")
        if not info:
            w("No column has nulls.\n")
            continue
        rows = []
        for c, i in sorted(info.items(), key=lambda x: -x[1]["rate"]):
            decl = "**NOT NULL**" if c in nn_cols else "nullable"
            if i["cls"] == "co-null":
                aw = (f"P(null / other null)={pct(i['co_null'][0], 1)}, "
                      f"P(null / other not null)={pct(i['co_null'][1], 1)}")
            else:
                aw = ", ".join(f"{v} ({ng:,})" for v, ng in i["always_null_when"][:4]) or "-"
            rr = random_rate(i)
            rows.append([c, decl, pct(i["rate"], 1), i["cls"],
                         f"{i['explainer']} ({pct(i['explained'], 0)})", aw,
                         pct(rr, 1) if rr is not None else "-",
                         disp_str(i["disp_x"]), disp_str(i["disp_t"])])
        w(md_table(["column", "declared", "null rate", "class", "best explainer (explained)",
                    "always null when", "residual", "by explainer", "by month"], rows))
        w("")

    # ---- (c)
    w("## (c) Foreign keys and orphans\n")
    w("An orphan is a non-null FK value with no matching parent key. \"Same ID "
      "format\" counts orphans whose prefix and length match the parent's IDs, i.e. "
      "well-formed IDs that point nowhere rather than malformed values. \"By month\" "
      "tests whether orphans are spread uniformly over time (null baseline: D ~ 1).\n")
    rows = []
    for f in R["fk"]:
        rows.append([f"{f['child']}.{f['col']}", f"{f['parent']}.{f['pcol']}", fmt(f["n"]),
                     pct(1 - f["non_null"] / f["n"], 1) if f["n"] else "-", fmt(f["non_null"]),
                     fmt(f["orphans"]),
                     pct(f["rate"], 3) if f["rate"] is not None else "n/a (all null)",
                     fmt(f["orphan_distinct"]), fmt(f["orphan_same_format"]),
                     disp_str(f["disp_t"]), ", ".join(f["samples"]) or "-"])
    w(md_table(["FK", "references", "rows", "FK null rate", "non-null", "orphans",
                "orphan rate", "distinct orphan values", "same ID format", "by month",
                "sample orphans"], rows))
    w("\nCross-table consistency, for rows whose parent exists. \"Shuffled baseline\" "
      "re-links every child row to a random parent row. When observed ~ baseline, "
      "the generator does not model the relationship at all.\n")
    w(md_table(["rule", "rows checked", "violations", "rate", "shuffled baseline"],
               [[c["rule"], fmt(c["checked"]), fmt(c["violations"]),
                 pct(c["violations"] / c["checked"], 3) if c["checked"] else "-",
                 pct(c["baseline"], 3) if c["baseline"] is not None else "-"]
                for c in R["consistency"]]))
    w("\nProduct currency by owner's country:\n")
    w(md_table(["country", "currency", "products"],
               [[a, b, fmt(c)] for a, b, c in R["currency_by_country"]]))
    w("")

    # ---- (d)
    w("## (d) Late arrivals\n")
    w("lag = `process_date - CAST(event_ts AS DATE)` in days. \"Late\" means lag > 0. "
      "\"Partition mismatch\" counts rows whose `year=/month=/day=` path differs from "
      "their process_date.\n")
    rows = []
    for t, l in R["late"].items():
        rows.append([t, l["event"], fmt(l["total"]), fmt(l["late"]), fmt(l["negative"]),
                     pct(l["negative"] / l["total"], 2), l["min"], l["max"],
                     fmt(l["partition_mismatch"])])
    w(md_table(["table", "event time", "rows", "late rows (lag > 0)", "rows with lag < 0",
                "share lag < 0", "min lag", "max lag", "partition mismatch"], rows))
    w("\nLag distribution (share of rows):\n")
    labels = sorted({lag for l in R["late"].values() for lag, _ in l["dist"]})
    rows = []
    for t, l in R["late"].items():
        d = dict(l["dist"])
        rows.append([t] + [pct(d.get(x, 0) / l["total"], 2) for x in labels])
    w(md_table(["table"] + [f"lag {x}" for x in labels], rows))
    w("\n**Why lag < 0: a business-day cutoff.** The negative lags follow the hour of "
      "day exactly, not a random late or early delivery. For each table, the cutoff "
      "hour h (0-12) that maximizes agreement with `process_date = CAST(event_ts - h "
      "hours AS DATE)` was fitted:\n")
    rows = []
    for t, l in R["late"].items():
        nh = l["neg_hours"]
        neg_h = [h for h, r in nh if r > 0.99]
        rows.append([t, f"{l['cutoff_h']:02d}:00", pct(l["cutoff_agree"], 3),
                     pct(l["agree_h0"], 2),
                     (f"{min(neg_h):02d}-{max(neg_h):02d}h" if neg_h else "-"),
                     "inherited from interaction" if t in PARENT_PROCESS_DATE else "own"])
    w(md_table(["table", "fitted cutoff", "agreement with cutoff model",
                "agreement with process_date = event date", "hours always in previous day",
                "process_date source"], rows))
    sv = cons.get("satisfaction_surveys.process_date = interaction.process_date")
    tr = cons.get("call_transcripts.process_date = interaction.process_date")
    w("")
    if sv and tr:
        w(f"`call_transcripts` and `satisfaction_surveys` carry the process_date of "
          f"their interaction (mismatches: {tr['violations']:,} and "
          f"{sv['violations']:,}; shuffled baseline {pct(tr['baseline'], 1)} and "
          f"{pct(sv['baseline'], 1)}). A survey is answered hours after the call "
          "(`response_time_hours`), so it lands in a partition up to 2 days *before* "
          "its own survey_date. The null baseline for lateness: a random late-delivery "
          "process would produce some lag > 0. Across "
          f"{late_n:,} rows there are {late_tot}, so the declared late-arrival "
          "behaviour is not present in this delivery.\n")
    w("Whole-file gaps (a missing daily partition would be the other form of late "
      "arrival): "
      + "; ".join(f"`{t}` {R['hdr'][t]['files']} files, {R['hdr'][t]['first_day']} to "
                  f"{R['hdr'][t]['last_day']}, {R['hdr'][t]['missing_days']} missing days"
                  for t in R["late"]) + ".\n")
    w("Sample rows around the cutoff (lag < 0):\n")
    for t, s in R["late_samples"].items():
        w(f"*{t}*: " + "; ".join(f"`{r[0]}` event {r[1]} -> process {r[2]} "
                                 f"(lag {r[3]}, file `{Path(r[4]).name}`)" for r in s))
        w("")
    for t, l in R["late"].items():
        if l["unmatched"]:
            w(f"`{t}`: {l['unmatched']:,} rows have no matching interaction and are "
              "excluded from its lag distribution.\n")

    # ---- (e)
    w("## (e) Schema evolution\n")
    w("**Column sets.** Each raw CSV header was read directly, because the ingestion "
      "uses `union_by_name`, which would hide missing or extra columns as nulls.\n")
    rows = []
    for t in tables:
        h = R["hdr"][t]
        dict_cols = list(R["prof"][t]["cols"])
        v0 = h["variants"][0][0]
        rows.append([t, h["files"], len(h["variants"]), len(v0),
                     "yes" if v0 == dict_cols else "no (order/names differ)",
                     f"{h['bom']}/{h['files']}", f"{h['crlf']}/{h['files']}"])
    w(md_table(["table", "files", "distinct headers", "columns",
                "matches dictionary (names and order)", "UTF-8 BOM", "CRLF"], rows))
    w("")
    for t in tables:
        if len(R["hdr"][t]["variants"]) > 1:
            w(f"*{t}* header variants: " + "; ".join(
                f"{n} files {a}..{b}: {cols}" for cols, a, b, n in R["hdr"][t]["variants"]))
    w("\n**Types.** The Parquet is cast to the dictionary types, so type drift has to "
      "be measured on the raw strings. For every typed column and every key column, "
      "each raw value was reduced to a shape: digit runs -> `9`, letter runs -> `a`, "
      "IDs -> prefix + length, booleans kept verbatim. Shapes were then counted per "
      "source file. Each shape gets a status:")
    w("- *every file*: present in every file.")
    w("- *sporadic*: missing from some files but spread over the whole period "
      "(typically rare values).")
    w("- *time-bounded*: first or last seen more than 45 days inside the table's span. "
      "Only this one counts as drift.\n")
    w("The ingestion (`data/08_reporting/ingestion_cast_failures.csv`) recorded 0 "
      "TRY_CAST failures across all typed columns. Columns with more than one shape:\n")
    rows = []
    for t in tables:
        for f in R["fmt"][t]:
            if len(f["shapes"]) > 1:
                rows.append([t, f["col"], f["type"], "**yes**" if f["drift"] else "no",
                             "; ".join(f"`{s['shape']}` {pct(s['share'], 2)} of values, "
                                       f"{s['files']} files, {s['status']}"
                                       for s in f["shapes"][:4])])
    single = sum(1 for t in tables for f in R["fmt"][t] if len(f["shapes"]) <= 1)
    if rows:
        w(md_table(["table", "column", "type", "drift", "shapes"], rows))
    w(f"\n{single} typed/key columns have a single raw shape everywhere. Booleans "
      "always use `True`/`False`. Dates and timestamps always use one ISO layout. "
      "Integers are always written as floats (`701.0`), which the ingestion handles.\n")
    w("**Categorical values over time** (fact tables): values of low-cardinality "
      "columns that first appear more than 45 days after the table's first month, or "
      "disappear more than 45 days before its last month.\n")
    drift_rows = [[t, d["col"], d["value"], str(d["first"])[:7], str(d["last"])[:7],
                   fmt(d["rows"])]
                  for t in tables for d in R["cat_drift"][t]]
    w(md_table(["table", "column", "value", "first month", "last month", "rows"], drift_rows)
      if drift_rows else "None: every categorical value spans the whole period.")
    if drift_rows:
        w("\nThese are all in `campaign_sends`, and they follow the campaign calendar: a "
          "send only exists while its campaign runs (`subject` embeds the promoted "
          "product, and `Voice` sends follow the Voice campaigns). This is content "
          "seasonality, not schema evolution.")
    w("")
    # ---- value domains
    w("## Value domains vs dictionary\n")
    w("Enumerations declared in the dictionary against the observed values. "
      "\"Extra\" = observed but not declared. \"Missing\" = declared but never seen.\n")
    rows = []
    for t in tables:
        for c, v in R["dom"][t]["enum_violations"].items():
            rows.append([t, c, ", ".join(f"{a} ({b:,})" for a, b in v["extra"]) or "-",
                         ", ".join(v["missing"]) or "-"])
    w(md_table(["table", "column", "extra (rows)", "missing"], rows))
    w("\nDeclared numeric ranges:\n")
    rows = []
    for t in tables:
        for c, v in R["dom"][t]["range_violations"].items():
            s = R["dom"][t]["numeric"].get(c, {})
            rows.append([t, c, f"[{v['lo']}, {v['hi'] if v['hi'] is not None else 'inf'}]",
                         f"[{s.get('min')}, {s.get('max')}]", fmt(v["violations"])])
    w(md_table(["table", "column", "declared", "observed [min, max]", "violations"], rows))
    w("\nRow-level rules (candidates for the contracts):\n")
    rows = []
    for t in tables:
        for r in R["dom"][t]["row_rules"]:
            rows.append([t, r["rule"], fmt(r["violations"]),
                         pct(r["violations"] / R["prof"][t]["n"], 3)])
    w(md_table(["table", "rule", "violations", "rate"], rows))
    w("")

    # ---- contracts
    w("## Proposed data contracts\n")
    w("These apply to `03_primary`, which reads `02_intermediate`. \"Required\" is the "
      "dictionary NOT NULL set minus the columns that violate it in the data (listed "
      "as relaxed). Everything left in it holds 100% and can be a hard check. Allowed values are the observed sets (lists of 40 values or "
      "fewer). A new value should raise a warning, not fail the load. Numeric ranges "
      "are the observed ones; declared ranges are enforced where they exist.\n")
    for t in tables:
        c = R["contracts"][t]
        w(f"### {t}\n")
        w(f"- **Grain / PK**: {c['grain']}. Unique: {', '.join(c['unique']) or '-'}.")
        w(f"- **Dedup rule**: {c['dedup_rule']}.")
        w(f"- **Required (NOT NULL)**: {', '.join(c['required'])}.")
        if c["relaxed_not_null"]:
            w(f"- **Declared NOT NULL but relaxed**: {', '.join(c['relaxed_not_null'])}.")
        for note in c["notes"]:
            w(f"- **Note**: {note}")
        for tr in c.get("text_rules", []):
            w(f"- **Text rule**: {tr}")
        if c["nullable"]:
            w("- **Nullable**:")
            for col, nv in c["nullable"].items():
                w(f"  - `{col}` ({pct(nv['observed_null_rate'], 1)} null): {nv['rule']}")
        if c["allowed_values"]:
            w("- **Allowed values**:")
            for col, vals in c["allowed_values"].items():
                shown = ", ".join(f"`{v}`" for v in vals[:40])
                w(f"  - `{col}`: {shown}")
        declared_ranges = {k: v for k, v in c["numeric_ranges"].items() if v["declared"]}
        if c["numeric_ranges"]:
            w("- **Numeric ranges** (observed; *declared* where the dictionary gives one): "
              + "; ".join(f"`{k}` [{v['observed'][0]}, {v['observed'][1]}]"
                          + (f" *declared [{v['declared'][0]}, {v['declared'][1] if v['declared'][1] is not None else 'inf'}]*"
                             if v["declared"] else "")
                          for k, v in c["numeric_ranges"].items()))
        if c["foreign_keys"]:
            w("- **Foreign keys**:")
            for f in c["foreign_keys"]:
                rate = (pct(f["observed_orphan_rate"], 3)
                        if f["observed_orphan_rate"] is not None else "n/a")
                w(f"  - `{f['column']}` -> `{f['references']}` (orphans {rate}): {f['policy']}")
        if c["row_rules"]:
            w("- **Row rules**: " + "; ".join(c["row_rules"]))
        if "late_arrival" in c:
            la = c["late_arrival"]
            w(f"- **Late arrival**: partition key `process_date`, event time "
              f"`{la['event_time']}`; {la['rule']}.")
        w("")

    # ---- appendix: categorical values with counts
    w("## Appendix A - categorical values with counts\n")
    w("All low-cardinality columns (40 distinct values or fewer), listed before any "
      "filtering.\n")
    for t in tables:
        cats = R["dom"][t]["categorical"]
        if not cats:
            continue
        w(f"**{t}**\n")
        for c, vals in cats.items():
            w(f"- `{c}`: " + ", ".join(f"{v} ({k:,})" for v, k in vals))
        high = R["dom"][t].get("categorical_high", {})
        if high:
            w("- high-cardinality text: " + ", ".join(f"`{c}` (~{d:,} distinct)"
                                                      for c, d in high.items()))
        w("")
    w("## Appendix B - run log\n")
    w("```\n" + "\n".join(LOG) + "\n```\n")
    return "\n".join(L)


# --------------------------------------------------------------------------
def business_key_samples(results: dict) -> dict:
    out = {}
    for t, meta in TABLES.items():
        for b in results["dup"][t]["business_keys"]:
            if b["groups"] and not b.get("declared_unique"):
                keys = ", ".join(qi(c) for c in b["key"])
                show = list(dict.fromkeys(meta["pk"] + b["key"] + [
                    c for c in list(results["prof"][t]["cols"])[:8]]))[:9]
                rows = q(f"""
                    WITH k AS (SELECT {keys} FROM {t}
                               WHERE {' AND '.join(f'{qi(c)} IS NOT NULL' for c in b['key'])}
                               GROUP BY {keys} HAVING count(*) > 1
                               ORDER BY {keys} LIMIT 2)
                    SELECT {', '.join(qi(c) for c in show)} FROM {t} JOIN k USING ({keys})
                    ORDER BY {keys} LIMIT 5""")
                out[t] = dict(cols=show, rows=[[str(v)[:40] for v in r] for r in rows])
                break
    return out


def main() -> None:
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_DOCS.mkdir(parents=True, exist_ok=True)
    R: dict = {k: {} for k in ["prof", "dup", "nulls", "late", "late_samples", "hdr", "fmt",
                               "cat_drift", "dom", "contracts"]}
    for t, meta in TABLES.items():
        t0 = time.time()
        R["prof"][t] = profile(t)
        R["dup"][t] = duplicates(t, meta, R["prof"][t])
        R["nulls"][t] = null_analysis(t, meta, R["prof"][t])
        R["dom"][t] = domains(t, meta, R["prof"][t])
        R["hdr"][t] = raw_headers(t)
        R["fmt"][t] = raw_formats(t, R["prof"][t], meta)
        R["cat_drift"][t] = categorical_drift(t, meta, R["prof"][t])
        if meta["kind"] == "fact":
            R["late"][t] = late_arrivals(t, meta)
            R["late_samples"][t] = late_samples(t, meta)
        log(f"{t}: {R['prof'][t]['n']:,} rows profiled in {time.time() - t0:.1f}s")
    t0 = time.time()
    R["fk"] = orphans()
    R["consistency"] = consistency()
    R["exchange"] = exchange_completeness()
    R["currency_by_country"] = product_currency_by_country()
    R["bk_samples"] = business_key_samples(R)
    log(f"FKs and consistency in {time.time() - t0:.1f}s")
    for t, meta in TABLES.items():
        R["contracts"][t] = build_contract(t, meta, R["prof"][t], R["dup"][t], R["nulls"][t],
                                           R["fk"], R["late"].get(t), R["dom"][t])

    report = render(R)
    for d in (OUT_DOCS, OUT_DATA):
        (d / "C1.md").write_text(report, encoding="utf-8")
    (OUT_DOCS / "C1_contracts.json").write_text(
        json.dumps(R["contracts"], indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    dup_rows = sum(R["dup"][t]["pk_extra"] + R["dup"][t]["full_extra"] for t in TABLES)
    orph = sum(1 for f in R["fk"] if f["orphans"])
    late_tot = sum(R["late"][t]["late"] for t in R["late"])
    late_n = sum(R["late"][t]["total"] for t in R["late"])
    broken = [f"{f['child']}.{f['col']}" for f in R["fk"] if f["orphans"] and f["rate"] > 0.5]
    line = (f"- C1 (data quality): refuted as stated. {dup_rows} duplicates (declared ~2%); "
            f"{late_tot} late rows (process_date is a 06:00/08:00 business-day cutoff); "
            f"{sum(f['drift'] for t in TABLES for f in R['fmt'][t])} drifting columns; random nulls at round rates (5-20%), the rest structural; "
            f"{orph}/{len(R['fk'])} FKs with orphans ({', '.join(broken)} ~100% broken); "
            f"complaints.origin_interaction_id 100% null; Spanish labels, no MXN. "
            f"See docs/findings/day1/C1.md")
    for d in (OUT_DOCS, OUT_DATA):
        f = d / "FINDINGS.md"
        lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else ["# Day 1 findings", ""]
        lines = [x for x in lines if not x.startswith("- C1 ")] + [line]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
