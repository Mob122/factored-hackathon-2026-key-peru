"""scripts/verificar_hmac.py sobre datos de prueba (el script real lo corre el equipo contra gold)."""

import os
import re

import duckdb

import gold_prueba as g
from scripts import verificar_hmac


def _fuente(directorio, numeros):
    """Un products.parquet de prueba con product_id y product_number, como 02_intermediate."""
    ruta = directorio / "products.parquet"
    with duckdb.connect() as conexion:
        conexion.execute("CREATE TABLE products (product_id VARCHAR, product_number VARCHAR)")
        conexion.executemany("INSERT INTO products VALUES (?, ?)", list(numeros.items()))
        conexion.execute(f"COPY products TO '{ruta.as_posix()}' (FORMAT parquet)")
    return ruta


def test_verificar_hmac_cuenta_coincidencias(tmp_path):
    """POL-ESC-10: el HMAC del backend coincide con card_number_hmac de gold (docs/findings/gold_run.md, desviación 9);
    un número fuente distinto se cuenta como diferencia."""
    gold = tmp_path / "gold"
    g.escribir_gold(gold, g.gold_base(), [g.ENTREGAS_BASE], os.environ["CARD_HASH_KEY"])

    assert verificar_hmac.verificar(gold, _fuente(tmp_path, g.NUMEROS), n= 20) == (len(g.NUMEROS), len(g.NUMEROS))
    alterados = {**g.NUMEROS, g.TARJETA_9205: "4000000000001234"}
    (tmp_path / "otra").mkdir()
    assert verificar_hmac.verificar(gold, _fuente(tmp_path / "otra", alterados), n= 20) == (len(g.NUMEROS) - 1, len(g.NUMEROS))


def test_verificar_hmac_no_imprime_la_clave_ni_numeros(tmp_path, monkeypatch, capsys):
    """POL-PII-04: la salida es solo el conteo; nunca la clave, un número de tarjeta ni un id."""
    gold = tmp_path / "gold"
    g.escribir_gold(gold, g.gold_base(), [g.ENTREGAS_BASE], os.environ["CARD_HASH_KEY"])
    monkeypatch.setenv("GOLD_DIR", str(gold))

    assert verificar_hmac.main(["--fuente", str(_fuente(tmp_path, g.NUMEROS))]) == 0
    salida = capsys.readouterr().out
    assert salida.strip() == f"HMAC OK: {len(g.NUMEROS)}/{len(g.NUMEROS)}"
    assert os.environ["CARD_HASH_KEY"] not in salida and not re.search(r"\d{13,19}", salida) and "PRD-" not in salida
