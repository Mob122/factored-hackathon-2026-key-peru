<script lang="ts">
	import MasterCard from '$lib/assets/icons/MasterCard.svelte';
	import Seguridad from '$lib/assets/icons/Seguridad.svelte';
	import Tarjeta from '$lib/assets/icons/Tarjeta.svelte';
	import Transaccion from '$lib/assets/icons/Transaccion.svelte';
	import Visa from '$lib/assets/icons/Visa.svelte';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

    let tarjetaSeleccionada = $state<string | null>(null);
    let mostrarBloqueo = $state(false);

    // Datos mock mientras conectamos el backend.
    const tarjetas = [
        {
            id: 'card-001',
            ultimos4: '4821',
            tipo: 'Visa',
            categoria: 'Crédito',
            estado: 'Activa',
            numero: '•••• •••• •••• 4821',
            titular: data.usuario?.nombre ?? 'Titular'
        },
        {
            id: 'card-002',
            ultimos4: '9137',
            tipo: 'Mastercard',
            categoria: 'Débito',
            estado: 'Activa',
            numero: '•••• •••• •••• 9137',
            titular: data.usuario?.nombre ?? 'Titular'
        },
        {
            id: 'card-003',
            ultimos4: '1054',
            tipo: 'Visa',
            categoria: 'Crédito',
            estado: 'Bloqueada',
            numero: '•••• •••• •••• 1054',
            titular: data.usuario?.nombre ?? 'Titular'
        }
    ];

    function abrirBloqueo(id: string) {
        tarjetaSeleccionada = id;
        mostrarBloqueo = true;
    }

    function cerrarBloqueo() {
        mostrarBloqueo = false;
        tarjetaSeleccionada = null;
    }

    let usuario = $derived(data.usuario);
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
    
            <div class="grid gap-5 lg:grid-cols-2">
                {#each tarjetas as tarjeta}
                    <article class="bg-white overflow-hidden rounded-2xl shadow-sm">                        
                        <div class="p-4">
                            <div class="flex items-center justify-between">
                                {#if tarjeta.tipo === 'Visa'}
                                    <Visa _class="fill-blue-800 h-17 w-17" />
                                {:else}
                                    <MasterCard _class="h-17 w-17" />
                                {/if}
                                
                                <span class="flex items-center">
                                    <span
                                        class={`h-1.5 inline-block mr-1.5 rounded-full w-1.5 ${tarjeta.estado === 'Activa'? 'bg-green-500' : 'bg-red-500'}`}
                                    ></span>

                                    {tarjeta.estado}
                                </span>
                            </div>
    
        
                            <div class="mt-8">
                                <p class="font-medium text-xs! tracking-wider uppercase">
                                    {tarjeta.categoria}
                                </p>
                                <p class="font-mono mt-2 text-xl text-gris-secundario! tracking-widest">
                                    {tarjeta.numero}
                                </p>
                                <p class="mt-3 separar-letras text-sm!">
                                    {tarjeta.titular}
                                </p>    
                            </div>    
                        </div>
    
                        <div class="grid grid-cols-2 border-t border-slate-100">  
                            <a href="/app/transacciones" class="flex font-semibold hover:bg-slate-50! hover:text-gris-secundario! items-center justify-center gap-2 group px-4 py-4 rounded-none! text-sm transition-color "
                            >
                                <Transaccion _class="fill-gris-secundario/62 h-5 group-hover:fill-gris-secundario transition-color w-5" />
    
                                Transacciones
                            </a>
    
                            {#if tarjeta.estado === 'Activa'}
                                <button class="border-l border-slate-100 cursor-pointer font-semibold hover:bg-red-50 px-4 py-4 text-sm text-red-500 transition-all" onclick={() => abrirBloqueo(tarjeta.id)}>
                                    Bloquear tarjeta
                                </button>
                            {:else}
                                <button class="border-l border-slate-100 font-semibold px-4 py-4 text-gris-secundario/44 text-sm" disabled>
                                    Bloqueada
                                </button>
                            {/if} 
                        </div>
                    </article>
                {/each}
    
            </div>
        </div>
    </section>
</div>


{#if mostrarBloqueo}
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
                <h2 class="font-bold text-xl">¿Quieres bloquear esta tarjeta?</h2>

                <p class="mt-3">
                    Esta acción requiere una verificación adicional. La tarjeta quedará bloqueada y posteriormente verificaremos su nuevo estado.
                </p>
            </div>

            <div class="bg-amber-50 mt-5 p-4 rounded-xl text-amber-800 text-sm">
                <div class="flex gap-3 items-center">
                    <span>⚠️</span>
                    <p>El bloqueo es una acción sensible y no puede ejecutarse únicamente a partir de una instrucción del asistente.</p>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-3 mt-6">
                <button class="border border-slate-200 cursor-pointer font-semibold hover:bg-slate-50 px-4 py-3 rounded-xl text-sm transition" onclick={cerrarBloqueo}>
                    Cancelar
                </button>

                <button class="bg-red-500 cursor-pointer font-semibold hover:bg-red-600 px-4 py-3 rounded-xl text-sm text-white transition-colors" onclick={() => { cerrarBloqueo(); }}>
                    Continuar
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