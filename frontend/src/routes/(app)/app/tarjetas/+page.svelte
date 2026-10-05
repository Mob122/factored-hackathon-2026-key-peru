<script lang="ts">
	import { goto } from '$app/navigation';
	import Seguridad from '$lib/assets/icons/Seguridad.svelte';
	import Tarjeta from '$lib/assets/icons/Tarjeta.svelte';
	import Transaccion from '$lib/assets/icons/Transaccion.svelte';
	import { ESTADOS_TARJETA, tipoCorto } from '$lib/utils/formato';
	import type { Tarjeta as TipoTarjeta } from '$lib/types';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

    let tarjetaSeleccionada = $state<TipoTarjeta | null>(null);

    let usuario = $derived(data.usuario);

    function abrirBloqueo(tarjeta: TipoTarjeta) {
        tarjetaSeleccionada = tarjeta;
    }

    function cerrarBloqueo() {
        tarjetaSeleccionada = null;
    }

    // El bloqueo lo hace el asistente, con verificación adicional y confirmación (POL-AUTH-04, POL-ACT-02):
    // la página solo abre el chat con el pedido escrito.
    function continuarBloqueo() {
        if (!tarjetaSeleccionada) return;
        const mensaje = `Quiero bloquear mi tarjeta de ${tipoCorto(tarjetaSeleccionada.tipo)} terminada en ${tarjetaSeleccionada.last4}.`;
        cerrarBloqueo();
        goto(`/app/consultas?mensaje=${encodeURIComponent(mensaje)}`);
    }
</script>

<svelte:head>
    <title>Mis tarjetas | Agente</title>
</svelte:head>

<div class="space-y-4">
    <section>
        <div class="flex items-center justify-between">
            <div class="space-y-4">
                <span class="block font-light">Consulta el estado y la información de tus tarjetas</span>
                <h1>Mis tarjetas</h1>
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
        <div>
            <div class="space-y-4">
                <div class="bg-white p-4 rounded-2xl">
                    <div class="flex gap-2 items-center">
                        <Seguridad _class="fill-green-600 h-5 w-5" />
                        <h2 class="font-semibold text-sm">
                            Información protegida
                        </h2>
                    </div>

                    <ul class="mt-3 list-disc list-inside">
                        <li>Solo mostramos los últimos 4 dígitos de cada tarjeta.</li>
                        <li>Las acciones sensibles requieren verificación adicional.</li>
                    </ul>

                </div>
            </div>
        </div>
    </section>

     <section>
        <div class="space-y-3">
            <h2>Selecciona una Tarjeta para Consultar sus Detalles</h2>

            {#if data.enRevision}
                <div class="bg-amber-50 p-4 rounded-xl text-amber-800">
                    Su cuenta está en revisión: un asesor atenderá su caso. Mientras tanto no podemos mostrar sus tarjetas.
                </div>
            {:else if data.tarjetas.length === 0}
                <div class="bg-white p-6 rounded-2xl text-center">No tiene tarjetas registradas.</div>
            {/if}

            <div class="grid gap-5 lg:grid-cols-2">
                {#each data.tarjetas as tarjeta (tarjeta.ref)}
                    {@const estado = ESTADOS_TARJETA[tarjeta.estado] ?? { texto: tarjeta.estado, color: 'bg-slate-400' }}
                    <article class="bg-white overflow-hidden rounded-2xl shadow-sm">
                        <div class="p-4">
                            <div class="flex items-center justify-between">
                                <Tarjeta _class="fill-gris-secundario/62 h-10 w-10" />

                                <span class="flex items-center">
                                    <span class={`h-1.5 inline-block mr-1.5 rounded-full w-1.5 ${estado.color}`}></span>
                                    {estado.texto}
                                </span>
                            </div>


                            <div class="mt-8">
                                <p class="font-medium text-xs! tracking-wider uppercase">
                                    {tarjeta.tipo}
                                </p>
                                <p class="font-mono mt-2 text-xl text-gris-secundario! tracking-widest">
                                    •••• •••• •••• {tarjeta.last4}
                                </p>
                                <p class="mt-3 separar-letras text-sm!">
                                    {usuario?.nombre ?? 'Titular'}
                                </p>
                            </div>
                        </div>

                        <div class="grid grid-cols-2 border-t border-slate-100">
                            <a href={`/app/transacciones?tarjeta=${tarjeta.ref}`} class="flex font-semibold hover:bg-slate-50! hover:text-gris-secundario! items-center justify-center gap-2 group px-4 py-4 rounded-none! text-sm transition-color "
                            >
                                <Transaccion _class="fill-gris-secundario/62 h-5 group-hover:fill-gris-secundario transition-color w-5" />

                                Transacciones
                            </a>

                            {#if tarjeta.estado === 'Active'}
                                <button class="border-l border-slate-100 cursor-pointer font-semibold hover:bg-red-50 px-4 py-4 text-sm text-red-500 transition-all" onclick={() => abrirBloqueo(tarjeta)}>
                                    Bloquear tarjeta
                                </button>
                            {:else}
                                <button class="border-l border-slate-100 font-semibold px-4 py-4 text-gris-secundario/44 text-sm" disabled>
                                    {estado.texto}
                                </button>
                            {/if}
                        </div>
                    </article>
                {/each}

            </div>
        </div>
    </section>
</div>


{#if tarjetaSeleccionada}
    <div class="backdrop-blur-sm bg-slate-950/50 fixed flex inset-0 items-center justify-center p-5 z-50" role="presentation"
        onclick={(event) => {
            if (event.target === event.currentTarget) cerrarBloqueo();
        }}
    >
        <div class="bg-white max-w-md rounded-3xl p-7 shadow-2xl">
            <div class="flex justify-center">
                <Tarjeta _class="fill-gris-secundario/62 h-7 w-7" />
            </div>

            <div class="mt-5 text-center">
                <h2 class="font-bold text-xl">¿Quieres bloquear la tarjeta •••• {tarjetaSeleccionada.last4}?</h2>

                <p class="mt-3">
                    El asistente te pedirá un código de verificación y tu confirmación. Después del bloqueo la tarjeta deja de funcionar y solo un asesor puede desbloquearla.
                </p>
            </div>

            <div class="bg-amber-50 mt-5 p-4 rounded-xl text-amber-800 text-sm">
                <div class="flex gap-3 items-center">
                    <span>⚠️</span>
                    <p>El bloqueo es una acción sensible: solo se ejecuta después de la verificación y de un sí explícito en el chat.</p>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-3 mt-6">
                <button class="border border-slate-200 cursor-pointer font-semibold hover:bg-slate-50 px-4 py-3 rounded-xl text-sm transition" onclick={cerrarBloqueo}>
                    Cancelar
                </button>

                <button class="bg-red-500 cursor-pointer font-semibold hover:bg-red-600 px-4 py-3 rounded-xl text-sm text-white transition-colors" onclick={continuarBloqueo}>
                    Continuar en el chat
                </button>
            </div>
        </div>
    </div>
{/if}

<style>
    .separar-letras {
        letter-spacing: 0.1em;
    }
</style>
