import type { PageServerLoad } from './$types';
import { leerBackend } from '$lib/server/backend';

type Sesion = { sesion_id: string; nivel: string; idioma: 'es' | 'pt' | null; expira_absoluta_en: string };

// La sesión actual decide si una conversación guardada en el navegador se sigue tal cual (misma sesión) o se
// retoma con POST /chat/sesiones y su conversation_id (sesión nueva tras iniciar sesión otra vez, contrato 4.6).
export const load = (async ({ cookies, url }) => {
    const sesion = (await leerBackend<Sesion>(cookies, '/autenticacion/mi-sesion', url)).cuerpo;

    return {
        sesion: { sesion_id: sesion.sesion_id, idioma: sesion.idioma },
        mensajeInicial: url.searchParams.get('mensaje') ?? ''
    };
}) satisfies PageServerLoad;
