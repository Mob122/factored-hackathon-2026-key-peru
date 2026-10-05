"""cli.py contra la aplicación en proceso (TestClient en lugar de un servidor)."""

import builtins

import cli
import gold_golden as G
from conftest import CLAVE, crear_usuario


def test_cli_jurado_bloqueo_completo(http, agente, monkeypatch, capsys):
    """POL-AUTH-11, POL-AUTH-04, POL-ACT-02, POL-ACT-05: el chat de terminal entra como jurado con una sesión del IdP de
    prueba, pide el código con /otp, lo manda con /stepup, confirma el bloqueo, cambia el idioma y lee el audit log."""
    crear_usuario("jurado", "jurado.cli@pruebas.keyperu.example")
    monkeypatch.setattr(cli, "getpass", lambda texto: CLAVE)
    monkeypatch.setattr(cli.httpx, "Client", lambda base_url, timeout: http)

    salida = []
    entradas = iter(["Quiero bloquear mi tarjeta de débito.", "/otp", "__STEPUP__", "Sí.", "/lang pt", "Quais cartões eu tenho?", "/audit", "/salir"])

    def entrada(_texto):
        linea = next(entradas)
        if linea == "__STEPUP__":
            codigo = next(l for l in reversed(salida) if l.startswith("Código de prueba:")).split()[3]
            return f"/stepup {codigo}"
        return linea

    monkeypatch.setattr(builtins, "input", entrada)
    original_print = builtins.print
    monkeypatch.setattr(builtins, "print", lambda *a, **k: (salida.append(" ".join(str(x) for x in a)), original_print(*a, **k)))

    assert cli.main(["--jurado", "jurado.cli@pruebas.keyperu.example", "--cliente", G.D9, "--idioma", "es"]) == 0
    texto = "\n".join(salida)
    assert "Para bloquearla necesito confirmar su identidad" in texto
    assert "Identidad confirmada." in texto
    assert "Listo: su tarjeta de débito terminada en 4214 está bloqueada." in texto
    assert "Você tem um cartão: o de débito final 4214 (bloqueado)." in texto
    assert "eventos de la sesión" in texto and "policy_decision" in texto and "block_card" in texto
