import { env } from '$env/dynamic/private';
import { error, redirect, type Cookies } from '@sveltejs/kit';

// URL de la API (FastAPI). Solo el servidor de SvelteKit la usa: el navegador nunca llama a la API directo.
// API_BCKD_8 se mantiene como alias de la configuración de producción del frontend.
export const BACKEND_URL = (env.BACKEND_URL || env.API_BCKD_8 || 'http://localhost:8000').replace(/\/+$/, '');

export const COOKIE_TOKEN = 'token';

// La sesión del backend dura como mucho 60 minutos (POL-AUTH-03): la cookie no vive más que ella.
// `secure` queda con el valor por defecto de SvelteKit: solo HTTPS, salvo en http://localhost (desarrollo).
export const OPCIONES_COOKIE = {
	path: '/',
	httpOnly: true, // Invisible para JavaScript del lado del cliente.
	sameSite: 'strict',
	maxAge: 60 * 60
} as const;

export type RespuestaBackend<T> = { ok: boolean; status: number; cuerpo: T };

// Error de la API: {"detail": {"codigo", "mensaje"}}, {"detail": "<texto>"} o la lista de validación (contrato, sección 9).
export function codigoError(cuerpo: unknown): string | undefined {
	const detalle = (cuerpo as { detail?: unknown } | null)?.detail;
	return typeof detalle === 'object' && detalle !== null && 'codigo' in detalle
		? String((detalle as { codigo: unknown }).codigo)
		: undefined;
}

export function mensajeError(cuerpo: unknown, porDefecto = 'Ocurrió un error inesperado.'): string {
	const detalle = (cuerpo as { detail?: unknown } | null)?.detail;
	if (typeof detalle === 'string') return detalle;
	if (typeof detalle === 'object' && detalle !== null && 'mensaje' in detalle) {
		return String((detalle as { mensaje: unknown }).mensaje);
	}
	return porDefecto;
}

// Llama a la API con el token de la cookie. Un turno del chat puede esperar al LLM hasta 130 s (contrato, sección 1).
export async function llamarBackend<T = unknown>(
	cookies: Cookies,
	ruta: string,
	{ metodo = 'GET', cuerpo, esperaMs = 15_000 }: { metodo?: string; cuerpo?: unknown; esperaMs?: number } = {}
): Promise<RespuestaBackend<T>> {
	const cabeceras: Record<string, string> = {};
	const token = cookies.get(COOKIE_TOKEN);
	if (token) cabeceras['Authorization'] = `Bearer ${token}`;
	if (cuerpo !== undefined) cabeceras['Content-Type'] = 'application/json';

	const respuesta = await fetch(`${BACKEND_URL}${ruta}`, {
		method: metodo,
		headers: cabeceras,
		body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
		signal: AbortSignal.timeout(esperaMs)
	});
	const texto = await respuesta.text();

	return { ok: respuesta.ok, status: respuesta.status, cuerpo: (texto ? JSON.parse(texto) : null) as T };
}

// Para los load de las páginas: un 401 es "inicie sesión de nuevo" (contrato, sección 2); 403 y 404 los decide la página.
export async function leerBackend<T>(cookies: Cookies, ruta: string, url: URL): Promise<RespuestaBackend<T>> {
	let respuesta: RespuestaBackend<T>;
	try {
		respuesta = await llamarBackend<T>(cookies, ruta);
	} catch {
		error(502, 'No se pudo conectar con el servidor del banco.');
	}

	if (respuesta.status === 401) {
		cookies.delete(COOKIE_TOKEN, { path: '/' });
		redirect(303, `/login?volver=${encodeURIComponent(url.pathname + url.search)}`);
	}
	if (!respuesta.ok && respuesta.status !== 403 && respuesta.status !== 404) {
		error(respuesta.status, mensajeError(respuesta.cuerpo));
	}
	return respuesta;
}

// Portal del cliente (contrato, sección 4.7): un cliente Suspended o Closed recibe CUSTOMER_STATUS_REVIEW en tarjetas
// y transacciones (POL-AUTH-09); la página lo muestra como aviso, no como error.
export async function leerPortal<T>(cookies: Cookies, ruta: string, url: URL): Promise<{ datos: T | null; enRevision: boolean }> {
	const respuesta = await leerBackend<T>(cookies, ruta, url);
	if (respuesta.ok) return { datos: respuesta.cuerpo, enRevision: false };
	if (codigoError(respuesta.cuerpo) === 'CUSTOMER_STATUS_REVIEW') return { datos: null, enRevision: true };
	error(respuesta.status, mensajeError(respuesta.cuerpo));
}
