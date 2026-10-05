"""Verifica que el HMAC de números de tarjeta del backend coincide con el de gold.

Toma 20 tarjetas de gold `cards`, busca su `product_number` en los datos fuente
(ml/data/02_intermediate/products.parquet) y recalcula el HMAC con CARD_HASH_KEY usando
banco.hmac_numero_tarjeta, la misma función que usa la comprobación de propiedad (POL-ESC-10).

Uso, desde backend/:  python -m scripts.verificar_hmac [--n 20] [--fuente RUTA]

Solo imprime "HMAC OK: 20/20" o la cantidad de diferencias. Nunca imprime la clave, ningún
número de tarjeta ni ningún id. Lee de backend/.env solo CARD_HASH_KEY y GOLD_DIR.
"""

from pathlib import Path
from typing import Optional, Tuple

import argparse
import os
import sys

RAIZ_BACKEND = Path(__file__).resolve().parents[1]
FUENTE_DEFECTO = RAIZ_BACKEND.parent / "ml" / "data" / "02_intermediate" / "products.parquet"


def _cargar_entorno() -> None:
    """Solo las variables necesarias, sin cargar el resto de backend/.env en el proceso."""
    import dotenv

    dotenv.load_dotenv = lambda *args, **kwargs: False # security.config no debe cargar el resto de .env.
    faltan = [nombre for nombre in ("CARD_HASH_KEY", "GOLD_DIR") if not os.environ.get(nombre)]
    if faltan:
        valores = dotenv.dotenv_values(RAIZ_BACKEND / ".env")
        for nombre in faltan:
            if valores.get(nombre):
                os.environ[nombre] = valores[nombre]
    # security.config exige estas claves al importarse; esta verificación no las usa.
    for nombre in ("SECRET_KEY", "AUDIT_KEY"):
        os.environ.setdefault(nombre, "no-se-usa-en-verificar-hmac")


def verificar(directorio_gold: Path, fuente: Path, n: int = 20) -> Tuple[int, int]:
    """Devuelve (coincidencias, revisadas). No imprime nada."""
    import duckdb
    from services import banco

    with duckdb.connect() as conexion:
        filas = conexion.execute(
            "SELECT c.card_number_hmac AS esperado, CAST(p.product_number AS VARCHAR) AS numero "
            f"FROM read_parquet('{(directorio_gold / 'cards.parquet').as_posix()}') c "
            f"JOIN read_parquet('{fuente.as_posix()}') p ON p.product_id = c.card_id "
            "ORDER BY md5(c.card_id) LIMIT ?",
            [n],
        ).fetchall()

    coincidencias = sum(1 for esperado, numero in filas if numero and banco.hmac_numero_tarjeta(numero) == esperado)
    return coincidencias, len(filas)


def main(argumentos: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description= "Verifica el HMAC de tarjetas del backend contra gold.")
    parser.add_argument("--n", type= int, default= 20)
    parser.add_argument("--fuente", type= Path, default= FUENTE_DEFECTO)
    opciones = parser.parse_args(argumentos)

    _cargar_entorno()
    if not os.environ.get("CARD_HASH_KEY"):
        print("Falta CARD_HASH_KEY en backend/.env.")
        return 1
    if not opciones.fuente.is_file():
        print(f"No se encontró el archivo fuente de productos: {opciones.fuente}")
        return 1

    from services import banco

    try:
        directorio_gold = banco.resolver_directorio_gold(os.environ.get("GOLD_DIR"))
    except banco.ErrorHerramienta:
        print("No se encontraron las tablas gold (revise GOLD_DIR en backend/.env).")
        return 1

    coincidencias, revisadas = verificar(directorio_gold, opciones.fuente, opciones.n)
    if revisadas == 0:
        print("HMAC: no se encontró ninguna tarjeta de gold en el archivo fuente.")
        return 1
    if coincidencias == revisadas:
        print(f"HMAC OK: {coincidencias}/{revisadas}")
        return 0
    print(f"HMAC con diferencias: {revisadas - coincidencias} de {revisadas} no coinciden")
    return 1


if __name__ == "__main__":
    sys.exit(main())
