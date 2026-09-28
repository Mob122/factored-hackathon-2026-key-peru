<script lang="ts">
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import BarraNavegacion from '$lib/components/marketing/BarraNavegacion.svelte';

	const RUTAS: { texto: string; enlace: string }[] = [
		{ texto: 'Inicio', enlace: '/' },
		{ texto: 'Nosotros', enlace: '#nosotros' },
		{ texto: 'Testimonios', enlace: '#testimonios' },
		{ texto: 'Q&A', enlace: '#preguntas-frecuentes' }
	];

	let { children } = $props();	
</script>

<svelte:head><link rel="icon" href={favicon} /></svelte:head>

<div id="app" class="font-roboto text-gris-secundario">
	<BarraNavegacion rutas={RUTAS} />
	
	<div>
		{@render children()}
	</div>	
</div>