<script lang="ts">
	import Atencion from '$lib/assets/icons/Atencion.svelte';
	import Caso from '$lib/assets/icons/Caso.svelte';
	import Consulta from '$lib/assets/icons/Consulta.svelte';
	import Seguridad from '$lib/assets/icons/Seguridad.svelte';
	import Tarjeta from '$lib/assets/icons/Tarjeta.svelte';
	import Transaccion from '$lib/assets/icons/Transaccion.svelte';

    import Llave from '$lib/assets/llave-3d.webp';
	import Circular from '$lib/components/graficos/Circular.svelte';
	import Linea from '$lib/components/graficos/Linea.svelte';
	import { RUTAS } from '$lib/data/rutas';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

    let usuario = $derived(data.usuario);

</script>

<svelte:head>
    <title>Key Perú | Resumen</title>
</svelte:head>

<div class="space-y-4">
    <section>
        <div class="space-y-4">
            <span class="block font-light">¿Estás Listo para Interactuar con un Agente sobre tus Tarjetas y Transacciones?</span>
            <h1>Bienvenido Nuevamente, {usuario?.nombre}!</h1>
        </div>
    </section>
    
    <section>
        <div>
            <div class="space-y-4">            
                <div class="grid gap-4 xl:grid-cols-[repeat(auto-fit,minmax(300px,1fr))]">                            
                    <article class="bg-white p-2 rounded-xl space-y-5">
                        <div class="flex gap-2 items-center">
                            <Transaccion _class="fill-gris-secundario/62 h-6 w-6" />
                            <span>Transacciones Totales</span>
                        </div>
                        <h3 class="font-bold">42</h3>
                        <h4 class="separar-letras">Transacciones realizadas</h4>
                    </article>            
                    <article class="bg-white p-2 rounded-xl space-y-5">
                        <div class="flex gap-2 items-center">
                            <Tarjeta _class="fill-gris-secundario/62 h-6 w-6" />
                            <span>Tarjetas Totales</span>
                        </div>
                        <h3 class="font-bold">8</h3>
                        <h4 class="separar-letras">Tarjetas</h4>
                    </article>            
                    <article class="bg-white p-2 rounded-xl space-y-5">
                        <div class="flex gap-2 items-center">
                            <Consulta _class="fill-gris-secundario/62 h-6 w-6" />
                            <span>Consultas Totales</span>
                        </div>
                        <h3 class="font-bold">8</h3>
                        <h4 class="separar-letras">Consultas realizadas</h4>
                    </article>            
                    <article class="bg-white p-2 rounded-xl space-y-5">
                        <div class="flex gap-2 items-center">
                            <Caso _class="fill-gris-secundario/62 h-6 w-6" />
                            <span>Casos Totales</span>
                        </div>
                        <h3 class="font-bold">17</h3>
                        <h4 class="separar-letras">Casos realizados</h4>
                    </article>            
                </div>
                <div class="bg-linear-to-r flex from-red-500 group justify-between px-4 py-4 rounded-xl text-white to-red-300 xl:px-26 xl:py-8">
                    <div class="py-12 space-y-8">
                        <h2 class="font-bold">¿En qué podemos ayudarte?</h2>
                        <p class="mb-14 text-white!">Consulta tus tarjetas y transacciones, revisa el estado de una tarjeta o solicita ayuda con una operación.</p>
                        <a class="bg-white! font-bold hover:bg-red-800! text-gris-secundario/62" href="/app/consultas">Consulta al Agente</a>
                    </div>
    
                    <figure class="relative hidden xl:block">
                        <img class="group-hover:-rotate-45 h-71 transition-all w-full" src={Llave} alt="llave">                        
                    </figure>
                </div>
            </div>
        </div>
    </section>
    
    <section>
        <div>
            <div class="grid gap-4 xl:grid-cols-[repeat(auto-fit,minmax(300px,1fr))]">
                <div class="bg-white p-4 rounded-2xl space-y-5">
                    <div class="flex gap-2 items-center">
                        <Transaccion _class="fill-gris-secundario/62 h-6 w-6" />
                        <div>
                            <span class="font-bold">Transacciones</span>
                            <span class="block text-gray-400">Las últimas 30 transacciones diarias</span>
                        </div>
                    </div>
                    <Linea classLinea={'stroke-red-500'} />
                </div>
                <div class="grid gap-4 rounded-2xl xl:grid-cols-[repeat(auto-fit,minmax(300px,1fr))]">
                    <div class="bg-white rounded-2xl p-4">                
                        <div class="flex gap-2 items-center">
                            <Caso _class="fill-gris-secundario/62 h-6 w-6" />                        
                            <span class="font-bold">Mis Casos</span>
                        </div>
                        <Circular />                
                    </div>
                    <div class="bg-white p-4 rounded-2xl">
                        <div>
                            <div class="flex gap-2 items-center">
                                <svg class="h-6 fill-gris-secundario/62 w-6" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path fill-rule="evenodd" clip-rule="evenodd" d="M11.2929 2.29289C11.6834 1.90237 12.3166 1.90237 12.7071 2.29289L16.7071 6.29289C17.0976 6.68342 17.0976 7.31658 16.7071 7.70711C16.3166 8.09763 15.6834 8.09763 15.2929 7.70711L13 5.41421V15C13 15.5523 12.5523 16 12 16C11.4477 16 11 15.5523 11 15V5.41421L8.70711 7.70711C8.31658 8.09763 7.68342 8.09763 7.29289 7.70711C6.90237 7.31658 6.90237 6.68342 7.29289 6.29289L11.2929 2.29289ZM5 13C5 11.3431 6.34315 10 8 10H9C9.55228 10 10 10.4477 10 11C10 11.5523 9.55228 12 9 12H8C7.44772 12 7 12.4477 7 13V19C7 19.5523 7.44772 20 8 20H16C16.5523 20 17 19.5523 17 19V13C17 12.4477 16.5523 12 16 12H15C14.4477 12 14 11.5523 14 11C14 10.4477 14.4477 10 15 10H16C17.6569 10 19 11.3431 19 13V19C19 20.6569 17.6569 22 16 22H8C6.34315 22 5 20.6569 5 19V13Z" ></path> </g></svg>
                                <span class="font-bold">Acciones Rápidas</span>
                            </div>
                            <ul class="gap-4 grid grid-cols-2 mt-7">
                                {#each RUTAS.RutasPrincipales as ruta}
                                    <li>
                                        <a href={ruta.enlace} class="flex flex-col group items-center text-gray-400">
                                            <ruta.icono _class="fill-gris-secundario/62 h-6 group-hover:fill-white transition-colors w-6" />
                                            {ruta.texto}
                                        </a>
                                    </li>
                                {/each}
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>
                
    <section>
        <div>
            <div class="grid gap-2 xl:grid-cols-3">
                <div class="bg-white p-4 rounded-xl space-y-2 xl:col-span-2">
                    <div>
                        <div class="flex font-bold gap-2 items-center">
                            <Seguridad _class="h-6 w-6" />
                            <h3>Tus datos están protegidos</h3>
                        </div>
                        <p>El asistente solo responde utilizando información verificada de tu cuenta. Las acciones sensibles requieren confirmación y verificación adicional.</p>
                    </div>
    
                    <div class="flex flex-wrap gap-4">
                        <article class="bg-slate-100 cursor-grab duration-300 group hover:bg-red-500 p-4 rounded-xl transition-colors">
                            <h4 class="font-bold group-hover:text-white!">Verificación</h4>
                            <p class="group-hover:text-white! separar-letras">Step-up</p>
                        </article>
                        <article class="bg-slate-100 cursor-grab duration-300 group hover:bg-red-500 p-4 rounded-xl transition-colors">
                            <h4 class="font-bold group-hover:text-white!">Acciones</h4>
                            <p class="group-hover:text-white! separar-letras">Con confirmación</p>
                        </article>
                        <article class="bg-slate-100 cursor-grab duration-300 group hover:bg-red-500 p-4 rounded-xl transition-colors">
                            <h4 class="font-bold group-hover:text-white!">Escalamiento</h4>
                            <p class="group-hover:text-white! separar-letras">A un humano</p>
                        </article>
                    </div>
                </div>
    
                <a href="/app/casos" class="bg-white group p-4 rounded-xl space-y-2">
                    <div class="flex flex-col h-full">
                        <div class="flex-1">
                            <div class="flex gap-2 items-center">
                                <Atencion _class="fill-gris-secundario/62 group-hover:fill-white h-6 transition-colors w-6" />
                                <h3 class="font-bold">Atención</h3>
                            </div>
                            <p class="group-hover:text-white! mt-4 transition-colors"><span class="font-bold text-6xl">2</span> casos requieren seguimiento</p>                
                        </div>
                        <span class="group-hover:text-white! transition-colors">Ver mis casos</span>                    
                    </div>                
                </a>
            </div>
        </div>
    </section>
</div>
    

<style>
    .separar-letras {
        letter-spacing: 0.08rem;
    }
</style>