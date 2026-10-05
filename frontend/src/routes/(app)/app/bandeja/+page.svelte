<script lang="ts">
	import Caso from '$lib/assets/icons/Caso.svelte';
	import { PRIORIDADES, formatearFecha } from '$lib/utils/formato';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

    let filtroPrioridad = $state('Todas');

    const prioridad = (clave: string) => PRIORIDADES[clave] ?? { texto: clave, orden: 9, clase: 'bg-slate-100 text-slate-600' };

    // POL-HND-15: urgent > security > normal; dentro de cada prioridad, el más reciente primero.
    const casos = $derived(
        data.casos
            .filter((caso) => filtroPrioridad === 'Todas' || caso.priority === filtroPrioridad)
            .sort((a, b) => prioridad(a.priority).orden - prioridad(b.priority).orden || b.created_at.localeCompare(a.created_at))
    );
    const porPrioridad = $derived(
        Object.entries(PRIORIDADES).map(([clave, valor]) => ({ clave, ...valor, total: data.casos.filter((caso) => caso.priority === clave).length }))
    );
</script>

<svelte:head>
    <title>Bandeja de casos | Agente</title>
</svelte:head>

<div class="space-y-4">
    <section>
        <div class="space-y-4">
            <span class="block font-light">Asesor humano</span>
            <h1>Bandeja de casos</h1>
        </div>
    </section>

    <section>
        <div class="gap-4 grid sm:grid-cols-3">
            {#each porPrioridad as fila (fila.clave)}
                <button type="button" onclick={() => (filtroPrioridad = filtroPrioridad === fila.clave ? 'Todas' : fila.clave)}
                    class={['bg-white cursor-pointer p-3 rounded-xl space-y-3 text-left', filtroPrioridad === fila.clave && 'ring-2 ring-red-300']}>
                    <span class={`font-semibold px-2 py-0.5 rounded-md text-xs ${fila.clase}`}>{fila.texto}</span>
                    <h3 class="font-bold">{fila.total}</h3>
                </button>
            {/each}
        </div>
    </section>

    <section>
        <div class="bg-white overflow-hidden rounded-2xl">
            <div class="flex items-center justify-between p-4">
                <div>
                    <h2 class="font-semibold">Casos</h2>
                    <p class="mt-1">Ordenados por prioridad y fecha. Abra uno para ver el expediente y su audit trail.</p>
                </div>
                <span class="bg-slate-100 font-medium px-3 py-1 rounded-full text-xs">{casos.length} resultados</span>
            </div>

            {#if casos.length}
                <div class="divide-y divide-slate-100">
                    {#each casos as caso (caso.case_id)}
                        <a href={`/app/bandeja/${caso.case_id}`} class="flex flex-wrap gap-4 hover:bg-slate-50! hover:text-gris-secundario! items-center px-5! py-4! rounded-none!">
                            <div class="bg-slate-100 flex h-8 items-center justify-center rounded-xl shrink-0 w-8">
                                <Caso _class="fill-gris-secundario/62 h-4 w-4" />
                            </div>
                            <div class="flex-1 min-w-0">
                                <div class="flex flex-wrap gap-2 items-center">
                                    <p class="font-mono font-semibold text-sm">{caso.case_id}</p>
                                    <span class={`font-semibold px-2 py-0.5 rounded-md text-[10px] ${prioridad(caso.priority).clase}`}>{prioridad(caso.priority).texto}</span>
                                    {#each caso.reason_rule_ids as regla}
                                        <span class="bg-slate-100 font-mono px-2 py-0.5 rounded-md text-[10px] text-slate-500">{regla}</span>
                                    {/each}
                                </div>
                                <div class="flex flex-wrap gap-x-2 items-center mt-1 text-[11px] text-slate-400">
                                    <span>{formatearFecha(caso.created_at)}</span>
                                    <span>•</span>
                                    <span class="font-mono">{caso.customer_id}</span>
                                    <span>•</span>
                                    <span>{caso.language === 'pt' ? 'Portugués' : 'Español'}</span>
                                    <span>•</span>
                                    <span>{caso.auth_level}</span>
                                </div>
                            </div>
                        </a>
                    {/each}
                </div>
            {:else}
                <p class="px-6 py-16 text-center">No hay casos{filtroPrioridad === 'Todas' ? '' : ' con esta prioridad'}.</p>
            {/if}
        </div>
    </section>
</div>
