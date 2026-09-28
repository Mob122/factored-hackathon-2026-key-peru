"""Tests for the A3 card-charge detectors.

Fixtures are tiny typed tables with one scenario per transaction_id prefix, so
each test reads as a declared example of what a detector must and must not flag.
"""

from datetime import datetime, timedelta

import duckdb
import pytest

from banking_cs.detectors import (
    build_card_purchases_query,
    build_foreign_currency_query,
    build_habitual_merchant_query,
    build_preauthorization_query,
    build_repeat_charge_query,
    build_shuffled_column_query,
)
from banking_cs.pipelines.data_ingestion.schemas import TABLE_SCHEMAS

T0 = datetime(2024, 3, 1, 12, 0, 0)

PRODUCTS = [
    # product_id, customer_id, product_type, currency
    ("PRD-CC", "CLI-CO", "Tarjeta Crédito", "COP"),
    ("PRD-DC", "CLI-CO", "Tarjeta Débito", "COP"),
    ("PRD-USD", "CLI-CO", "Tarjeta Crédito", "USD"),
    ("PRD-SAV", "CLI-CO", "Cuenta Ahorro", "COP"),
    ("PRD-MX", "CLI-MX", "Tarjeta Crédito", "USD"),
    ("PRD-XX", "CLI-XX", "Tarjeta Débito", "USD"),
]
CUSTOMERS = [("CLI-CO", "Colombia"), ("CLI-MX", "México"), ("CLI-XX", "Chile")]
OWNER = {p[0]: p[1] for p in PRODUCTS}
CURRENCY = {p[0]: p[3] for p in PRODUCTS}


def tx(tid, minutes, product="PRD-CC", merchant="Uber", amount=100.0, **kw):
    """One transactions row; minutes are relative to T0."""
    row = dict.fromkeys(TABLE_SCHEMAS["transactions"])
    row.update(
        transaction_id=tid,
        transaction_date=T0 + timedelta(minutes=minutes),
        process_date=(T0 + timedelta(minutes=minutes)).date(),
        product_id=product,
        customer_id=OWNER[product],
        transaction_type="Purchase",
        amount=amount,
        currency=CURRENCY[product],
        channel="POS",
        merchant_name=merchant,
        transaction_country="Colombia",
        transaction_status="Approved",
        is_fraud=False,
        source_file="fixture.csv",
    )
    row.update(kw)
    return row


DAY = 24 * 60
TRANSACTIONS = [
    # --- scope: only card purchases are kept
    tx("SCOPE-SAV", 0, product="PRD-SAV"),
    tx("SCOPE-WDR", 0, transaction_type="Withdrawal", merchant=None),
    # --- preauthorization
    tx("PRE-1-PEND", 0, merchant="Hotel", transaction_status="Pending"),
    tx("PRE-1-REV", 120, merchant="Hotel", transaction_status="Reversed"),
    tx("PRE-2-PEND", 0, merchant="Gasolinera", amount=50, transaction_status="Pending"),
    tx("PRE-2-SET", 30, merchant="Gasolinera", amount=43.2),
    tx("PRE-3-PEND", 0, merchant="Cine", transaction_status="Pending"),
    tx("PRE-3-LATE", 8 * DAY, merchant="Cine"),  # outside 7-day horizon
    tx("PRE-4-PEND", 0, merchant="Teatro", transaction_status="Pending"),
    tx("PRE-4-OTHER", 60, product="PRD-DC", merchant="Teatro"),  # other product
    tx("PRE-5-BEFORE", -60, merchant="Farmacia"),  # earlier, not later
    tx("PRE-5-PEND", 0, merchant="Farmacia", transaction_status="Pending"),
    # --- repeat charges (merchant 'Tienda', amount 77)
    tx("DUP-A", 10 * DAY, merchant="Tienda", amount=77),
    tx("DUP-A", 10 * DAY, merchant="Tienda", amount=77),  # exact duplicate row
    tx("REP-B", 10 * DAY + 5, merchant="Tienda", amount=77),  # 5 min later
    tx("REP-C", 10 * DAY + 16, merchant="Tienda", amount=77),  # 11 min after B
    tx("REP-D", 10 * DAY + 6, merchant="Tienda", amount=78),  # other amount
    tx("REP-E", 10 * DAY + 7, product="PRD-DC", merchant="Tienda", amount=77),
    # --- habitual merchant (customer-level, across both card products)
    tx("HAB-1", 20 * DAY, merchant="Super"),
    tx("HAB-2", 21 * DAY, product="PRD-DC", merchant="Super"),
    tx("HAB-3", 22 * DAY, merchant="Super"),
    tx("HAB-4a", 23 * DAY, merchant="Super"),
    tx("HAB-4b", 23 * DAY, merchant="Super", amount=5),  # same timestamp as 4a
    tx("HAB-5", 24 * DAY, merchant="Super"),
    tx("HAB-NULL", 25 * DAY, merchant=None),
    # --- currency
    tx("CUR-USD", 30 * DAY, product="PRD-USD", merchant="Amazon"),
    tx("CUR-MX", 30 * DAY, product="PRD-MX", merchant="Amazon"),
    tx("CUR-XX", 30 * DAY, product="PRD-XX", merchant="Amazon"),
]


@pytest.fixture
def con():
    c = duckdb.connect()
    cols = {**TABLE_SCHEMAS["transactions"], "source_file": "VARCHAR"}
    c.sql(
        "create table transactions ("
        + ", ".join(f"{k} {v}" for k, v in cols.items())
        + ")"
    )
    c.executemany(
        f"insert into transactions values ({', '.join('?' * len(cols))})",
        [[r[k] for k in cols] for r in TRANSACTIONS],
    )
    c.sql(
        "create table products as select * from (values "
        + ", ".join(f"('{p}', '{cu}', '{t}', '{cur}')" for p, cu, t, cur in PRODUCTS)
        + ") v(product_id, customer_id, product_type, currency)"
    )
    c.sql(
        "create table customers as select * from (values "
        + ", ".join(f"('{cu}', '{co}')" for cu, co in CUSTOMERS)
        + ") v(customer_id, country)"
    )
    c.sql(
        "create table src as "
        + build_card_purchases_query("transactions", "products", "customers")
    )
    return c


def flags(con, query: str, *cols: str) -> dict[str, tuple]:
    """transaction_id -> flag tuple; exact duplicates get a '#n' suffix."""
    rows = con.sql(
        f"""
        select s.transaction_id, {", ".join(f"d.{c}" for c in cols)}
        from src s join ({query}) d using (row_key) order by s.row_key
        """
    ).fetchall()
    out: dict[str, tuple] = {}
    for tid, *vals in rows:
        key = tid if tid not in out else f"{tid}#2"
        out[key] = tuple(vals) if len(vals) > 1 else vals[0]
    return out


def test_card_purchases_scope(con):
    ids = [r[0] for r in con.sql("select transaction_id from src").fetchall()]
    assert "SCOPE-SAV" not in ids
    assert "SCOPE-WDR" not in ids
    assert ids.count("DUP-A") == 2  # exact duplicates are kept
    assert len(ids) == len(TRANSACTIONS) - 2
    keys = con.sql("select count(distinct row_key), count(*) from src").fetchone()
    assert keys[0] == keys[1]


def test_every_detector_returns_one_row_per_input_row(con):
    n = con.sql("select count(*) from src").fetchone()[0]
    for q in [
        build_preauthorization_query("src"),
        build_foreign_currency_query("src"),
        build_repeat_charge_query("src"),
        build_habitual_merchant_query("src"),
    ]:
        assert con.sql(f"select count(*), count(distinct row_key) from ({q})").fetchone() == (n, n)


class TestPreauthorization:
    COLS = ("is_preauth", "preauth_reversed", "preauth_settled", "preauth_same_amount",
            "is_preauth_followup")

    def test_pending_then_reversed(self, con):
        f = flags(con, build_preauthorization_query("src"), *self.COLS)
        assert f["PRE-1-PEND"] == (True, True, False, True, False)
        assert f["PRE-1-REV"] == (False, False, False, False, True)

    def test_pending_then_settled_with_other_amount(self, con):
        f = flags(con, build_preauthorization_query("src"), *self.COLS)
        assert f["PRE-2-PEND"] == (True, False, True, False, False)
        assert f["PRE-2-SET"][4] is True

    def test_non_matches(self, con):
        f = flags(con, build_preauthorization_query("src"), *self.COLS)
        assert f["PRE-3-PEND"][0] is False  # outside horizon
        assert f["PRE-4-PEND"][0] is False  # other product
        assert f["PRE-5-PEND"][0] is False  # match is earlier
        assert f["PRE-5-BEFORE"][4] is False

    def test_horizon_is_a_parameter(self, con):
        f = flags(con, build_preauthorization_query("src", horizon_minutes=9 * DAY),
                  "is_preauth")
        assert f["PRE-3-PEND"] is True
        f = flags(con, build_preauthorization_query("src", horizon_minutes=60),
                  "is_preauth")
        assert f["PRE-1-PEND"] is False
        assert f["PRE-2-PEND"] is True


class TestForeignCurrency:
    def test_flags(self, con):
        f = flags(con, build_foreign_currency_query("src"),
                  "local_currency", "is_foreign_currency")
        assert f["HAB-1"] == ("COP", False)
        assert f["CUR-USD"] == ("COP", True)
        assert f["CUR-MX"] == ("MXN", True)  # MXN absent from data: always foreign
        assert f["CUR-XX"] == (None, None)  # unmapped country

    def test_custom_mapping(self, con):
        f = flags(con, build_foreign_currency_query("src", {"México": "USD"}),
                  "is_foreign_currency")
        assert f["CUR-MX"] is False
        assert f["HAB-1"] is None


class TestRepeatCharge:
    def test_exact_duplicate_is_not_a_repeat_charge(self, con):
        f = flags(con, build_repeat_charge_query("src"),
                  "is_exact_duplicate", "is_repeat_charge")
        assert f["DUP-A"] == (False, False)
        assert f["DUP-A#2"] == (True, False)

    def test_distinct_ids_within_window(self, con):
        f = flags(con, build_repeat_charge_query("src"), "is_repeat_charge")
        assert f["REP-B"] is True  # 5 min after DUP-A
        assert f["REP-C"] is False  # 11 min after B, 16 after A
        assert f["REP-D"] is False  # different amount
        assert f["REP-E"] is False  # different product

    def test_window_is_a_parameter(self, con):
        f = flags(con, build_repeat_charge_query("src", window_minutes=11),
                  "is_repeat_charge")
        assert f["REP-C"] is True

    def test_same_timestamp_flags_only_one_side(self, con):
        con.sql("update src set transaction_date = transaction_date - interval 5 minute "
                "where transaction_id = 'REP-B'")
        f = flags(con, build_repeat_charge_query("src"), "is_repeat_charge")
        assert f["REP-B"] is True  # 'REP-B' > 'DUP-A' breaks the tie
        assert f["DUP-A"] is False


class TestHabitualMerchant:
    def test_prior_counts_and_flag(self, con):
        f = flags(con, build_habitual_merchant_query("src"),
                  "prior_purchases_at_merchant", "is_habitual_merchant")
        assert f["HAB-1"] == (0, False)
        assert f["HAB-2"] == (1, False)  # other card, same customer
        assert f["HAB-3"] == (2, False)
        assert f["HAB-4a"] == (3, True)
        assert f["HAB-4b"] == (3, True)  # same timestamp is not 'prior'
        assert f["HAB-5"] == (5, True)
        assert f["HAB-NULL"] == (0, False)

    def test_min_prior_is_a_parameter(self, con):
        f = flags(con, build_habitual_merchant_query("src", min_prior=5),
                  "is_habitual_merchant")
        assert f["HAB-4a"] is False
        assert f["HAB-5"] is True


class TestShuffledColumn:
    def test_keeps_rows_and_per_product_timestamps(self, con):
        q = build_shuffled_column_query("src", seed=1)
        assert con.sql(f"select count(*) from ({q})").fetchone()[0] == \
            con.sql("select count(*) from src").fetchone()[0]
        real = con.sql("select product_id, list_sort(list(transaction_date)) "
                       "from src group by 1 order by 1").fetchall()
        shuf = con.sql(f"select product_id, list_sort(list(transaction_date)) "
                       f"from ({q}) group by 1 order by 1").fetchall()
        assert real == shuf

    def test_deterministic_and_seed_dependent(self, con):
        def order(seed):
            q = build_shuffled_column_query("src", seed=seed)
            return con.sql(f"select row_key, transaction_date from ({q}) "
                           "order by row_key").fetchall()
        assert order(1) == order(1)
        assert any(order(s) != order(1) for s in (2, 3, 4))

    def test_global_permutation_of_another_column(self, con):
        q = build_shuffled_column_query("src", seed=7, column="merchant_name",
                                        partition_by=None)
        real = con.sql("select merchant_name, count(*) from src group by 1 "
                       "order by 1 nulls last").fetchall()
        shuf = con.sql(f"select merchant_name, count(*) from ({q}) group by 1 "
                       "order by 1 nulls last").fetchall()
        assert real == shuf
        same = con.sql(f"select count(*) from src s join ({q}) q using (row_key) "
                       "where s.transaction_date = q.transaction_date").fetchone()[0]
        assert same == con.sql("select count(*) from src").fetchone()[0]
