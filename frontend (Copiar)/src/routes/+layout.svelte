<script lang="ts">
    import type { LayoutProps } from './$types';
    	import './layout.css';


    let { data, children }: LayoutProps = $props();
</script>

<svelte:head>
    <title>Key Perú</title>
    <meta name="description" content="Key Perú es una aplicación de atención bancaria segura y confiable que permite consultar información de cuentas, movientos y revisar el estado de tarjetas o bloqueos de manera rápida y sencilla.">
    <meta name="keywords" content="Key Perú, atención bancaria, consulta de cuentas, movimientos bancarios, estado de tarjetas, bloqueos de tarjetas, aplicación bancaria segura, información financiera, servicios bancarios en línea">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="icon" href="/favicon.ico">
</svelte:head>

{@render children()}