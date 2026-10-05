import type { RequestHandler } from './$types';
import { error, json } from '@sveltejs/kit';
import { COOKIE_TOKEN, llamarBackend } from '$lib/server/backend';

// El chat pasa por aquí: el navegador nunca llama a la API ni ve el token (contrato chat_api.md, sección 2).
const RUTAS: Record<string, { ruta: string; esperaMs: number; conCuerpo: boolean }> = {
	sesiones: { ruta: '/chat/sesiones', esperaMs: 30_000, conCuerpo: true }, // Turno 0, o retomar con conversation_id (4.6).
	mensaje: { ruta: '/chat/mensaje', esperaMs: 135_000, conCuerpo: true }, // Puede esperar al LLM (sección 1).
	codigo: { ruta: '/autenticacion/otp-demo', esperaMs: 15_000, conCuerpo: false } // SMS simulado (4.3, POL-AUTH-14).
};

export const POST: RequestHandler = async ({ params, request, cookies }) => {
	const destino = RUTAS[params.accion];
	if (!destino) error(404, 'No encontrado');

	if (!cookies.get(COOKIE_TOKEN)) {
		return json({ detail: { codigo: 'SESSION_EXPIRED', mensaje: 'Su sesión expiró. Inicie sesión de nuevo.' } }, { status: 401 });
	}

	const cuerpo = destino.conCuerpo ? await request.json().catch(() => ({})) : undefined;
	try {
		const respuesta = await llamarBackend(cookies, destino.ruta, { metodo: 'POST', cuerpo, esperaMs: destino.esperaMs });
		if (respuesta.status === 401) cookies.delete(COOKIE_TOKEN, { path: '/' });
		return json(respuesta.cuerpo, { status: respuesta.status });
	} catch {
		return json(
			{ detail: { codigo: 'BACKEND_UNAVAILABLE', mensaje: 'No se pudo conectar con el servidor del banco. Intente de nuevo.' } },
			{ status: 502 }
		);
	}
};
