<script lang="ts">
	import { page } from "$app/state";
    import Llave from '$lib/assets/llave.gif';

    const { rutas }: { rutas: { texto: string; enlace: string }[] } = $props();

    let menuAbierto = $state(false);

    const rutaActual = $derived(page.url.pathname);
</script>

<header class="pt-5 sticky top-0 z-100">
    <div class="contenedor grid grid-cols-2 xl:grid-cols-3">
        <div class="self-center">            
            <h1 class="font-bold font-playfair-display text-xl md:text-3xl"> <img src={Llave} alt="Llave" class="h-8  inline mb-2 w-8" />               
                <span class="bg-clip-text bg-linear-to-tr font-extrabold from-white text-transparent to-red-500">
                    Perú
                </span>                
            </h1>
        </div>
        
         <nav class="flex items-center justify-end xl:place-self-center">
            <button aria-expanded={menuAbierto} aria-label={menuAbierto ? "Cerrar menú" : "Abrir menú"} class="cursor-pointer xl:hidden z-100" onclick={() => {
                menuAbierto = !menuAbierto;
            }}>
                {#if menuAbierto}                    
                    <svg class="fill-red-500 h-5 w-5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path d="M20.7457 3.32851C20.3552 2.93798 19.722 2.93798 19.3315 3.32851L12.0371 10.6229L4.74275 3.32851C4.35223 2.93798 3.71906 2.93798 3.32854 3.32851C2.93801 3.71903 2.93801 4.3522 3.32854 4.74272L10.6229 12.0371L3.32856 19.3314C2.93803 19.722 2.93803 20.3551 3.32856 20.7457C3.71908 21.1362 4.35225 21.1362 4.74277 20.7457L12.0371 13.4513L19.3315 20.7457C19.722 21.1362 20.3552 21.1362 20.7457 20.7457C21.1362 20.3551 21.1362 19.722 20.7457 19.3315L13.4513 12.0371L20.7457 4.74272C21.1362 4.3522 21.1362 3.71903 20.7457 3.32851Z"></path> </g></svg>
                {:else}
                    <svg class="h-5 stroke-red-500 w-5 z-100" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="SVGRepo_iconCarrier"> <path d="M4 6H20M4 12H20M4 18H20" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path> </g></svg>
                {/if}
            </button>


            <ul class={["auto-rows-max bg-white duration-300 fixed gap-2 grid inset-y-0 place-content-center place-items-center px-4 right-0 rounded-bl-3xl rounded-tl-3xl transition-transform w-[60%] z-90 xl:border xl:border-gris-primario/53 xl:flex xl:gap-8 xl:p-1 xl:rounded-lg xl:static xl:w-full", menuAbierto ? 'translate-x-0' : 'translate-x-full xl:translate-x-0'].filter(Boolean)}>
                {#each rutas as ruta}
                    <li><a class={['inline-block px-4 py-2 rounded-lg text-red-500/71 transition-colors hover:bg-red-500 hover:text-white', rutaActual === ruta.enlace && 'bg-red-500 text-white'].filter(Boolean)} href={ruta.enlace} onclick={() => {
                        menuAbierto = false;
                    }}>{ruta.texto}</a></li>
                {/each}
            </ul>            
        </nav>

        {#if page.data.usuario && page.data.usuario.correo_electronico}
            <a class="bg-red-500 hidden justify-self-end px-4 py-2 rounded-lg self-center text-white transition-colors hover:bg-red-500/62 xl:inline" href="/app">
                Ir a la aplicación
            </a>
        {:else}
            <a class="bg-red-500 hidden justify-self-end px-4 py-2 rounded-lg self-center text-white transition-colors hover:bg-red-500/62 xl:inline" href="/login">
                Iniciar Sesión
            </a>            
        {/if}
    </div>
</header>