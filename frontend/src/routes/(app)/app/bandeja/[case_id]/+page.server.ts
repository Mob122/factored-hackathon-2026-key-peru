import type { PageServerLoad } from './$types';
import { error } from '@sveltejs/kit';
import { leerBackend, mensajeError } from '$lib/server/backend';
import type { EventosConversacion, LecturaCaso } from '$lib/types';

// Expediente (contrato, sección 10) y audit trail de su conversación con la verificación de la cadena (sección 11).
export const load = (async ({ cookies, url, params }) => {
    const caso = await leerBackend<LecturaCaso>(cookies, `/casos/${encodeURIComponent(params.case_id)}`, url);
    if (!caso.ok) error(caso.status, mensajeError(caso.cuerpo, 'Caso no encontrado.'));

    const ruta = `/auditoria/conversacion/${encodeURIComponent(caso.cuerpo.conversation_ref)}?limite=2000`;
    const auditoria = await leerBackend<EventosConversacion>(cookies, ruta, url);

    return { caso: caso.cuerpo, auditoria: auditoria.ok ? auditoria.cuerpo : null };
}) satisfies PageServerLoad;
