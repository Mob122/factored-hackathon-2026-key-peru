"""
'gold' pipeline: 02_intermediate -> the four tables read by the mock bank
(03_primary/gold), with quality checks, quarantine and a load log.

Contracts: docs/contracts/gold_tables.md (gold-0.2) and
docs/contracts/freshness_policy.md (fresh-0.2).
"""

from kedro.pipeline import Node, Pipeline

from .checks import run_checks
from .nodes import (
    plan_load,
    publish_gold,
    stage_card_transactions,
    stage_customers,
    stage_products,
    upsert_tables,
)


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            Node(
                func=plan_load,
                inputs=[
                    "customers_intermediate",
                    "products_intermediate",
                    "transactions_intermediate",
                    "gold_previous",
                    "params:gold",
                ],
                outputs="gold_batch",
                name="plan_gold_load",
            ),
            Node(
                func=stage_customers,
                inputs=["customers_intermediate", "gold_batch"],
                outputs="gold_staged_customers",
                name="stage_customers",
            ),
            Node(
                func=stage_products,
                inputs=["products_intermediate", "card_hash_key", "gold_batch"],
                outputs=["gold_staged_cards", "gold_staged_balance_products"],
                name="stage_products",
            ),
            Node(
                func=stage_card_transactions,
                inputs=[
                    "transactions_intermediate",
                    "products_intermediate",
                    "gold_batch",
                ],
                outputs="gold_staged_card_transactions",
                name="stage_card_transactions",
            ),
            Node(
                func=upsert_tables,
                inputs=[
                    "gold_previous",
                    "gold_staged_customers",
                    "gold_staged_cards",
                    "gold_staged_card_transactions",
                    "gold_staged_balance_products",
                    "gold_batch",
                ],
                outputs="gold_candidate",
                name="upsert_gold",
            ),
            Node(
                func=run_checks,
                inputs=["gold_candidate", "products_intermediate", "gold_batch"],
                outputs="gold_check_results",
                name="check_gold",
            ),
            Node(
                func=publish_gold,
                inputs=[
                    "gold_candidate",
                    "gold_check_results",
                    "gold_previous",
                    "gold_batch",
                    "params:data_ingestion.raw_root",
                ],
                outputs="gold_store",
                name="publish_gold",
            ),
        ]
    )
