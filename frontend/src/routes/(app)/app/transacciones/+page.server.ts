import type { PageServerLoad } from './$types';
import { leerPortal } from '$lib/server/backend';
import type { Transacciones } from '$lib/types';

const PERIODOS = [7, 30, 90]; // 90 = TX_MAX_DAYS (POL-ANS-03).

export const load = (async ({ cookies, url }) => {
    const pedido = Number(url.searchParams.get('dias'));
    const dias = PERIODOS.includes(pedido) ? pedido : 30;
    const { datos, enRevision } = await leerPortal<Transacciones>(cookies, `/cliente/transacciones?dias=${dias}`, url);

    return { transacciones: datos, enRevision, dias, tarjeta: url.searchParams.get('tarjeta') ?? 'Todas' };
}) satisfies PageServerLoad;
