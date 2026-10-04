<script lang="ts">
    import type { LayoutProps } from './$types';

    let { data, children }: LayoutProps = $props();
</script>

<section class="overflow-hidden relative">
    <div class="contenedor pt-17">   
        {@render children()}
    </div>
</section>