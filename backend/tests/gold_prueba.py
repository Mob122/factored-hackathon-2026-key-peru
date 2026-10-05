"""TEST FIXTURE — not supplied data.

Gold de prueba escrito por el equipo con el esquema de docs/contracts/gold_tables.md (gold-0.2).
El cliente CLI-X7VXKV9P7ZC6, sus tarjetas 9205 y 7921 y sus 3 transacciones base son las filas
de docs/contracts/freshness_policy.md sección 6.1; los números de tarjeta son de prueba y
conservan los últimos 4. Todo lo demás (clientes CLI-FIXTURE…, tarjetas PRD-FIXTURE…,
transacciones TRX-FIXTURE…) es inventado para las pruebas y no aparece en ningún resultado.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

import duckdb
import hashlib
import hmac

LOTE_BASE = "gold-20260618T063000-0000000a"
CARGA_BASE = datetime(2026, 6, 18, 6, 40)
ENTREGA_SNAPSHOT = date(2026, 6, 17)

CLIENTE_FX = "CLI-X7VXKV9P7ZC6"
OTRO_CLIENTE = "CLI-FIXTURE00002"
CLIENTE_SUSPENDIDO = "CLI-FIXTURE00003"
CLIENTE_ESTADOS = "CLI-FIXTURE00004"
CLIENTE_CERRADO = "CLI-FIXTURE00005"

TARJETA_9205 = "PRD-S9E8FA7G5YXX"
TARJETA_7921 = "PRD-I97V8EFELBUP"
TARJETA_AJENA = "PRD-FIXTURECRD02" # De OTRO_CLIENTE, últimos 4 0044.
TARJETA_INEXISTENTE = "PRD-FIXTURENADA0"
TARJETA_SUSPENDIDO = "PRD-FIXTURECRD03"
TARJETA_BLOQUEADA = "PRD-FIXTURECRD04"
TARJETA_SUSPENDIDA = "PRD-FIXTURECRD05"
TARJETA_CERRADA = "PRD-FIXTURECRD06"
TARJETA_DEBITO = "PRD-FIXTURECRD07" # 25 transacciones recientes, para el tope de filas.
AHORRO_FX = "PRD-FIXTURESAV01"
AHORRO_CERRADO = "PRD-FIXTURESAV04"

NUMEROS = {
    TARJETA_9205: "4000000000009205",
    TARJETA_7921: "4000000000007921",
    TARJETA_AJENA: "4000000000000044",
    TARJETA_SUSPENDIDO: "4000000000003333",
    TARJETA_BLOQUEADA: "4000000000004444",
    TARJETA_SUSPENDIDA: "4000000000005555",
    TARJETA_CERRADA: "4000000000006666",
    TARJETA_DEBITO: "4000000000007777",
}

RUTA_PRODUCTOS_0618 = "products/updates/year=2026/month=06/day=18/products_20260618.csv"
RUTA_PRODUCTOS_0619 = "products/updates/year=2026/month=06/day=19/products_20260619.csv"
RUTA_TRANSACCIONES_0618 = "transactions/year=2026/month=06/day=18/transactions_20260618.csv"


def id_transaccion(n: int) -> str:
    return f"TRX-FIXTURE{n:013d}"


def huella(numero: str, clave: str) -> str:
    """El HMAC de docs/findings/gold_run.md, escrito aparte del backend para compararlo."""
    return hmac.new(clave.encode("utf-8"), numero.encode("utf-8"), hashlib.sha256).hexdigest()


def gold_base() -> Dict[str, List[dict]]:
    clientes = [
        {"customer_id": CLIENTE_FX, "country": "Colombia", "segment": "Basic", "customer_status": "Active"},
        {"customer_id": OTRO_CLIENTE, "country": "México", "segment": "Plus", "customer_status": "Active"},
        {"customer_id": CLIENTE_SUSPENDIDO, "country": "Argentina", "segment": "Basic", "customer_status": "Suspended"},
        {"customer_id": CLIENTE_ESTADOS, "country": "México", "segment": "Student", "customer_status": "Active"},
        {"customer_id": CLIENTE_CERRADO, "country": "Colombia", "segment": "Premium", "customer_status": "Closed"},
    ]
    clientes += [
        {"customer_id": f"CLI-FIXTUREB{n:04d}", "country": "México", "segment": "Basic", "customer_status": "Active"}
        for n in range(1, 26)
    ]

    def tarjeta(card_id, customer_id, tipo, estado, source_file= "products.csv"):
        return {"card_id": card_id, "customer_id": customer_id, "last4": NUMEROS[card_id][-4:], "product_type": tipo,
                "status": estado, "opening_date": date(2022, 1, 9), "expiration_date": date(2026, 1, 8),
                "last_updated": datetime(2022, 3, 29, 11, 49, 21), "source_file": source_file}

    tarjetas = [
        tarjeta(TARJETA_9205, CLIENTE_FX, "Tarjeta Crédito", "Active"),
        tarjeta(TARJETA_7921, CLIENTE_FX, "Tarjeta Crédito", "Active"),
        tarjeta(TARJETA_AJENA, OTRO_CLIENTE, "Tarjeta Crédito", "Active"),
        tarjeta(TARJETA_SUSPENDIDO, CLIENTE_SUSPENDIDO, "Tarjeta Crédito", "Active"),
        tarjeta(TARJETA_BLOQUEADA, CLIENTE_ESTADOS, "Tarjeta Crédito", "Blocked"),
        tarjeta(TARJETA_SUSPENDIDA, CLIENTE_ESTADOS, "Tarjeta Crédito", "Suspended"),
        tarjeta(TARJETA_CERRADA, CLIENTE_ESTADOS, "Tarjeta Crédito", "Closed"),
        tarjeta(TARJETA_DEBITO, CLIENTE_ESTADOS, "Tarjeta Débito", "Active"),
    ]

    def tx(transaction_id, card_id, customer_id, momento, tipo, monto, moneda, comercio, estado, codigo,
           source_file= None):
        return {"transaction_id": transaction_id, "card_id": card_id, "customer_id": customer_id,
                "transaction_datetime": momento, "process_date": (momento - timedelta(hours= 6)).date(),
                "transaction_type": tipo, "amount": Decimal(monto), "currency": moneda, "merchant_name": comercio,
                "status": estado, "response_code": codigo,
                "source_file": source_file or "transactions/year={0:%Y}/month={0:%m}/day={0:%d}/transactions_{0:%Y%m%d}.csv".format(
                    (momento - timedelta(hours= 6)).date())}

    transacciones = [
        # Filas base de freshness_policy.md 6.1.
        tx("TRX-87U97MFFGRHECCCGNRDR", TARJETA_9205, CLIENTE_FX, datetime(2026, 6, 10, 3, 26, 2), "Purchase", "1805684.49", "COP", "Tienda Don José", "Approved", "00"),
        tx("TRX-ST87M8AJLZ2GJHFR0B3F", TARJETA_9205, CLIENTE_FX, datetime(2026, 6, 6, 13, 31, 35), "Purchase", "1488737.81", "COP", "Internet Plus", "Approved", "00"),
        tx("TRX-YL1I7FAH1DJCCH428P15", TARJETA_7921, CLIENTE_FX, datetime(2025, 10, 7, 15, 48, 8), "Purchase", "722018.98", "COP", "Conciertos Live", "Approved", "00"),
        # Inventadas para las pruebas.
        tx(id_transaccion(10), TARJETA_9205, CLIENTE_FX, datetime(2026, 6, 12, 9, 0), "Purchase", "50000.00", "COP", "Uber", "Declined", "51"),
        tx(id_transaccion(11), TARJETA_9205, CLIENTE_FX, datetime(2026, 6, 11, 9, 0), "Withdrawal", "20000.00", "COP", None, "Declined", None),
        tx(id_transaccion(12), TARJETA_9205, CLIENTE_FX, datetime(2026, 4, 1, 12, 0), "Purchase", "30000.00", "COP", "Farmacia Salud", "Approved", "00"),
        tx(id_transaccion(13), TARJETA_9205, CLIENTE_FX, datetime(2026, 1, 1, 12, 0), "Purchase", "10000.00", "COP", "Farmacia Salud", "Approved", "00"),
        tx(id_transaccion(14), TARJETA_9205, CLIENTE_FX, datetime(2026, 6, 13, 10, 0), "Payment", "100000.00", "COP", None, "Reversed", "05"),
        tx(id_transaccion(15), TARJETA_9205, CLIENTE_FX, datetime(2026, 6, 14, 10, 0), "Purchase", "70000.00", "COP", "Uber", "Pending", "14"),
        tx(id_transaccion(16), TARJETA_9205, CLIENTE_FX, datetime(2026, 6, 15, 10, 0), "Purchase", "15000.00", "COP", "Uber", "Declined", "99"),
        tx(id_transaccion(2), TARJETA_AJENA, OTRO_CLIENTE, datetime(2026, 6, 10, 10, 0), "Purchase", "99.99", "USD", "Uber", "Approved", "00"),
    ]
    transacciones += [
        tx(id_transaccion(30 + n), TARJETA_DEBITO, CLIENTE_ESTADOS, datetime(2026, 6, 17, 20, 0) - timedelta(hours= 12 * n),
           "Purchase", f"{1000 + n}.00", "USD", "Cine Max", "Approved", "00")
        for n in range(25)
    ]

    def producto(product_id, customer_id, tipo, last4, estado, moneda, saldo, limite, source_file= "products.csv"):
        return {"product_id": product_id, "customer_id": customer_id, "kind": tipo, "last4": last4, "status": estado,
                "currency": moneda, "current_balance": Decimal(saldo), "credit_limit": Decimal(limite) if limite else None,
                "source_file": source_file}

    productos = [
        producto(TARJETA_9205, CLIENTE_FX, "credit_card", "9205", "Active", "COP", "1234567.89", "5000000.00"),
        producto(TARJETA_7921, CLIENTE_FX, "credit_card", "7921", "Active", "COP", "10.00", None),
        producto(AHORRO_FX, CLIENTE_FX, "savings_account", "0101", "Active", "COP", "2500000.00", None),
        producto(TARJETA_AJENA, OTRO_CLIENTE, "credit_card", "0044", "Active", "USD", "1500.00", "1000.00"),
        producto(TARJETA_SUSPENDIDO, CLIENTE_SUSPENDIDO, "credit_card", "3333", "Active", "ARS", "100.00", "1000.00"),
        producto(TARJETA_BLOQUEADA, CLIENTE_ESTADOS, "credit_card", "4444", "Blocked", "USD", "50.00", "500.00"),
        producto(TARJETA_SUSPENDIDA, CLIENTE_ESTADOS, "credit_card", "5555", "Suspended", "USD", "60.00", "500.00"),
        producto(TARJETA_CERRADA, CLIENTE_ESTADOS, "credit_card", "6666", "Closed", "USD", "0.00", "500.00"),
        producto(AHORRO_CERRADO, CLIENTE_ESTADOS, "savings_account", "0404", "Closed", "USD", "0.00", None),
    ]

    return {"customers": clientes, "cards": tarjetas, "card_transactions": transacciones, "balance_products": productos}


ENTREGAS_BASE = [("customers.csv", ENTREGA_SNAPSHOT), ("products.csv", ENTREGA_SNAPSHOT),
                 ("transactions/year=2026/month=06/day=17/transactions_20260617.csv", ENTREGA_SNAPSHOT)]

ESQUEMAS = {
    "customers": "customer_id VARCHAR, country VARCHAR, segment VARCHAR, customer_status VARCHAR",
    "cards": ("card_id VARCHAR, customer_id VARCHAR, last4 VARCHAR, card_number_hmac VARCHAR, product_type VARCHAR, "
              "status VARCHAR, opening_date DATE, expiration_date DATE, last_updated TIMESTAMP"),
    "card_transactions": ("transaction_id VARCHAR, card_id VARCHAR, customer_id VARCHAR, transaction_datetime TIMESTAMP, "
                          "process_date DATE, transaction_type VARCHAR, amount DECIMAL(15,2), currency VARCHAR, "
                          "merchant_name VARCHAR, status VARCHAR, response_code VARCHAR"),
    "balance_products": ("product_id VARCHAR, customer_id VARCHAR, kind VARCHAR, last4 VARCHAR, status VARCHAR, "
                         "currency VARCHAR, current_balance DECIMAL(15,2), credit_limit DECIMAL(15,2)"),
}
LINAJE = "source_file VARCHAR, gold_batch_id VARCHAR, gold_loaded_at TIMESTAMP"


def escribir_gold(directorio: Path, tablas: Dict[str, List[dict]], cargas: List[List[tuple]], clave_hmac: str) -> None:
    """Escribe las cuatro tablas y _load_log.parquet. `cargas` es una lista de cargas publicadas, cada
    una con sus archivos de entrada (ruta, fecha de entrega)."""
    directorio.mkdir(parents= True, exist_ok= True)
    conexion = duckdb.connect()

    for tabla, esquema in ESQUEMAS.items():
        columnas = [c.split()[0] for c in esquema.split(", ")] + ["source_file", "gold_batch_id", "gold_loaded_at"]
        conexion.execute(f"CREATE TABLE {tabla} ({esquema}, {LINAJE})")
        filas = []
        for fila in tablas[tabla]:
            fila = dict(fila)
            if tabla == "cards":
                fila["card_number_hmac"] = huella(NUMEROS[fila["card_id"]], clave_hmac)
            fila.setdefault("source_file", "customers.csv" if tabla == "customers" else "products.csv")
            fila.setdefault("gold_batch_id", LOTE_BASE)
            fila.setdefault("gold_loaded_at", CARGA_BASE)
            filas.append([fila.get(c) for c in columnas])
        conexion.executemany(f"INSERT INTO {tabla} VALUES ({', '.join('?' for _ in columnas)})", filas)
        conexion.execute(f"COPY {tabla} TO '{(directorio / f'{tabla}.parquet').as_posix()}' (FORMAT parquet)")

    conexion.execute(
        "CREATE TABLE _load_log (gold_batch_id VARCHAR, \"table\" VARCHAR, input_files STRUCT(path VARCHAR, sha256 VARCHAR, "
        "process_date DATE)[], status VARCHAR, max_process_date DATE)"
    )
    for numero, entradas in enumerate(cargas):
        archivos = ", ".join(f"{{'path': '{ruta}', 'sha256': '{'0' * 64}', 'process_date': DATE '{fecha}'}}" for ruta, fecha in entradas)
        maximo = max(fecha for _, fecha in entradas)
        for tabla in ESQUEMAS:
            conexion.execute(
                f"INSERT INTO _load_log VALUES ('gold-2026061{8 + numero}T063000-0000000{numero}', '{tabla}', [{archivos}], 'published', DATE '{maximo}')"
            )
    conexion.execute(f"COPY _load_log TO '{(directorio / '_load_log.parquet').as_posix()}' (FORMAT parquet)")
    conexion.close()


def entrega_0618(tablas: Dict[str, List[dict]]) -> Dict[str, List[dict]]:
    """Entrega del 2026-06-18 de freshness_policy.md 6.2: 7921 pasa a Blocked y hay una compra nueva en 9205."""
    nuevas = {nombre: [dict(f) for f in filas] for nombre, filas in tablas.items()}
    lote = {"gold_batch_id": "gold-20260619T063000-00000001", "gold_loaded_at": datetime(2026, 6, 19, 6, 40)}
    for nombre in ("cards", "balance_products"):
        for fila in nuevas[nombre]:
            if fila.get("card_id", fila.get("product_id")) == TARJETA_7921:
                fila.update(status= "Blocked", source_file= RUTA_PRODUCTOS_0618, **lote)
    nuevas["card_transactions"].append({
        "transaction_id": id_transaccion(1), "card_id": TARJETA_9205, "customer_id": CLIENTE_FX,
        "transaction_datetime": datetime(2026, 6, 18, 11, 42, 10), "process_date": date(2026, 6, 18),
        "transaction_type": "Purchase", "amount": Decimal("245300.00"), "currency": "COP", "merchant_name": "Farmacia Salud",
        "status": "Approved", "response_code": "00", "source_file": RUTA_TRANSACCIONES_0618, **lote,
    })
    return nuevas


def entrega_0619_9205_activa(tablas: Dict[str, List[dict]]) -> Dict[str, List[dict]]:
    """FX-7: una entrega del 2026-06-19 trae 9205 como Active."""
    nuevas = {nombre: [dict(f) for f in filas] for nombre, filas in tablas.items()}
    lote = {"gold_batch_id": "gold-20260620T063000-00000002", "gold_loaded_at": datetime(2026, 6, 20, 6, 40)}
    for nombre in ("cards", "balance_products"):
        for fila in nuevas[nombre]:
            if fila.get("card_id", fila.get("product_id")) == TARJETA_9205:
                fila.update(status= "Active", source_file= RUTA_PRODUCTOS_0619, **lote)
    return nuevas
