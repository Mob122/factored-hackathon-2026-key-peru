<script lang="ts">
    import favicon from '$lib/assets/key-peru.svg';

	import BarraLateral from '$lib/components/app/BarraLateral.svelte';
	import BarraSuperior from '$lib/components/app/BarraSuperior.svelte';

    import type { LayoutProps } from './$types';
	import { RUTAS, RUTAS_AGENTE, RUTAS_SIN_CLIENTE } from '$lib/data/rutas';
	import { page } from '$app/state';

    let { data, children }: LayoutProps = $props();

    let abrirBarraLateral = $state(false);

    // Cada rol ve su menú (contrato chat_api.md, sección 2).
    const rutas = $derived(
        data.usuario?.rol === 'agente' ? RUTAS_AGENTE : data.usuario?.rol === 'cliente' && data.usuario.customer_id ? RUTAS : RUTAS_SIN_CLIENTE
    );
</script>

<svelte:head><link rel="icon" href={favicon} /></svelte:head>

<div id="app" class="bg-red-50 font-roboto text-gris-secundario/62 ">
    <div class={["grid md:grid-cols-[300px_1fr]", page.url.pathname.startsWith('/app/consultas') ? 'h-screen' : 'min-h-screen']}>
        <BarraLateral bind:abrir={abrirBarraLateral} {rutas} />

        <main class="col-start-2 flex flex-col min-h-0 px-4 py-3">
            <BarraSuperior bind:abrir={abrirBarraLateral} />

            <div class="flex flex-col min-h-0 mt-4 flex-1">
                {@render children()}
            </div>
        </main>
    </div>
</div>
