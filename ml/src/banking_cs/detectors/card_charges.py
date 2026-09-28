"""Detectors for benign causes of 'unrecognized' card charges (hypothesis A3).

Every builder takes the name of a relation (table, view or CTE) shaped like the
output of `build_card_purchases_query` and returns a DuckDB SQL string with
exactly one row per input row, keyed by `row_key`, plus the detector's flag
columns. Flags are never null (a row that cannot be evaluated is False) unless
documented otherwise, so flags can be summed directly as prevalence numerators.

Required source columns: row_key, transaction_id, transaction_date, product_id,
customer_id, merchant_name, amount, currency, transaction_status, and
customer_country (foreign currency only). Exact-duplicate detection also uses
every column of the raw transactions schema.
"""

from __future__ import annotations

from banking_cs.pipelines.data_ingestion.schemas import TABLE_SCHEMAS

CARD_PRODUCT_TYPES = ("Tarjeta Crédito", "Tarjeta Débito")
PURCHASE_TYPE = "Purchase"
# Legal tender by customer country. MXN never appears in the data (C1), so every
# Mexican purchase is 'foreign' under this definition; see the A3 report.
LOCAL_CURRENCY = {"Argentina": "ARS", "Colombia": "COP", "México": "MXN"}
TRANSACTION_COLUMNS = tuple(TABLE_SCHEMAS["transactions"])


def _sql_list(values) -> str:
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)


def build_card_purchases_query(
    transactions: str,
    products: str,
    customers: str,
    card_product_types: tuple[str, ...] = CARD_PRODUCT_TYPES,
    purchase_type: str = PURCHASE_TYPE,
) -> str:
    """Purchases on credit or debit card products, with a deterministic row_key.

    All rows are kept, including exact duplicates; `row_key` tells them apart.
    """
    return f"""
        select
            row_number() over (
                order by t.transaction_id, t.transaction_date, t.source_file
            ) as row_key,
            t.*,
            p.product_type,
            cu.country as customer_country
        from {transactions} t
        join {products} p using (product_id)
        left join {customers} cu on cu.customer_id = t.customer_id
        where p.product_type in ({_sql_list(card_product_types)})
          and t.transaction_type = '{purchase_type}'
    """


def build_preauthorization_query(source: str, horizon_minutes: int = 7 * 24 * 60) -> str:
    """Pending purchase later Reversed or settled (Approved) on the same product
    and merchant within `horizon_minutes`.

    Columns:
      is_preauth           the Pending row has a later Reversed/Approved match
      preauth_reversed     ... and at least one match is Reversed
      preauth_settled      ... and at least one match is Approved
      preauth_same_amount  ... and at least one match has the same amount
      is_preauth_followup  the row is the Reversed/Approved match of a Pending row
    """
    return f"""
        with pairs as (
            select p.row_key as pending_key, l.row_key as later_key,
                   l.transaction_status as later_status,
                   l.amount = p.amount as same_amount
            from {source} p
            join {source} l
              on l.product_id = p.product_id
             and l.merchant_name = p.merchant_name
             and l.transaction_date > p.transaction_date
             and l.transaction_date
                 <= p.transaction_date + to_minutes({int(horizon_minutes)})
             and l.transaction_status in ('Reversed', 'Approved')
            where p.transaction_status = 'Pending'
        ),
        anchors as (
            select pending_key as row_key,
                   bool_or(later_status = 'Reversed') as preauth_reversed,
                   bool_or(later_status = 'Approved') as preauth_settled,
                   bool_or(same_amount) as preauth_same_amount
            from pairs group by 1
        ),
        followups as (select distinct later_key as row_key from pairs)
        select s.row_key,
               a.row_key is not null as is_preauth,
               coalesce(a.preauth_reversed, false) as preauth_reversed,
               coalesce(a.preauth_settled, false) as preauth_settled,
               coalesce(a.preauth_same_amount, false) as preauth_same_amount,
               f.row_key is not null as is_preauth_followup
        from {source} s
        left join anchors a using (row_key)
        left join followups f using (row_key)
    """


def build_foreign_currency_query(
    source: str, local_currency: dict[str, str] | None = None
) -> str:
    """Purchase currency differs from the customer's local currency.

    `is_foreign_currency` is null when the customer's country has no mapping.
    """
    mapping = local_currency or LOCAL_CURRENCY
    cases = " ".join(
        f"when {_sql_list([country])} then {_sql_list([cur])}"
        for country, cur in mapping.items()
    )
    return f"""
        select row_key,
               case customer_country {cases} end as local_currency,
               currency <> local_currency as is_foreign_currency
        from {source}
    """


def build_repeat_charge_query(source: str, window_minutes: int = 10) -> str:
    """Same product, merchant and amount within `window_minutes`.

    Columns:
      is_exact_duplicate  the row is an extra copy of an identical row (every
                          raw transactions column equal); the first copy is False
      is_repeat_charge    a row with a *different* transaction_id, same product,
                          merchant and amount, occurred at most `window_minutes`
                          earlier (ties broken by transaction_id), so only the
                          second and later charges are flagged
    """
    cols = ", ".join(TRANSACTION_COLUMNS)
    return f"""
        with dup as (
            select row_key,
                   row_number() over (partition by {cols} order by row_key) > 1
                       as is_exact_duplicate
            from {source}
        ),
        rep as (
            select distinct b.row_key
            from {source} a
            join {source} b
              on a.product_id = b.product_id
             and a.merchant_name = b.merchant_name
             and a.amount = b.amount
             and a.transaction_id <> b.transaction_id
             and b.transaction_date >= a.transaction_date
             and b.transaction_date
                 <= a.transaction_date + to_minutes({int(window_minutes)})
             and (b.transaction_date > a.transaction_date
                  or b.transaction_id > a.transaction_id)
        )
        select s.row_key,
               d.is_exact_duplicate,
               r.row_key is not null as is_repeat_charge
        from {source} s
        join dup d using (row_key)
        left join rep r using (row_key)
    """


def build_habitual_merchant_query(source: str, min_prior: int = 3) -> str:
    """Customer made at least `min_prior` earlier purchases at the same merchant.

    Earlier means a strictly smaller transaction_date, across all of the
    customer's rows in `source`. Rows without merchant are never habitual.
    """
    return f"""
        with ranked as (
            select row_key,
                   case when merchant_name is null then 0
                        else rank() over (
                            partition by customer_id, merchant_name
                            order by transaction_date
                        ) - 1
                   end as prior_purchases_at_merchant
            from {source}
        )
        select row_key, prior_purchases_at_merchant,
               prior_purchases_at_merchant >= {int(min_prior)} as is_habitual_merchant
        from ranked
    """


def build_shuffled_column_query(
    source: str,
    seed: int,
    column: str = "transaction_date",
    partition_by: str | None = "product_id",
) -> str:
    """Null baseline: permute `column` among the rows of each partition.

    The default permutes timestamps within each product: every product keeps its
    exact set of timestamps and only their pairing with merchant, amount, status,
    etc. is randomized. `partition_by=None` permutes across all rows. The
    permutation is deterministic for a given seed.
    """
    part = f"partition by {partition_by}" if partition_by else ""
    keys = f"{partition_by}, _k" if partition_by else "_k"
    return f"""
        with shuffled as (
            select * exclude ({column}),
                   row_number() over (
                       {part} order by hash(row_key, {int(seed)}), row_key
                   ) as _k
            from {source}
        ),
        vals as (
            select {partition_by + "," if partition_by else ""} {column},
                   row_number() over ({part} order by row_key) as _k
            from {source}
        )
        select s.* exclude (_k), v.{column}
        from shuffled s join vals v using ({keys})
    """
