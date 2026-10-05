<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import Lupa from '$lib/assets/icons/Lupa.svelte';
	import Transaccion from '$lib/assets/icons/Transaccion.svelte';
	import {
		ESTADOS_TRANSACCION, TIPOS_TRANSACCION, fechaLarga, formatearFechaBanco, formatearMonto, tipoCorto
	} from '$lib/utils/formato';
	import type { Tarjeta, Transaccion as TipoTransaccion } from '$lib/types';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

    type Fila = TipoTransaccion & { tarjeta: Tarjeta };

    let filtro = $state('');
    let transaccionSeleccionada = $state<Fila | null>(null);

    const ARTICULOS: Record<string, string> = { Purchase: 'la compra', Withdrawal: 'el retiro', Payment: 'el pago' };

    // Todas las transacciones del periodo, de la más reciente a la más antigua, con su tarjeta.
    const filas = $derived(
        (data.transacciones?.tarjetas ?? [])
            .flatMap((tarjeta) => tarjeta.transacciones.map((tx) => ({ ...tx, tarjeta })))
            .sort((a, b) => b.fecha.localeCompare(a.fecha))
    );

    let transaccionesFiltradas = $derived(
        filas.filter((fila) => {
            const coincideTarjeta = data.tarjeta === 'Todas' || fila.tarjeta.ref === data.tarjeta;
            const texto = `${fila.comercio ?? ''} ${TIPOS_TRANSACCION[fila.tipo] ?? fila.tipo} ${ESTADOS_TRANSACCION[fila.estado]?.texto ?? fila.estado} ${fila.monto} ${fila.moneda}`.toLowerCase();
            const coincideBusqueda = filtro.trim() === '' || texto.includes(filtro.toLowerCase());

            return coincideTarjeta && coincideBusqueda;
        })
    );

    const rechazadas = $derived(transaccionesFiltradas.filter((fila) => fila.estado === 'Declined').length);
    const tarjetasConMovimientos = $derived(new Set(transaccionesFiltradas.map((fila) => fila.tarjeta.ref)).size);
    const truncadas = $derived(
        (data.transacciones?.tarjetas ?? []).filter((tarjeta) => tarjeta.truncada && (data.tarjeta === 'Todas' || tarjeta.ref === data.tarjeta))
    );

    // Tarjeta y periodo van en la URL: el periodo vuelve a leer la API (de 1 a 90 días, POL-ANS-03).
    function cambiar(parametro: 'tarjeta' | 'dias', valor: string) {
        const url = new URL(page.url);
        url.searchParams.set(parametro, valor);
        goto(url, { keepFocus: true, noScroll: true, replaceState: true });
    }

    function seleccionarTransaccion(fila: Fila) {
        transaccionSeleccionada = fila;
    }

    function cerrarDetalle() {
        transaccionSeleccionada = null;
    }

    // Abre el chat con el pedido escrito; el cliente lo revisa y lo envía.
    function preguntar(fila: Fila, desconoce: boolean) {
        const articulo = ARTICULOS[fila.tipo] ?? 'la transacción';
        const deComercio = fila.comercio ? ` de ${fila.comercio}` : '';
        const detalle = `${deComercio} del ${fechaLarga(fila.fecha)} por ${fila.monto} ${fila.moneda} en mi tarjeta de ${tipoCorto(fila.tarjeta.tipo)} terminada en ${fila.tarjeta.last4}`;
        const mensaje = desconoce
            ? `No reconozco ${articulo}${detalle}.`
            : fila.estado === 'Declined'
              ? `¿Por qué rechazaron ${articulo}${detalle}?`
              : `¿Qué es ${articulo}${detalle}?`;
        goto(`/app/consultas?mensaje=${encodeURIComponent(mensaje)}`);
    }
</script>

<svelte:head>
    <title>Transacciones | Agente</title>
</svelte:head>


<div class="space-y-4">
    <section>
        <div class="flex items-center justify-between">
            <div class="space-y-4">
                <span class="block font-light">
                    {#if data.transacciones}
                        Del {formatearFechaBanco(data.transacciones.desde, false)} al {formatearFechaBanco(data.transacciones.hasta, false)} · reloj del banco
                    {:else}
                        Información verificada
                    {/if}
                </span>
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

    {#if data.enRevision}
        <section>
            <div class="bg-amber-50 p-4 rounded-xl text-amber-800">
                Su cuenta está en revisión: un asesor atenderá su caso. Mientras tanto no podemos mostrar sus movimientos.
            </div>
        </section>
    {:else}
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
                    <span class="text-red-500">Rechazadas</span>
                </div>
                <h3 class="font-bold">{rechazadas}</h3>
                <h4 class="separar-letras">Puedes preguntar por qué</h4>
            </article>

            <article class="bg-white p-2 rounded-xl space-y-5">
                <div class="flex gap-2 items-center">
                    <Transaccion _class="fill-gris-secundario/62 h-6 w-6" />
                    <span>Tarjetas Utilizadas</span>
                </div>
                <h3 class="font-bold">{tarjetasConMovimientos}</h3>
                <h4 class="separar-letras">Con movimientos en el periodo</h4>
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

                        <input id="buscar" type="text" bind:value={filtro} placeholder="Comercio, tipo, estado o monto..." class="bg-slate-50 focus:bg-white focus:ring-2 focus:ring-red-100 outline-none placeholder:text-slate-400 pl-9 pr-3 py-2.5 rounded-xl text-sm transition-all w-full"
                        />
                    </div>
                </div>

                <!-- Tarjeta -->
                <div class="bg-white p-4 rounded-xl">
                    <label for="tarjeta" class="block font-semibold mb-2 text-xs">
                        Tarjeta
                    </label>

                    <select id="tarjeta" value={data.tarjeta} onchange={(event) => cambiar('tarjeta', event.currentTarget.value)} class="bg-slate-50 focus:ring-2 focus:ring-red-100 px-3 py-2.5 rounded-xl text-sm outline-none  w-full"
                    >
                        <option value="Todas">Todas las tarjetas</option>

                        {#each data.transacciones?.tarjetas ?? [] as tarjeta (tarjeta.ref)}
                            <option value={tarjeta.ref}>
                                {tipoCorto(tarjeta.tipo) === 'débito' ? 'Débito' : 'Crédito'} •••• {tarjeta.last4}
                            </option>
                        {/each}
                    </select>
                </div>

                <!-- Periodo -->
                <div class="bg-white p-4 rounded-xl">
                    <label for="periodo" class="block font-semibold mb-2 text-xs">
                        Periodo
                    </label>

                    <select id="periodo" value={String(data.dias)} onchange={(event) => cambiar('dias', event.currentTarget.value)} class="bg-slate-50 focus:ring-2 focus:ring-red-100 px-3 py-2.5 rounded-xl text-sm outline-none w-full">
                        <option value="7">Últimos 7 días</option>
                        <option value="30">Últimos 30 días</option>
                        <option value="90">Últimos 90 días</option>
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
                    {#each truncadas as tarjeta (tarjeta.ref)}
                        <p class="mt-2 text-xs!">La tarjeta •••• {tarjeta.last4} tiene más movimientos en el periodo: se muestran los 20 más recientes. Pide más detalle al asistente.</p>
                    {/each}
                </div>

                {#if transaccionesFiltradas.length > 0}
                    <div class="divide-y divide-slate-100">
                        {#each transaccionesFiltradas as transaccion}
                            {@const estado = ESTADOS_TRANSACCION[transaccion.estado] ?? { texto: transaccion.estado, clase: 'text-slate-500' }}
                            <button type="button" onclick={() => seleccionarTransaccion(transaccion)} class="cursor-pointer duration-300 flex flex-wrap gap-4 group hover:bg-slate-50 items-center px-5 py-4 text-left transition-all w-full">
                                <!-- Icono -->
                                <div class={`flex h-8 items-center justify-center rounded-xl shrink-0 w-8 ${transaccion.estado === 'Declined' ? 'bg-red-50 text-red-600' : 'bg-slate-100'}`}>
                                    <Transaccion _class="fill-gris-secundario/62 h-4 w-4" />
                                </div>

                                <!-- Información -->
                                <div class="flex-1 min-w-0">
                                    <div class="flex gap-2 items-center">
                                        <p class="font-semibold truncate text-sm">
                                            {transaccion.comercio ?? TIPOS_TRANSACCION[transaccion.tipo] ?? transaccion.tipo}
                                        </p>

                                        <span class="bg-slate-100 font-medium hidden px-2 py-0.5 rounded-md text-[10px] text-slate-500 sm:inline">
                                            {TIPOS_TRANSACCION[transaccion.tipo] ?? transaccion.tipo}
                                        </span>
                                    </div>

                                    <div class="flex gap-2 items-center mt-1 text-[11px] text-slate-400">
                                        <span>{formatearFechaBanco(transaccion.fecha)}</span>
                                        <span>•</span>
                                        <span>{tipoCorto(transaccion.tarjeta.tipo) === 'débito' ? 'Débito' : 'Crédito'} •••• {transaccion.tarjeta.last4}</span>
                                    </div>
                                </div>

                                <!-- Monto -->
                                <div class="text-right">
                                    <p class="font-bold text-slate-800 text-sm">
                                        {formatearMonto(transaccion.monto, transaccion.moneda)}
                                    </p>

                                    <p class={`mt-1 text-[11px]! ${estado.clase}`}>
                                        {estado.texto}
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
                            Prueba con otra tarjeta, otro periodo u otra búsqueda.
                        </p>
                    </div>
                {/if}
            </div>
        </div>
    </section>
    {/if}
</div>

<!-- Modal detalle -->
{#if transaccionSeleccionada}
    {@const estado = ESTADOS_TRANSACCION[transaccionSeleccionada.estado] ?? { texto: transaccionSeleccionada.estado, clase: 'text-slate-500' }}
    <div class="backdrop-blur-sm bg-slate-900/40 flex fixed inset-0 items-center justify-center px-4 z-50" role="presentation" onclick={(event) => { if (event.target === event.currentTarget) cerrarDetalle();}}>
        <div class="bg-white max-w-md rounded-2xl w-full">
            <!-- Header -->
            <div class="flex items-start justify-between p-5">
                <div>
                    <p class="font-medium text-xs tracking-wide uppercase">
                        Detalle de transacción
                    </p>

                    <h2 class="font-bold mt-1 text-lg">
                        {transaccionSeleccionada.comercio ?? TIPOS_TRANSACCION[transaccionSeleccionada.tipo] ?? transaccionSeleccionada.tipo}
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
                    {formatearMonto(transaccionSeleccionada.monto, transaccionSeleccionada.moneda)}
                </p>

                <span class={`font-semibold inline-flex mt-2 px-3 py-1 rounded-full text-xs ${estado.clase}`}>
                    {estado.texto}
                </span>
            </div>

            <!-- Datos -->
            <div class="p-5 space-y-4 ">
                <div class="border-b border-slate-100 flex items-center justify-between pb-3">
                    <span class="text-sm">Tipo</span>
                    <span class="font-medium text-right text-sm">
                        {TIPOS_TRANSACCION[transaccionSeleccionada.tipo] ?? transaccionSeleccionada.tipo}
                    </span>
                </div>

                <div class="border-b border-slate-100 flex items-center justify-between pb-3">
                    <span class="text-sm">Fecha</span>
                    <span class="font-medium text-right text-sm">
                        {formatearFechaBanco(transaccionSeleccionada.fecha)}
                    </span>
                </div>

                <div class="flex items-center justify-between">
                    <span class="text-sm">Tarjeta</span>
                    <span class="font-medium text-right text-sm">
                        {transaccionSeleccionada.tarjeta.tipo} •••• {transaccionSeleccionada.tarjeta.last4}
                    </span>
                </div>
            </div>

            <!-- Acción -->
            <div class="p-5 space-y-2">
                <button type="button" onclick={() => transaccionSeleccionada && preguntar(transaccionSeleccionada, false)} class="bg-red-500 cursor-pointer flex font-semibold gap-2 hover:bg-red-400 items-center justify-center rounded-xl px-4 py-3 text-sm text-white transition-all w-full">
                    {transaccionSeleccionada.estado === 'Declined' ? '¿Por qué fue rechazada?' : 'Consultar esta transacción'}
                </button>
                <button type="button" onclick={() => transaccionSeleccionada && preguntar(transaccionSeleccionada, true)} class="border border-slate-200 cursor-pointer font-semibold hover:bg-slate-50 px-4 py-3 rounded-xl text-sm transition w-full">
                    No reconozco este cargo
                </button>

                <p class="leading-4 mt-2 text-center text-[11px]">
                    El asistente solo proporcionará información que pueda verificar con los datos de tu cuenta.
                </p>
            </div>
        </div>
    </div>
{/if}
