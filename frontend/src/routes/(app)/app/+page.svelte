<script lang="ts">
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();
</script>

<h1>Bienvenido a la aplicación</h1>

<pre>
    {
        JSON.stringify(data.usuario, null, 2)
    }
</pre>