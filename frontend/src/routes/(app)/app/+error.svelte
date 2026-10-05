<script lang="ts">
	import { page } from '$app/state';
</script>

<section class="flex flex-col items-center justify-center px-6 py-16 text-center">
    <span class="bg-red-50 font-semibold mb-3 px-4 py-1.5 rounded-full text-red-600 text-sm">Error {page.status}</span>
    <h1 class="font-bold text-3xl">No pudimos cargar esta página</h1>
    <p class="max-w-md mt-3">{page.error?.message ?? 'Ocurrió un error inesperado.'}</p>
    <a href="/app" class="mt-6">Volver al inicio</a>
</section>
