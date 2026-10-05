"""Chat de terminal contra la API en ejecución (uvicorn main:app --port 8000).

Dos formas de entrar:
  python cli.py --usuario cli-sqjocedjjncz@clientes.keyperu.example       usuario sembrado (pide la contraseña)
  python cli.py --jurado jurado@keyperu.example --cliente CLI-SQJOCEDJJNCZ   jurado + sesión del IdP de prueba

Comandos:
  /stepup <código>   envía el código de la ventana de verificación (nunca en el texto del chat, POL-AUTH-08)
  /otp               (solo --jurado) pide un código de prueba para esta sesión y lo muestra
  /lang es|pt        cambia la preferencia de idioma (se envía con el próximo mensaje)
  /audit             (solo --jurado) eventos del audit log de esta sesión
  /reanudar          tras SESSION_EXPIRED: sesión nueva del mismo cliente y G-02 sobre la conversación
  /salir
"""

from getpass import getpass
from typing import Dict, Optional

import argparse
import sys

import httpx


class ErrorCLI(Exception):
    pass


class Cliente:
    def __init__(self, api: str, idioma: Optional[str]):
        self.http = httpx.Client(base_url= api, timeout= 60)
        self.idioma_pendiente = idioma
        self.idioma_inicial = idioma
        self.token: Optional[str] = None
        self.sesion_id: Optional[str] = None
        self.conversation_id: Optional[str] = None
        self.jurado: Optional[Dict[str, str]] = None # correo y contraseña del jurado, para renovar su sesión.
        self.token_jurado: Optional[str] = None
        self.usuario: Optional[Dict[str, str]] = None
        self.customer_id: Optional[str] = None

    # --- HTTP -----------------------------------------------------------------------------------

    def _pedir(self, metodo: str, ruta: str, token: Optional[str], **kwargs) -> dict:
        cabeceras = {"Authorization": f"Bearer {token}"} if token else {}
        respuesta = self.http.request(metodo, ruta, headers= cabeceras, **kwargs)
        if respuesta.status_code >= 400:
            try:
                detalle = respuesta.json().get("detail")
            except ValueError:
                detalle = respuesta.text
            raise ErrorCLI(f"{respuesta.status_code}: {detalle}")
        return respuesta.json() if respuesta.content else {}

    def _iniciar_sesion(self, correo: str, password: str) -> str:
        return self._pedir("POST", "/autenticacion/iniciar-sesion", None, json= {"correo_electronico": correo, "password": password})

    def _token_jurado(self) -> str:
        if self.token_jurado:
            try:
                self._pedir("GET", "/autenticacion/mi-sesion", self.token_jurado)
                return self.token_jurado
            except ErrorCLI:
                pass # Venció: se renueva con las credenciales de esta ejecución.
        self.token_jurado = self._iniciar_sesion(self.jurado["correo"], self.jurado["password"])
        return self.token_jurado

    # --- entrada ----------------------------------------------------------------------------------

    def entrar_como_usuario(self, correo: str) -> None:
        self.usuario = {"correo": correo, "password": getpass(f"Contraseña de {correo}: ")}
        self.token = self._iniciar_sesion(self.usuario["correo"], self.usuario["password"])
        self.sesion_id = self._pedir("GET", "/autenticacion/mi-sesion", self.token)["sesion_id"]

    def entrar_como_jurado(self, correo: str, customer_id: str) -> None:
        self.jurado = {"correo": correo, "password": getpass(f"Contraseña de {correo}: ")}
        self.customer_id = customer_id
        self._sesion_de_prueba()

    def _sesion_de_prueba(self) -> None:
        cuerpo = {"customer_id": self.customer_id, **({"idioma": self.idioma_inicial} if self.idioma_inicial else {})}
        sesion = self._pedir("POST", "/identidad/sesion-prueba", self._token_jurado(), json= cuerpo)
        self.token, self.sesion_id = sesion["token"], sesion["sesion_id"]
        print(f"[IdP de prueba] sesión {self.sesion_id} para {self.customer_id} (customer_status {sesion['customer_status']}). {sesion['aviso']}")

    def abrir_chat(self) -> dict:
        cuerpo = {"idioma": self.idioma_pendiente} if self.idioma_pendiente else {}
        respuesta = self._pedir("POST", "/chat/sesiones", self.token, json= cuerpo)
        self.idioma_pendiente = None
        self.conversation_id = respuesta["conversation_id"]
        return respuesta

    def reanudar(self) -> dict:
        if self.jurado:
            self._sesion_de_prueba()
        else:
            self.token = self._iniciar_sesion(self.usuario["correo"], getpass(f"Contraseña de {self.usuario['correo']}: "))
            self.sesion_id = self._pedir("GET", "/autenticacion/mi-sesion", self.token)["sesion_id"]
        return self._pedir("POST", "/chat/sesiones", self.token, json= {"conversation_id": self.conversation_id})

    # --- turnos -----------------------------------------------------------------------------------

    def enviar(self, mensaje: Optional[str] = None, codigo: Optional[str] = None) -> dict:
        cuerpo = {"conversation_id": self.conversation_id}
        cuerpo.update({"mensaje": mensaje} if mensaje is not None else {"codigo_step_up": codigo})
        if self.idioma_pendiente:
            cuerpo["idioma"] = self.idioma_pendiente
            self.idioma_pendiente = None
        return self._pedir("POST", "/chat/mensaje", self.token, json= cuerpo)

    def otp(self) -> str:
        if not self.jurado:
            raise ErrorCLI("/otp solo funciona con --jurado (el código de prueba lo emite el IdP simulado).")
        codigo = self._pedir("POST", "/identidad/otp-prueba", self._token_jurado(), json= {"sesion_id": self.sesion_id})
        return f"Código de prueba: {codigo['codigo']} (vence {codigo['expira_en']}). Envíelo con /stepup {codigo['codigo']}"

    def auditoria(self) -> str:
        if not self.jurado:
            raise ErrorCLI("/audit necesita el rol jurado o agente (use --jurado).")
        datos = self._pedir("GET", f"/auditoria/{self.sesion_id}", self._token_jurado())
        filas = []
        for evento in datos["eventos"]:
            detalle = evento.get("transition_id") or evento.get("tool") or evento.get("session_event") or evento.get("security_event") or ""
            if evento["event_type"] == "classification":
                detalle = f"set={evento.get('conformal_set')} override={evento.get('safety_override')}"
            filas.append(f"  t{evento['turn_index']:<3} {evento['event_type']:<16} {detalle:<40} {', '.join(evento['rule_ids'][:6])}")
        return f"{datos['total']} eventos de la sesión {self.sesion_id}:\n" + "\n".join(filas)


def mostrar(respuesta: dict) -> None:
    print(f"\nAsistente: {respuesta['reply']}")
    extra = [f"estado {respuesta['state']}", f"idioma {respuesta['language']}", f"turno {respuesta['turn']}"]
    if respuesta.get("pending_confirmation"):
        p = respuesta["pending_confirmation"]
        extra.append(f"confirmación pendiente: {p['card_type']} {p['card_last4']} hasta {p['expires_at']}")
    if respuesta.get("case_id"):
        extra.append(f"caso {respuesta['case_id']}")
    print(f"  [{' · '.join(extra)}]")
    if respuesta["state"] == "STEP_UP":
        print("  (escriba /otp para pedir un código de prueba y /stepup <código> para enviarlo)")
    if respuesta["state"] == "SESSION_EXPIRED":
        print("  (escriba /reanudar para iniciar una sesión nueva y seguir esta conversación)")


def main(argumentos: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description= "Chat de terminal del asistente (API en ejecución).")
    parser.add_argument("--api", default= "http://localhost:8000")
    parser.add_argument("--usuario", help= "correo de un usuario cliente sembrado")
    parser.add_argument("--jurado", help= "correo del usuario jurado")
    parser.add_argument("--cliente", help= "customer_id para la sesión del IdP de prueba (con --jurado)")
    parser.add_argument("--idioma", choices= ("es", "pt"))
    opciones = parser.parse_args(argumentos)

    if bool(opciones.usuario) == bool(opciones.jurado) or (opciones.jurado and not opciones.cliente):
        parser.error("use --usuario, o --jurado con --cliente")

    cliente = Cliente(opciones.api, opciones.idioma)
    try:
        if opciones.usuario:
            cliente.entrar_como_usuario(opciones.usuario)
        else:
            cliente.entrar_como_jurado(opciones.jurado, opciones.cliente)
        mostrar(cliente.abrir_chat())
    except (ErrorCLI, httpx.HTTPError) as error:
        print(f"No se pudo iniciar: {error}")
        return 1

    while True:
        try:
            linea = input("\nUsted: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not linea:
            continue
        try:
            if linea == "/salir":
                return 0
            if linea.startswith("/stepup"):
                partes = linea.split()
                if len(partes) != 2:
                    print("Uso: /stepup <código de 6 dígitos>")
                    continue
                mostrar(cliente.enviar(codigo= partes[1]))
            elif linea == "/otp":
                print(cliente.otp())
            elif linea.startswith("/lang"):
                partes = linea.split()
                if len(partes) != 2 or partes[1] not in ("es", "pt"):
                    print("Uso: /lang es|pt")
                    continue
                cliente.idioma_pendiente = partes[1]
                print(f"Idioma {partes[1]}: se envía con el próximo mensaje.")
            elif linea == "/audit":
                print(cliente.auditoria())
            elif linea == "/reanudar":
                mostrar(cliente.reanudar())
            elif linea.startswith("/"):
                print("Comandos: /stepup <código>, /otp, /lang es|pt, /audit, /reanudar, /salir")
            else:
                mostrar(cliente.enviar(mensaje= linea))
        except (ErrorCLI, httpx.HTTPError) as error:
            print(f"Error: {error}")


if __name__ == "__main__":
    sys.exit(main())
