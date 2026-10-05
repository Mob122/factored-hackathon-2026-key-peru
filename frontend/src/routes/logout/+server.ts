import type { RequestHandler } from './$types';
import { redirect } from '@sveltejs/kit';
import { COOKIE_TOKEN, llamarBackend } from '$lib/server/backend';

// Cierra la sesión del backend (el token deja de valer) y borra la cookie. `volver` lleva de nuevo a la página
// después del login, por ejemplo para retomar una conversación cuya sesión expiró (contrato, sección 4.6).
export const POST: RequestHandler = async ({ cookies, url }) => {
	if (cookies.get(COOKIE_TOKEN)) {
		try {
			await llamarBackend(cookies, '/autenticacion/cerrar-sesion', { metodo: 'POST' });
		} catch {
			// Sin backend la cookie se borra igual; la sesión vence sola (POL-AUTH-03).
		}
		cookies.delete(COOKIE_TOKEN, { path: '/' });
	}

	const volver = url.searchParams.get('volver');
	redirect(303, volver?.startsWith('/app') ? `/login?volver=${encodeURIComponent(volver)}` : '/login');
};
