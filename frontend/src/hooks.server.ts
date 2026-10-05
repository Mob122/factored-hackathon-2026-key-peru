// src/hooks.server.ts
import { redirect, type Handle } from '@sveltejs/kit';
import { COOKIE_TOKEN, llamarBackend } from '$lib/server/backend';
import { inicioDelRol, rutaPermitida } from '$lib/data/roles';

export const handle: Handle = async ({ event, resolve }) => {
	const token = event.cookies.get(COOKIE_TOKEN);

	if (!token) {
		event.locals.usuario = null;
	} else {
		try {
			// Validamos el token contra /autenticacion/mi-perfil: cuenta como actividad de la sesión (POL-AUTH-03).
			const respuesta = await llamarBackend<App.Locals['usuario']>(event.cookies, '/autenticacion/mi-perfil');

			if (respuesta.ok) {
				event.locals.usuario = respuesta.cuerpo;
			} else {
				// Si la sesión expiró o el token es inválido en FastAPI, borramos la cookie.
				event.cookies.delete(COOKIE_TOKEN, { path: '/' });
				event.locals.usuario = null;
			}
		} catch {
			event.locals.usuario = null;
		}
	}

	const ruta = event.url.pathname;
	const usuario = event.locals.usuario;

	// Seguridad: Proteger rutas del /app en el servidor.
	if (ruta.startsWith('/app') && !usuario) {
		redirect(302, `/login?volver=${encodeURIComponent(ruta + event.url.search)}`);
	}
	// Cada rol ve solo sus pantallas: el cliente su portal y el chat, el agente la bandeja de casos.
	if (ruta.startsWith('/app') && usuario && !rutaPermitida(usuario, ruta)) {
		redirect(302, inicioDelRol(usuario));
	}
	// Si ya inicio sesión y quiere ir a login o registrarse, lo redirigimos a su inicio.
	if ((ruta === '/login' || ruta === '/registrarse') && usuario) {
		redirect(302, inicioDelRol(usuario));
	}

	return resolve(event);
};
