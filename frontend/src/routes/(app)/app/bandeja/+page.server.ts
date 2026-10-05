import type { PageServerLoad } from './$types';
import { error } from '@sveltejs/kit';
import { leerBackend, mensajeError } from '$lib/server/backend';
import type { ResumenCaso } from '$lib/types';

// Bandeja del agente (contrato chat_api.md, sección 5): los casos más recientes primero.
export const load = (async ({ cookies, url }) => {
    const respuesta = await leerBackend<ResumenCaso[]>(cookies, '/casos?limite=200', url);
    if (!respuesta.ok) error(respuesta.status, mensajeError(respuesta.cuerpo));

    return { casos: respuesta.cuerpo };
}) satisfies PageServerLoad;
