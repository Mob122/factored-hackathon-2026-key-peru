// src/hooks.server.ts
import { env } from '$env/dynamic/private';
import { redirect, type Handle } from '@sveltejs/kit';

export const handle: Handle = async ({ event, resolve }) => {
	const token = event.cookies.get('token');

	if (!token) {
		event.locals.usuario = null;
	} else {
		try {
			// Validamos el token directamente contra el endpoint /me de FastAPI
			const response = await fetch(`${env.API_BCKD_8}/autenticacion/mi-perfil`, {
				method: 'GET',
				headers: {
					'Authorization': `Bearer ${token}`,
					'Content-Type': 'application/json'
				}
			});

			if (response.ok) {
				const usuario = await response.json();
				// Guardamos los datos del usuario en el objeto locals
				event.locals.usuario = usuario;
			} else {
				// Si el token expiró o es inválido en FastAPI, borramos la cookie.
				event.cookies.delete('token', { path: '/' });
				event.locals.usuario = null;
			}
		} catch (error) {
			event.locals.usuario = null;
		}
	}


	// Seguridad: Proteger rutas del /app en el servidor.
	if (event.url.pathname.startsWith('/app') && !event.locals.usuario) {
		redirect(302, '/login');
	} 
	// Si ya inicio sesión y quiere ir a login o registrarse, lo redirigimos a /app.
	if ((event.url.pathname === '/login' || event.url.pathname === '/registrarse') && event.locals.usuario) {
		redirect(302, '/app');
	}

	return resolve(event);
};