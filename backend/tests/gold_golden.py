"""TEST FIXTURE — not supplied data.

Filas de los clientes de las conversaciones golden (docs/golden_conversations.md, golden-0.5) para
reproducirlas de punta a punta sin ml/data/. Los ids, últimos 4, tipos, estados, transacciones y
saldos citados en esas conversaciones se copian del documento; los números de tarjeta son de prueba
(conservan los últimos 4) y los saldos que el documento no cita son inventados. Se agregan al gold
de prueba de tests/gold_prueba.py.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List

import gold_prueba as base

D1, D5, D7, D8 = "CLI-5B9VSCP2GSML", "CLI-AYAHYQEG16BZ", "CLI-GHRMPXT32BKK", "CLI-EHVV6YJ6SL5W"
D9, D10, D11, D12 = "CLI-LD6QVNCSTR43", "CLI-JAS4V4U7H60H", "CLI-SQJOCEDJJNCZ", "CLI-AN7KXGR09TB2"

CLIENTES = [
    (D1, "México", "Basic"), (D5, "México", "Basic"), (D7, "México", "Basic"), (D8, "Colombia", "Basic"),
    (D9, "Colombia", "Plus"), (D10, "México", "Basic"), (D11, "Colombia", "Basic"), (D12, "México", "Basic"),
]
# No es una persona golden: tarjeta de crédito y cuenta de ahorros con los mismos últimos 4 (POL-ANS-08, GQ-29).
MISMOS_4 = "CLI-FIXTURE00006"
CLIENTES.append((MISMOS_4, "Argentina", "Basic"))

# (card_id, customer_id, last4, tipo, estado)
TARJETAS = [
    ("PRD-CF0H6VD9E4WW", D1, "6873", "Tarjeta Crédito", "Active"),
    ("PRD-3IUDDGZBOCEE", D1, "6898", "Tarjeta Débito", "Active"),
    ("PRD-ND3SNM4M4IOU", D1, "0727", "Tarjeta Crédito", "Blocked"),
    ("PRD-O6A7T916ZJ2N", D5, "1883", "Tarjeta Débito", "Active"),
    ("PRD-TGMAN4NBB814", D5, "4950", "Tarjeta Crédito", "Active"),
    ("PRD-UBSN35P9UX26", D7, "2771", "Tarjeta Crédito", "Active"),
    ("PRD-VIWI5SXFUTC6", D7, "7167", "Tarjeta Débito", "Active"),
    ("PRD-Y4G07XYWXFJ5", D8, "0245", "Tarjeta Crédito", "Active"),
    ("PRD-LA9ABZREIOZF", D8, "7131", "Tarjeta Débito", "Active"),
    ("PRD-F0L5Y3POU66F", D8, "8283", "Tarjeta Débito", "Active"),
    ("PRD-RQMV87CJAOKW", D8, "7663", "Tarjeta Crédito", "Blocked"),
    ("PRD-V9G3LK6DKBNG", D9, "4214", "Tarjeta Débito", "Active"),
    ("PRD-66D0I8GLUV1W", D10, "0044", "Tarjeta Crédito", "Active"),
    ("PRD-261UZFW569GS", D10, "7042", "Tarjeta Crédito", "Active"),
    ("PRD-5YMLZ8YCF4PH", D11, "5070", "Tarjeta Crédito", "Active"),
    ("PRD-ZQO1H0MW0E1E", D11, "5419", "Tarjeta Débito", "Closed"),
    ("PRD-HATYL2FAWGX5", D12, "2960", "Tarjeta Crédito", "Active"),
    ("PRD-F5265QDY6AWJ", D12, "7858", "Tarjeta Crédito", "Active"),
    ("PRD-XA1FQKRTRLE7", D12, "2952", "Tarjeta Crédito", "Blocked"),
    ("PRD-FIXTURECRD11", MISMOS_4, "1111", "Tarjeta Crédito", "Active"),
]
NUMEROS = {card_id: f"451900000000{last4}" for card_id, _, last4, _, _ in TARJETAS}
NUMERO_TARJETA_D10_0044 = NUMEROS["PRD-66D0I8GLUV1W"] # El número que se escribe en el diálogo 7.

# (product_id, customer_id, kind, last4, estado, moneda, saldo, límite)
PRODUCTOS = [
    ("PRD-CF0H6VD9E4WW", D1, "credit_card", "6873", "Active", "USD", "300.00", "2000.00"),
    ("PRD-ND3SNM4M4IOU", D1, "credit_card", "0727", "Blocked", "USD", "0.00", "1000.00"),
    ("PRD-TGMAN4NBB814", D5, "credit_card", "4950", "Active", "USD", "800.00", "3000.00"),
    ("PRD-UBSN35P9UX26", D7, "credit_card", "2771", "Active", "USD", "120.00", "1500.00"),
    ("PRD-Y4G07XYWXFJ5", D8, "credit_card", "0245", "Active", "COP", "1000000.00", "5000000.00"),
    ("PRD-RQMV87CJAOKW", D8, "credit_card", "7663", "Blocked", "COP", "0.00", "5000000.00"),
    ("PRD-66D0I8GLUV1W", D10, "credit_card", "0044", "Active", "USD", "50.00", "900.00"),
    ("PRD-261UZFW569GS", D10, "credit_card", "7042", "Active", "USD", "75.00", "900.00"),
    ("PRD-5YMLZ8YCF4PH", D11, "credit_card", "5070", "Active", "COP", "8741863.41", "84596594.05"),
    ("PRD-E6VB3HXXNL29", D11, "savings_account", "1317", "Active", "COP", "17646484.21", None),
    ("PRD-TXH6UOOMY8ON", D12, "savings_account", "2700", "Active", "USD", "3447.34", None),
    ("PRD-HATYL2FAWGX5", D12, "credit_card", "2960", "Active", "USD", "500.00", "3000.00"),
    ("PRD-F5265QDY6AWJ", D12, "credit_card", "7858", "Active", "USD", "1126.12", "5366.87"),
    ("PRD-XA1FQKRTRLE7", D12, "credit_card", "2952", "Blocked", "USD", "10.00", "1000.00"),
    ("PRD-FIXTURECRD11", MISMOS_4, "credit_card", "1111", "Active", "ARS", "25000.00", "100000.00"),
    ("PRD-FIXTURESAV11", MISMOS_4, "savings_account", "1111", "Active", "ARS", "123456.78", None),
]

# (transaction_id, card_id, customer_id, fecha y hora, tipo, monto, moneda, comercio, estado, código)
TRANSACCIONES = [
    ("TRX-0OQVC3BDVLGG2VDSXTFM", "PRD-CF0H6VD9E4WW", D1, datetime(2026, 6, 6, 19, 43, 19), "Purchase", "127.37", "USD", "Uber", "Declined", "54"),
    ("TRX-FIXTUREG000000000101", "PRD-CF0H6VD9E4WW", D1, datetime(2026, 6, 2, 12, 0), "Purchase", "45.00", "USD", "Cine Max", "Approved", "00"),
    ("TRX-KFN7RMGYX8DR5AYBQ4QL", "PRD-TGMAN4NBB814", D5, datetime(2026, 6, 1, 4, 20), "Purchase", "392.25", "USD", "Empresa Telefónica", "Approved", "00"),
    ("TRX-FIXTUREG000000000102", "PRD-TGMAN4NBB814", D5, datetime(2026, 6, 10, 9, 30), "Purchase", "15.00", "USD", "Café Central", "Approved", "00"),
    ("TRX-FIXTUREG000000000103", "PRD-UBSN35P9UX26", D7, datetime(2026, 6, 12, 18, 0), "Purchase", "60.00", "USD", "Cine Max", "Approved", "00"),
    ("TRX-FIXTUREG000000000104", "PRD-261UZFW569GS", D10, datetime(2026, 6, 14, 11, 0), "Purchase", "22.50", "USD", "Farmacia Salud", "Approved", "00"),
]


def tablas() -> Dict[str, List[dict]]:
    datos = base.gold_base()
    datos["customers"] += [{"customer_id": c, "country": pais, "segment": segmento, "customer_status": "Active"}
                           for c, pais, segmento in CLIENTES]
    datos["cards"] += [{"card_id": card_id, "customer_id": cliente, "last4": last4, "product_type": tipo, "status": estado,
                        "opening_date": datetime(2022, 1, 1).date(), "expiration_date": datetime(2028, 9, 16).date(),
                        "last_updated": datetime(2023, 1, 1), "source_file": "products.csv"}
                       for card_id, cliente, last4, tipo, estado in TARJETAS]
    datos["balance_products"] += [{"product_id": p, "customer_id": c, "kind": k, "last4": l4, "status": e, "currency": m,
                                   "current_balance": Decimal(s), "credit_limit": Decimal(lim) if lim else None, "source_file": "products.csv"}
                                  for p, c, k, l4, e, m, s, lim in PRODUCTOS]
    datos["card_transactions"] += [{
        "transaction_id": tx, "card_id": card, "customer_id": cliente, "transaction_datetime": momento,
        "process_date": (momento - timedelta(hours= 6)).date(), "transaction_type": tipo, "amount": Decimal(monto),
        "currency": moneda, "merchant_name": comercio, "status": estado, "response_code": codigo,
        "source_file": "transactions/year={0:%Y}/month={0:%m}/day={0:%d}/transactions_{0:%Y%m%d}.csv".format((momento - timedelta(hours= 6)).date()),
    } for tx, card, cliente, momento, tipo, monto, moneda, comercio, estado, codigo in TRANSACCIONES]
    return datos


def escribir(directorio, clave_hmac: str) -> None:
    base.escribir_gold(directorio, tablas(), [base.ENTREGAS_BASE], clave_hmac, numeros= {**base.NUMEROS, **NUMEROS})
