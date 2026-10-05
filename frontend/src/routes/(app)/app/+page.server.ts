import type { PageServerLoad } from './$types';
import { leerPortal } from '$lib/server/backend';
import { esCliente } from '$lib/data/roles';
import type { CasoCliente, ConversacionCliente, Tarjeta, Transacciones } from '$lib/types';

// Resumen del cliente con sus datos del portal (contrato chat_api.md, sección 4.7). El jurado y un usuario
// registrado sin cliente solo ven un aviso.
export const load = (async ({ cookies, url, locals }) => {
    if (!locals.usuario || !esCliente(locals.usuario)) return { portal: null };

    const [tarjetas, transacciones, conversaciones, casos] = await Promise.all([
        leerPortal<Tarjeta[]>(cookies, '/cliente/tarjetas', url),
        leerPortal<Transacciones>(cookies, '/cliente/transacciones?dias=30', url),
        leerPortal<ConversacionCliente[]>(cookies, '/cliente/conversaciones', url),
        leerPortal<CasoCliente[]>(cookies, '/cliente/casos', url)
    ]);

    return {
        portal: {
            enRevision: tarjetas.enRevision,
            tarjetas: tarjetas.datos ?? [],
            transacciones: transacciones.datos,
            conversaciones: conversaciones.datos ?? [],
            casos: casos.datos ?? []
        }
    };
}) satisfies PageServerLoad;
