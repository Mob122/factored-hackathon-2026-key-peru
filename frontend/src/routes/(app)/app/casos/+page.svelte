<script lang="ts">
	import Caso from '$lib/assets/icons/Caso.svelte';
	import { PRIORIDADES, formatearFecha, motivoCaso } from '$lib/utils/formato';
	import type { CasoCliente } from '$lib/types';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

    let filtroPrioridad = $state('Todas');
    let casoSeleccionado = $state<CasoCliente | null>(null);

    let casosFiltrados = $derived(
        data.casos.filter((caso) => filtroPrioridad === 'Todas' || caso.prioridad === filtroPrioridad)
    );
    const prioritarios = $derived(data.casos.filter((caso) => caso.prioridad !== 'normal').length);

    const prioridad = (clave: string) => PRIORIDADES[clave] ?? { texto: clave, orden: 9, clase: 'bg-slate-100 text-slate-600' };

    function seleccionarCaso(caso: CasoCliente) {
        casoSeleccionado = caso;
    }

    function cerrarDetalle() {
        casoSeleccionado = null;
    }
</script>

<svelte:head>
    <title>Mis casos | Agente</title>
</svelte:head>

<div class="space-y-4">
    <section>
        <div class="flex items-center justify-between">
            <div class="space-y-4">
                <div class="flex items-center gap-2">
                    <span class="font-light">Atención al cliente</span>
                </div>

                <h1>Mis casos</h1>
            </div>

            <a href="/app/consultas" class="bg-white font-semibold gap-2 group hidden hover:bg-red-600! px-4 py-2.5 rounded-xl text-sm transition-all sm:inline-flex">
                <span class="block group-hover:-rotate-45">+</span>
                Nueva consulta
            </a>
        </div>
    </section>

    <section>
        <div class="gap-4 grid sm:grid-cols-3">
            <article class="bg-white p-2 rounded-xl space-y-5">
                <div class="flex gap-2 items-center">
                    <Caso _class="fill-gris-secundario/62 h-4 w-4" />
                    <span>Total de casos</span>
                </div>

                <h3 class="font-bold">{data.casos.length}</h3>
                <h4 class="separar-letras">Transferidos a un asesor</h4>
            </article>

            <article class="bg-white p-2 rounded-xl space-y-5">
                <div class="flex gap-2 items-center">
                    <span class="bg-yellow-500 h-2 rounded-full w-2"></span>
                    <span class="text-yellow-600">En atención</span>
                </div>

                <h3 class="font-bold">{data.casos.length}</h3>
                <h4 class="separar-letras">Pendientes de un asesor</h4>
            </article>

            <article class="bg-white p-2 rounded-xl space-y-5">
                <div class="flex gap-2 items-center">
                    <span class="bg-red-500 h-2 rounded-full w-2"></span>
                    <span class="text-red-600">Prioritarios</span>
                </div>

                <h3 class="font-bold">{prioritarios}</h3>
                <h4 class="separar-letras">Seguridad o urgencia</h4>
            </article>
        </div>
    </section>

    <section >
        <div>
            <div class="bg-white flex flex-wrap gap-4 items-end justify-between p-4 rounded-xl">
                <div>
                    <h2 class="font-semibold">
                        Historial de atención
                    </h2>

                    <p class="mt-1">
                        Los casos que el asistente transfirió a un asesor, con su referencia.
                    </p>
                </div>

                <div>
                    <label for="prioridad" class="block font-semibold mb-2 text-xs">
                        Prioridad
                    </label>

                    <select
                        id="prioridad"
                        bind:value={filtroPrioridad}
                        class="bg-slate-50 focus:ring-2 focus:ring-red-100 px-3 py-2.5 rounded-xl text-sm outline-none"
                    >
                        <option value="Todas">Todas</option>
                        {#each Object.entries(PRIORIDADES) as [clave, valor]}
                            <option value={clave}>{valor.texto}</option>
                        {/each}
                    </select>
                </div>
            </div>
        </div>
    </section>

    <section>
        <div>
            <div class="bg-white overflow-hidden rounded-2xl">
                <div class="p-4">
                    <div class="flex gap-3 items-center justify-between">
                        <div>
                            <h2 class="font-semibold">
                                Casos registrados
                            </h2>

                            <p class="mt-1">
                                Selecciona un caso para ver su información.
                            </p>
                        </div>

                        <span class="bg-slate-100 font-medium px-3 py-1 rounded-full text-xs">
                            {casosFiltrados.length} resultados
                        </span>
                    </div>
                </div>
                {#if casosFiltrados.length > 0}
                    <div class="divide-y divide-slate-100">
                        {#each casosFiltrados as caso (caso.case_id)}
                            <button type="button" onclick={() => seleccionarCaso(caso)} class="cursor-pointer duration-300 flex flex-wrap gap-4 group hover:bg-slate-50 items-center px-5 py-4 text-left transition-all w-full">
                                <div class="bg-slate-100 flex h-8 items-center justify-center rounded-xl shrink-0 w-8">
                                    <Caso _class="fill-gris-secundario/62 h-4 w-4" />
                                </div>

                                <div class="flex-1 min-w-0">
                                    <div class="flex gap-2 items-center">
                                        <p class="font-semibold truncate text-sm">
                                            {motivoCaso(caso.motivo)}
                                        </p>
                                        {#if caso.prioridad !== 'normal'}
                                            <span class={`font-semibold hidden px-2 py-0.5 rounded-md text-[10px] sm:inline ${prioridad(caso.prioridad).clase}`}>
                                                Prioridad {prioridad(caso.prioridad).texto.toLowerCase()}
                                            </span>
                                        {/if}
                                    </div>

                                    <div class="flex flex-wrap gap-x-2 gap-y-1 items-center mt-1 text-[11px] text-slate-400">
                                        <span>{caso.case_id}</span>
                                        <span>•</span>
                                        <span>{formatearFecha(caso.creado_en)}</span>
                                        {#each caso.tarjetas_last4 as ultimos4}
                                            <span>•</span>
                                            <span>•••• {ultimos4}</span>
                                        {/each}
                                    </div>
                                </div>

                                <div class="hidden items-end gap-2 sm:flex sm:flex-col">
                                    <span class="bg-yellow-50 font-semibold px-3 py-1 rounded-full text-xs text-yellow-700">
                                        En atención
                                    </span>
                                </div>

                                <svg
                                    xmlns="http://www.w3.org/2000/svg"
                                    class="h-4 w-4 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-red-400"
                                    fill="none"
                                    viewBox="0 0 24 24"
                                    stroke="currentColor"
                                    stroke-width="2"
                                >
                                    <path
                                        stroke-linecap="round"
                                        stroke-linejoin="round"
                                        d="M9 5l7 7-7 7"
                                    />
                                </svg>
                            </button>
                        {/each}
                    </div>
                {:else}
                    <div class="px-6 py-16 text-center">
                        <div class="bg-slate-100 flex h-12 items-center justify-center mx-auto rounded-full w-12">
                            <Caso _class="fill-slate-400 h-6 w-6" />
                        </div>

                        <p class="font-semibold mt-4">
                            {data.casos.length ? 'No hay casos con esta prioridad' : 'No tiene casos con un asesor'}
                        </p>
                        <p class="mt-1">
                            Cuando el asistente transfiera una consulta a un asesor, el caso aparecerá aquí.
                        </p>
                    </div>
                {/if}
            </div>
        </div>
    </section>
</div>

{#if casoSeleccionado}
    <div class="backdrop-blur-sm bg-slate-900/40 flex fixed inset-0 items-center justify-center px-4 z-50" role="presentation" onclick={(event) => { if (event.target === event.currentTarget) cerrarDetalle();}}>
        <div class="bg-white max-w-md rounded-2xl w-full">
            <!-- Header -->
            <div class="flex items-start justify-between p-5">
                <div>
                    <div class="flex gap-2 items-center">
                        <span class="font-mono font-semibold text-red-500 text-xs">
                            {casoSeleccionado.case_id}
                        </span>
                        <span class="bg-yellow-50 font-semibold px-2 py-0.5 rounded-full text-[10px] text-yellow-700">
                            En atención
                        </span>
                    </div>
                    <h2 class="font-bold mt-1 text-lg">
                        {motivoCaso(casoSeleccionado.motivo)}
                    </h2>

                </div>

                <button
                    type="button"
                    onclick={cerrarDetalle}
                    class="cursor-pointer hover:bg-slate-100 hover:text-slate-600 p-2 rounded-lg text-slate-400 transition-all"
                    aria-label="Cerrar"
                >
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        class="h-5 w-5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            d="M6 18L18 6M6 6l12 12"
                        />
                    </svg>
                </button>
            </div>

            <!-- Datos -->
            <div class="p-5 space-y-4">
                <div>
                    <p class="font-semibold text-xs uppercase tracking-wide">
                        Información del caso
                    </p>
                </div>

                <div class="space-y-4">
                    <div class="border-b border-slate-100 flex items-center justify-between pb-3">
                        <span class="text-sm">Prioridad</span>
                        <span class="font-medium text-right text-sm">{prioridad(casoSeleccionado.prioridad).texto}</span>
                    </div>

                    <div class="border-b border-slate-100 flex items-center justify-between pb-3">
                        <span class="text-sm">Tarjetas</span>
                        <span class="font-medium text-right text-sm">
                            {casoSeleccionado.tarjetas_last4.length ? casoSeleccionado.tarjetas_last4.map((u) => `•••• ${u}`).join(', ') : '—'}
                        </span>
                    </div>

                    <div class="border-b border-slate-100 flex items-center justify-between pb-3">
                        <span class="text-sm">Fecha de creación</span>
                        <span class="font-medium text-right text-sm">{formatearFecha(casoSeleccionado.creado_en)}</span>
                    </div>

                    <div class="flex items-center justify-between">
                        <span class="text-sm">Mensajes agregados después de la transferencia</span>
                        <span class="font-medium text-right text-sm">{casoSeleccionado.mensajes_agregados}</span>
                    </div>
                </div>
            </div>

            <!-- Acción -->
            <div class="p-5">
                <div class="flex gap-3 items-start">
                    <div class="bg-yellow-500 h-2 mt-0.5 rounded-full w-2"></div>
                    <p class="leading-5 text-xs">
                        Un asesor revisará su caso con la referencia {casoSeleccionado.case_id}. El asesor ve lo que el
                        asistente verificó en la conversación, así que no necesita repetirlo.
                    </p>
                </div>

                <a
                    href="/app/consultas"
                    class="bg-red-500 flex font-semibold gap-2 hover:bg-red-400 items-center justify-center mt-4 rounded-xl px-4 py-3 text-sm text-white transition-all w-full"
                >
                    Consultar al asistente
                </a>
            </div>
        </div>
    </div>
{/if}
