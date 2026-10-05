import type { PageServerLoad } from './$types';
import { leerPortal } from '$lib/server/backend';
import type { CasoCliente } from '$lib/types';

export const load = (async ({ cookies, url }) => {
    const { datos } = await leerPortal<CasoCliente[]>(cookies, '/cliente/casos', url);

    return { casos: datos ?? [] };
}) satisfies PageServerLoad;
