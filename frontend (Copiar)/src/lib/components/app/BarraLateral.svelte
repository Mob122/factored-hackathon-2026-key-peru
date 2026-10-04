<script lang="ts">
	import { page } from "$app/state";
	import type { Component } from "svelte";

    let { abrir = $bindable(), rutas }: {
        abrir: boolean;
        rutas: Record<string, { texto: string; enlace: string, icono?: Component<{ _class: string | string[] }> }[]>
    } = $props();

    const rutaActual = $derived(page.url.pathname);
    const usuario = $derived(page.data.usuario);
</script>

 
{#if abrir}
    <button aria-label="Cerrar menú" class="bg-slate-950/40 fixed inset-0 z-40 md:hidden" onclick={ () => abrir = false }></button>
{/if}

<aside class={["fixed p-4 left-0 transition-transform -translate-x-full w-full z-50 md:translate-x-0 md:w-80", { "translate-x-0": abrir }].filter(Boolean)}>
    <div class={["bg-white flex flex-col h-[97vh] px-3 py-4 rounded-xl"]}>    
        <div class="flex h-17 items-center">            
            <div class="flex items-center gap-2">
                <div class="bg-red-500 font-bold flex h-8 items-center justify-center rounded-xl text-white w-8">
                    <svg class="h-5 stroke-white w-5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path d="M12.3212 10.6852L4 19L6 21M7 16L9 18M20 7.5C20 9.98528 17.9853 12 15.5 12C13.0147 12 11 9.98528 11 7.5C11 5.01472 13.0147 3 15.5 3C17.9853 3 20 5.01472 20 7.5Z"  stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></path> </g></svg>                
                </div>                                    
                <h2 class="font-semibold text-black text-lg">key Perú</h2>
            </div>
    
            <button aria-label="Cerrar menú" class="ml-auto text-slate-400 md:hidden" onclick={() => abrir = false } >
                <svg class="h-6 stroke-red-500 w-6" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <g id="System / Bar_Left"> <path id="Vector" d="M9 20V4M9 20H16.8031C17.921 20 18.48 20 18.9074 19.7822C19.2837 19.5905 19.5905 19.2837 19.7822 18.9074C20 18.48 20 17.921 20 16.8031V7.19691C20 6.07899 20 5.5192 19.7822 5.0918C19.5905 4.71547 19.2837 4.40973 18.9074 4.21799C18.4796 4 17.9203 4 16.8002 4H9M9 20H7.19692C6.07901 20 5.5192 20 5.0918 19.7822C4.71547 19.5905 4.40973 19.2837 4.21799 18.9074C4 18.4796 4 17.9203 4 16.8002V7.2002C4 6.08009 4 5.51962 4.21799 5.0918C4.40973 4.71547 4.71547 4.40973 5.0918 4.21799C5.51962 4 6.08009 4 7.2002 4H9"  stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path> </g> </g></svg>
            </button>    
        </div>
        
        <nav class="flex-1 overflow-y-auto">
            <div class="mb-8">
                <p class="font-bold mb-4 px-3 text-xs tracking-wider">
                    Menú Principal
                </p>
    
                <ul class="space-y-2">
                    {#each rutas.RutasPrincipales as ruta}
                        <li class="">
                            <a class={['flex items-center gap-2 group p-2 rounded-md', rutaActual === ruta.enlace && 'bg-red-500 text-white']} href={ruta.enlace} onclick={() => abrir = false }>                                
                                <ruta.icono _class={["fill-gris-secundario/62  h-5 w-5", rutaActual === ruta.enlace && 'fill-white'].filter(Boolean).join(' ')} />
                                {ruta.texto}                                
                            </a>
                        </li>
                    {/each}                            
                </ul>
            </div>
            <div class="mb-8">
                <p class="font-bold mb-4 px-3 text-xs tracking-wider">
                    Atención
                </p>

                <ul class="space-y-2">
                    {#each rutas.RutasAtencion as ruta}
                        <li class="">
                            <a class={['flex items-center gap-2 group p-2 rounded-md', rutaActual === ruta.enlace && 'bg-red-500 text-white']} href={ruta.enlace} onclick={() => abrir = false }>
                                <ruta.icono _class={["fill-gris-secundario/62  h-5 w-5", rutaActual === ruta.enlace && 'fill-white'].filter(Boolean).join(' ')} />
                                {ruta.texto}
                            </a>
                        </li>
                    {/each}                            
                </ul>
            </div>
            <div>
                <p class="font-bold mb-4 px-3 text-xs tracking-wider">
                    Seguridad
                </p>

                <ul class="space-y-5">
                    {#each rutas.RutasSeguridad as ruta}
                        <li class="flex gap-2 items-center">
                            <a class={['flex items-center gap-2 group p-2 rounded-md', rutaActual === ruta.enlace && 'bg-red-500 text-white']} href={ruta.enlace} onclick={() => abrir = false }>
                                <ruta.icono _class={["fill-gris-secundario/62  h-5 w-5", rutaActual === ruta.enlace && 'fill-white'].filter(Boolean).join(' ')} />
                                {ruta.texto}
                            </a>
                        </li>
                    {/each}                            
                </ul>
            </div>
        </nav>

         
        <div class="border border-slate-300 flex gap-3 items-center p-3 rounded-xl">
            <div class="bg-red-500 flex font-bold h-9 items-center justify-center rounded-full shrink-0 text-sm  text-white w-9">
                {usuario.nombre.charAt(0)?.toUpperCase() ?? 'U'}
            </div>

            <div class="min-w-0">
                <p class="font-semibold text-sm text-slate-800 truncate">
                    {usuario.nombre ?? 'Usuario'}
                </p>

                <p class="text-slate-500 text-xs">
                    {usuario.correo_electronico}
                </p>
            </div>            
        </div>
    </div>
</aside>