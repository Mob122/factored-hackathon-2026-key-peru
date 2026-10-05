import type { PageServerLoad } from './$types';
import { leerPortal } from '$lib/server/backend';
import type { Tarjeta } from '$lib/types';

export const load = (async ({ cookies, url }) => {
    const { datos, enRevision } = await leerPortal<Tarjeta[]>(cookies, '/cliente/tarjetas', url);

    return { tarjetas: datos ?? [], enRevision };
}) satisfies PageServerLoad;
