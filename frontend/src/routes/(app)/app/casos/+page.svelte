<script lang="ts">
	import Tarjeta from '$lib/assets/icons/Tarjeta.svelte';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

    let filtroEstado = $state('Todos');
    let casoSeleccionado = $state<(typeof casos)[number] | null>(null);

    const casos = [
        {
            id: 'CAS-2026-00124',
            asunto: 'Consulta sobre transacción',
            tipo: 'Transacción',
            fecha: '30 sep 2026, 19:05',
            ultimaActualizacion: 'Hace 15 minutos',
            estado: 'En atención',
            prioridad: 'Normal',
            tarjeta: '•••• 4821',
            descripcion:
                'El cliente solicita asistencia para revisar una transacción que no reconoce.',
            detalle:
                'Se verificó la existencia de la transacción y se derivó el caso a un especialista para continuar con la atención.'
        },
        {
            id: 'CAS-2026-00118',
            asunto: 'Solicitud de desbloqueo',
            tipo: 'Tarjeta',
            fecha: '28 sep 2026, 11:32',
            ultimaActualizacion: '28 sep 2026',
            estado: 'Resuelto',
            prioridad: 'Normal',
            tarjeta: '•••• 1054',
            descripcion:
                'Solicitud para desbloquear una tarjeta actualmente bloqueada.',
            detalle:
                'La solicitud fue derivada a un especialista debido a que el desbloqueo no puede ser realizado automáticamente por el asistente.'
        },
        {
            id: 'CAS-2026-00107',
            asunto: 'Consulta sobre bloqueo',
            tipo: 'Tarjeta',
            fecha: '25 sep 2026, 16:48',
            ultimaActualizacion: '26 sep 2026',
            estado: 'Resuelto',
            prioridad: 'Normal',
            tarjeta: '•••• 9137',
            descripcion:
                'Consulta relacionada con el estado de una tarjeta.',
            detalle:
                'Se atendió la consulta y se confirmó el estado de la tarjeta con la información disponible.'
        },
        {
            id: 'CAS-2026-00094',
            asunto: 'Transacción no reconocida',
            tipo: 'Transacción',
            fecha: '21 sep 2026, 10:21',
            ultimaActualizacion: '22 sep 2026',
            estado: 'Cerrado',
            prioridad: 'Alta',
            tarjeta: '•••• 4821',
            descripcion:
                'El cliente reportó una transacción que no reconoce.',
            detalle:
                'El caso fue revisado por un especialista y posteriormente cerrado.'
        }
    ];

    let casosFiltrados = $derived(
        casos.filter((caso) => {
            return filtroEstado === 'Todos' || caso.estado === filtroEstado;
        })
    );

    function seleccionarCaso(caso: (typeof casos)[number]) {
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
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        class="h-4 w-4 text-slate-500"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a2 2 0 011.414.586l4.414 4.414A2 2 0 0119 9v10a2 2 0 01-2 2z"
                        />
                    </svg>
                
                    <span>Total de casos</span>
                </div>

                <h3 class="font-bold">{casos.length}</h3>
                <h4 class="separar-letras">Solicitudes registradas</h4>
            </article>

            <article class="bg-white p-2 rounded-xl space-y-5">
                <div class="flex gap-2 items-center">
                    <span class="bg-yellow-500 h-2 rounded-full w-2"></span>
                    <span class="text-yellow-600">En atención</span>
                </div>

                <h3 class="font-bold">{casos.filter((caso) => caso.estado === 'En atención').length}</h3>
                <h4 class="separar-letras">Pendientes de especialista</h4>
            </article>

            <article class="bg-white p-2 rounded-xl space-y-5">
                <div class="flex gap-2 items-center">
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        class="fill-none h-5 stroke-green-600 w-5"
                        viewBox="0 0 24 24"
                        stroke-width="2"
                    >
                        <path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            d="M5 13l4 4L19 7"
                        />
                    </svg>

                    <span class="text-green-600">Resueltos</span>
                </div>

                <h3 class="font-bold">{casos.filter((caso) => caso.estado === 'Resuelto').length}</h3>
                <h4 class="separar-letras">Solicitudes atendidas</h4>
            </article>
        </div>
    </section>

    <section >
        <div>            
            <div class="bg-white p-4 rounded-xl">
                <label for="buscar" class="block font-semibold mb-2 text-xs">
                    Buscar transacción
                </label>                    
                <div class="flex flex-col ">
                    <div>
                        <h2 class="font-semibold">
                            Historial de atención
                        </h2>

                        <p class="mt-1">
                            Revisa las solicitudes asociadas a tu cuenta.
                        </p>
                    </div>

                    <div>
                        <label for="estado" class="block font-semibold mb-2 text-xs">
                            Estado
                        </label>

                        <select
                            id="estado"
                            bind:value={filtroEstado}
                            class="bg-slate-50 focus:ring-2 focus:ring-red-100 px-3 py-2.5 rounded-xl text-sm outline-none"
                        >
                            <option value="Todos">Todos los estados</option>
                            <option value="En atención">En atención</option>
                            <option value="Resuelto">Resueltos</option>
                            <option value="Cerrado">Cerrados</option>
                        </select>
                    </div>
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
                        {#each casosFiltrados as caso}
                            <button type="button" onclick={() => seleccionarCaso(caso)} class="cursor-pointer duration-300 flex flex-wrap gap-4 group hover:bg-slate-50 items-center px-5 py-4 text-left transition-all w-full">
                                <!-- Icono -->
                                <div
                                    class={`flex h-8 items-center justify-center rounded-xl shrink-0 w-8 ${
                                        caso.tipo === 'Tarjeta'
                                            ? 'bg-red-50 text-red-500'
                                            : 'bg-slate-100 text-slate-600'
                                    }`}
                                >
                                    {#if caso.tipo === 'Tarjeta'}
                                        <Tarjeta _class="fill-gris-secundario/62 h-4 w-4" />
                                    {:else}
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
                                                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a2 2 0 011.414.586l4.414 4.414A2 2 0 0119 9v10a2 2 0 01-2 2z"
                                            />
                                        </svg>
                                    {/if}
                                </div>
    
                                <div class="flex-1 min-w-0">
                                    <div class="flex gap-2 items-center">
                                        <p class="font-semibold truncate text-sm">
                                            {caso.asunto}
                                        </p>
                                        <span class="bg-slate-100 font-medium hidden px-2 py-0.5 rounded-md text-[10px] text-slate-500 sm:inline">
                                            {caso.tipo}
                                        </span>
                                        {#if caso.prioridad === 'Alta'}
                                            <span class="bg-red-50 font-semibold hidden px-2 py-0.5 rounded-md text-[10px] text-red-600 sm:inline">
                                                Prioridad alta
                                            </span>
                                        {/if}
                                    </div>
    
                                    <p class="mt-1 text-wrap text-xs truncate">
                                        {caso.descripcion}
                                    </p>
    
                                    <div class="flex flex-wrap gap-x-2 gap-y-1 items-center mt-1 text-[11px] text-slate-400">
                                        <span>{caso.id}</span>
                                        <span>•</span>
                                        <span>{caso.fecha}</span>
                                        <span>•</span>
                                        <span>{caso.tarjeta}</span>
                                    </div>                                    
                                </div>

                                <div class="hidden items-end gap-2 sm:flex sm:flex-col">
                                    <span
                                        class={`font-semibold px-3 py-1 rounded-full text-xs ${caso.estado === 'En atención' ? 'bg-yellow-50 text-yellow-700' : caso.estado === 'Resuelto' ? 'bg-green-50 text-green-700' : 'bg-slate-100 text-slate-600'}`}
                                    >
                                        {caso.estado}
                                    </span>

                                    <span class="text-[11px]! text-slate-400">
                                        {caso.ultimaActualizacion}
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
                            <svg
                                xmlns="http://www.w3.org/2000/svg"
                                class="h-6 w-6 text-slate-400"
                                fill="none"
                                viewBox="0 0 24 24"
                                stroke="currentColor"
                                stroke-width="2"
                            >
                                <path
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586L19 9v10a2 2 0 01-2 2z"
                                />
                            </svg>
                        </div>

                        <p class="font-semibold mt-4">
                            No hay casos con este estado
                        </p>
                        <p class="mt-1">
                            Prueba seleccionando otro filtro.
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
                            {casoSeleccionado.id}
                        </span>
                        <span
                            class={`font-semibold px-2 py-0.5 rounded-full text-[10px] ${
                                casoSeleccionado.estado === 'En atención'
                                    ? 'bg-yellow-50 text-yellow-700'
                                    : casoSeleccionado.estado === 'Resuelto'
                                      ? 'bg-green-50 text-green-700'
                                      : 'bg-slate-100 text-slate-600'
                            }`}
                        >
                            {casoSeleccionado.estado}
                        </span>
                    </div>
                    <h2 class="font-bold mt-1 text-lg">
                        {casoSeleccionado.asunto}
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

            <!-- Descripción -->
            <div class="px-5">
                <div class="bg-slate-50 p-4 rounded-xl">
                    <p class="font-semibold text-xs uppercase tracking-wide">
                        Descripción
                    </p>
                    <p class="mt-2 text-sm">
                        {casoSeleccionado.descripcion}
                    </p>
                </div>
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
                        <span class="text-sm">
                            Tipo
                        </span>

                        <span class="font-medium text-right text-sm">
                            {casoSeleccionado.tipo}
                        </span>
                    </div>

                    <div class="border-b border-slate-100 flex items-center justify-between pb-3">
                        <span class="text-sm">
                            Tarjeta
                        </span>

                        <span class="font-medium text-right text-sm">
                            {casoSeleccionado.tarjeta}
                        </span>
                    </div>

                    <div class="border-b border-slate-100 flex items-center justify-between pb-3">
                        <span class="text-sm">
                            Fecha de creación
                        </span>
                        <span class="font-medium text-right text-sm">
                            {casoSeleccionado.fecha}
                        </span>
                    </div>

                    <div class="flex items-center justify-between">
                        <span class="text-sm">
                            Última actualización
                        </span>
                        <span class="font-medium text-right text-sm">
                            {casoSeleccionado.ultimaActualizacion}
                        </span>
                    </div>
                </div>

                <div>
                    <p class="font-semibold text-xs uppercase tracking-wide">
                        Atención
                    </p>

                    <p class="mt-2 text-sm">
                        {casoSeleccionado.detalle}
                    </p>

                </div>

            </div>

            <!-- Acción -->
            <div class="p-5">
                {#if casoSeleccionado.estado === 'En atención'}
                    <div class="flex gap-3 items-start">
                        <div class="bg-yellow-500 h-2 mt-0.5 rounded-full w-2"></div>
                        <p class="leading-5 text-xs">
                            Tu caso se encuentra en atención. Un especialista
                            continuará con la revisión.
                        </p>
                    </div>
                {:else}
                    <div class="flex gap-3 items-start">
                        <div class="bg-green-500 h-2 mt-0.5 rounded-full w-2"></div>
                        <p class="leading-5 text-xs">
                            Este caso ya fue atendido. Puedes iniciar una nueva
                            consulta si necesitas ayuda adicional.
                        </p>
                    </div>
                {/if}

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