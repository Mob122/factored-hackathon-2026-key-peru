<script lang="ts">
	import Lupa from '$lib/assets/icons/Lupa.svelte';
	import Transaccion from '$lib/assets/icons/Transaccion.svelte';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

    let filtro = $state('');
    let tarjetaSeleccionada = $state('Todas');
    let periodoSeleccionado = $state('Últimos 30 días');

    const tarjetas = [
        {
            id: 'card-001',
            numero: '•••• 4821',
            tipo: 'Visa',
            categoria: 'Crédito'
        },
        {
            id: 'card-002',
            numero: '•••• 9137',
            tipo: 'Mastercard',
            categoria: 'Débito'
        },
        {
            id: 'card-003',
            numero: '•••• 1054',
            tipo: 'Visa',
            categoria: 'Crédito'
        }
    ];

    const transacciones = [
        {
            id: 'tx-001',
            comercio: 'Plaza Vea',
            descripcion: 'Compra presencial',
            fecha: '30 sep 2026, 18:42',
            monto: -125.90,
            moneda: 'PEN',
            tarjeta: '•••• 4821',
            estado: 'Completada',
            categoria: 'Compras',
            codigo: 'TX-847291'
        },
        {
            id: 'tx-002',
            comercio: 'Netflix',
            descripcion: 'Suscripción mensual',
            fecha: '29 sep 2026, 09:15',
            monto: -44.90,
            moneda: 'PEN',
            tarjeta: '•••• 4821',
            estado: 'Completada',
            categoria: 'Entretenimiento',
            codigo: 'TX-847102'
        },
        {
            id: 'tx-003',
            comercio: 'Uber',
            descripcion: 'Servicio de transporte',
            fecha: '28 sep 2026, 21:30',
            monto: -18.50,
            moneda: 'PEN',
            tarjeta: '•••• 9137',
            estado: 'Completada',
            categoria: 'Transporte',
            codigo: 'TX-846921'
        },
        {
            id: 'tx-004',
            comercio: 'Rappi',
            descripcion: 'Compra en aplicación',
            fecha: '27 sep 2026, 20:18',
            monto: -67.40,
            moneda: 'PEN',
            tarjeta: '•••• 4821',
            estado: 'Completada',
            categoria: 'Alimentos',
            codigo: 'TX-846731'
        },
        {
            id: 'tx-005',
            comercio: 'Transferencia recibida',
            descripcion: 'Abono a cuenta',
            fecha: '26 sep 2026, 14:05',
            monto: 850.00,
            moneda: 'PEN',
            tarjeta: '•••• 9137',
            estado: 'Completada',
            categoria: 'Ingresos',
            codigo: 'TX-846512'
        },
        {
            id: 'tx-006',
            comercio: 'Spotify',
            descripcion: 'Suscripción mensual',
            fecha: '24 sep 2026, 08:30',
            monto: -23.90,
            moneda: 'PEN',
            tarjeta: '•••• 1054',
            estado: 'Completada',
            categoria: 'Entretenimiento',
            codigo: 'TX-846102'
        }
    ];

    let transaccionSeleccionada = $state<(typeof transacciones)[number] | null>(null);

    let transaccionesFiltradas = $derived(
        transacciones.filter((transaccion) => {
            const coincideTarjeta =
                tarjetaSeleccionada === 'Todas' ||
                transaccion.tarjeta === tarjetaSeleccionada;

            const texto = `${transaccion.comercio} ${transaccion.descripcion} ${transaccion.codigo}`.toLowerCase();

            const coincideBusqueda =
                filtro.trim() === '' ||
                texto.includes(filtro.toLowerCase());

            return coincideTarjeta && coincideBusqueda;
        })
    );

    function seleccionarTransaccion(transaccion: (typeof transacciones)[number]) {
        transaccionSeleccionada = transaccion;
    }

    function cerrarDetalle() {
        transaccionSeleccionada = null;
    }

    function formatearMonto(monto: number) {
        const signo = monto >= 0 ? '+' : '-';

        return `${signo} S/ ${Math.abs(monto).toFixed(2)}`;
    }
</script>

<svelte:head>
    <title>Transacciones | Agente</title>
</svelte:head>


<div class="space-y-4">
    <section>
        <div class="flex items-center justify-between">
            <div class="space-y-4">
                <span class="block font-light">Información verificada</span>
                <h1>Mis transacciones</h1>
            </div>
            <a
                href="/app/consultas"
                class="bg-white font-semibold gap-2 group hidden hover:bg-red-600! px-4 py-2.5 rounded-xl text-sm transition-all sm:inline-flex"
            >
                <span class="block group-hover:-rotate-45">+</span>
                Consultar al asistente
            </a>
        </div>
    </section>
    <section>
         <div class="gap-4 grid mb-6 sm:grid-cols-3">
           <article class="bg-white p-2 rounded-xl space-y-5">
                <div class="flex gap-2 items-center">
                    <Transaccion _class="fill-gris-secundario/62 h-6 w-6" />
                    <span>Movimientos</span>
                </div>
                <h3 class="font-bold">{transaccionesFiltradas.length}</h3>
                <h4 class="separar-letras">En el periodo seleccionado</h4>
            </article>

            <article class="bg-white p-2 rounded-xl space-y-5">
                <div class="flex gap-2 items-center">
                    <Transaccion _class="fill-red-500 h-6 w-6" />
                    <span class="text-red-500">Gastos Recientes</span>
                </div>
                <h3 class="font-bold">S/ 280.60</h3>
                <h4 class="separar-letras">Compras y suscripciones</h4>
            </article>

            <article class="bg-white p-2 rounded-xl space-y-5">
                <div class="flex gap-2 items-center">
                    <Transaccion _class="fill-gris-secundario/62 h-6 w-6" />
                    <span>Tarjetas Utilizadas</span>
                </div>
                <h3 class="font-bold">3</h3>
                <h4 class="separar-letras">Con movimientos recientes</h4>
            </article>                        
        </div>
    </section>
    <section >
        <div>            
            <div class="grid gap-4 md:grid-cols-[1fr_200px_180px]">
                <!-- Buscar -->
                <div class="bg-white p-4 rounded-xl">
                    <label for="buscar" class="block font-semibold mb-2 text-xs">
                        Buscar transacción
                    </label>
    
                    <div class="relative">
                        <Lupa _class="absolute h-4 left-3  stroke-gris-secundario/62 top-1/2 -translate-y-1/2 w-4" />
    
                        <input id="buscar" type="text" bind:value={filtro} placeholder="Comercio, descripción o código..." class="bg-slate-50 focus:bg-white focus:ring-2 focus:ring-red-100 outline-none placeholder:text-slate-400 pl-9 pr-3 py-2.5 rounded-xl text-sm transition-all w-full"
                        />
                    </div>
                </div>
    
                <!-- Tarjeta -->
                <div class="bg-white p-4 rounded-xl">
                    <label for="tarjeta" class="block font-semibold mb-2 text-xs">
                        Tarjeta
                    </label>
    
                    <select id="tarjeta" bind:value={tarjetaSeleccionada} class="bg-slate-50 focus:ring-2 focus:ring-red-100 px-3 py-2.5 rounded-xl text-sm outline-none  w-full"
                    >
                        <option value="Todas">Todas las tarjetas</option>
    
                        {#each tarjetas as tarjeta}
                            <option value={tarjeta.numero}>
                                {tarjeta.tipo} {tarjeta.numero}
                            </option>
                        {/each}
                    </select>
                </div>
    
                <!-- Periodo -->
                <div class="bg-white p-4 rounded-xl">
                    <label for="periodo" class="block font-semibold mb-2 text-xs">
                        Periodo
                    </label>
    
                    <select id="periodo" bind:value={periodoSeleccionado} class="bg-slate-50 focus:ring-2 focus:ring-red-100 px-3 py-2.5 rounded-xl text-sm outline-none w-full">
                        <option>Últimos 30 días</option>
                        <option>Últimos 7 días</option>
                        <option>Últimos 3 meses</option>
                    </select>
                </div>
            </div>
        </div>
    </section>
    <section>
        <div>
            <div class="bg-white overflow-hidden rounded-2xl">
                <div class="p-4">
                    <div class="flex items-center justify-between">
                        <div>
                            <h2 class="font-semibold">
                                Movimientos recientes
                            </h2>
        
                            <p class="mt-1">
                                Selecciona una transacción para consultar sus detalles.
                            </p>
                        </div>
        
                        <span class="bg-slate-100 font-medium px-3 py-1 rounded-full text-xs">
                            {transaccionesFiltradas.length} resultados
                        </span>
                    </div>
                </div>
        
                {#if transaccionesFiltradas.length > 0}
                    <div class="divide-y divide-slate-100">
                        {#each transaccionesFiltradas as transaccion}
                            <button type="button" onclick={() => seleccionarTransaccion(transaccion)} class="cursor-pointer duration-300 flex flex-wrap gap-4 group hover:bg-slate-50 items-center px-5 py-4 text-left transition-all w-full"> 
                                <!-- Icono -->
                                <div class={`flex h-8 items-center justify-center rounded-xl shrink-0 w-8 ${transaccion.monto >= 0 ? 'bg-green-50 text-green-600' : 'bg-slate-100'}`}>
                                    {#if transaccion.monto >= 0}
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
                                                d="M12 4v16m8-8H4"
                                            />
                                        </svg>
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
                                                d="M20 12H4"
                                            />
                                        </svg>
                                    {/if}
                                </div>
        
                                <!-- Información -->
                                <div class="flex-1 min-w-0">
                                    <div class="flex gap-2 items-center">
                                        <p class="font-semibold truncate text-sm">
                                            {transaccion.comercio}
                                        </p>
        
                                        <span class="bg-slate-100 font-medium hidden px-2 py-0.5 rounded-md text-[10px] text-slate-500 sm:inline">
                                            {transaccion.categoria}
                                        </span>
                                    </div>
        
                                    <p class="mt-1 text-xs truncate">
                                        {transaccion.descripcion}
                                    </p>
        
                                    <div class="flex gap-2 items-center mt-1 text-[11px] text-slate-400">
                                        <span>{transaccion.fecha}</span>
                                        <span>•</span>
                                        <span>{transaccion.tarjeta}</span>
                                    </div>
                                </div>
        
                                <!-- Monto -->
                                <div class="text-right">
                                    <p class={`font-bold text-sm ${transaccion.monto >= 0 ? 'text-green-600' : 'text-slate-800' }`}>
                                        {formatearMonto(transaccion.monto)}
                                    </p>
        
                                    <p class="mt-1 text-[11px]! text-slate-400">
                                        {transaccion.estado}
                                    </p>
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
                            <Lupa _class="h-6 stroke-slate-400 w-6" />
                        </div>
        
                        <p class="font-semibold mt-4">
                            No encontramos transacciones
                        </p>
        
                        <p class="mt-1">
                            Prueba cambiando los filtros de búsqueda.
                        </p>
                    </div>
                {/if}
            </div>
        </div>
    </section>
</div>        

<!-- Modal detalle -->
{#if transaccionSeleccionada}
    <div class="backdrop-blur-sm bg-slate-900/40 flex fixed inset-0 items-center justify-center px-4 z-50" role="presentation" onclick={(event) => { if (event.target === event.currentTarget) cerrarDetalle();}}>
        <div class="bg-white max-w-md rounded-2xl">
            <!-- Header -->
            <div class="flex items-start justify-between p-5">
                <div>
                    <p class="font-medium text-xs tracking-wide uppercase">
                        Detalle de transacción
                    </p>

                    <h2 class="font-bold mt-1 text-lg">
                        {transaccionSeleccionada.comercio}
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

            <!-- Monto -->
            <div class="px-5 pt-6 text-center">
                <p class={`text-3xl font-bold `}>
                    {formatearMonto(transaccionSeleccionada.monto)}
                </p>

                <span class="font-semibold inline-flex mt-2 px-3 py-1 rounded-full text-xs text-green-700">
                    {transaccionSeleccionada.estado}
                </span>
            </div>

            <!-- Datos -->
            <div class="p-5 space-y-4 ">
                <div class="border-b border-slate-100 flex items-center justify-between pb-3">
                    <span class="text-sm">Descripción</span>
                    <span class="font-medium text-right text-sm">
                        {transaccionSeleccionada.descripcion}
                    </span>
                </div>

                <div class="border-b border-slate-100 flex items-center justify-between pb-3">
                    <span class="text-sm">Fecha</span>
                    <span class="font-medium text-right text-sm">
                        {transaccionSeleccionada.fecha}
                    </span>
                </div>

                <div class="border-b border-slate-100 flex items-center justify-between pb-3">
                    <span class="text-sm">Tarjeta</span>
                    <span class="font-medium text-right text-sm">
                        {transaccionSeleccionada.tarjeta}
                    </span>
                </div>

                <div class="flex items-center justify-between">
                    <span class="text-sm">Código</span>
                    <span class="bg-slate-100 font-bold font-mono px-2 py-1 rounded-md text-xs">
                        {transaccionSeleccionada.codigo}
                    </span>
                </div>

            </div>

            <!-- Acción -->
            <div class="p-5">
                <a href="/app/consultas" class="bg-red-500 flex font-semibold gap-2 hover:bg-red-400 items-center justify-center rounded-xl px-4 py-3 text-sm text-white transition-all w-full">
                    Consultar esta transacción
                </a>

                <p class="leading-4 mt-2 text-center text-[11px]">
                    El asistente solo proporcionará información que pueda verificar con los datos de tu cuenta.
                </p>
            </div>
        </div>
    </div>
{/if}