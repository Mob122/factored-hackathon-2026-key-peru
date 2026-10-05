<script lang="ts">
	import { PieChart, type ArcLabelPlacement } from 'layerchart';

	let { datos }: { datos: { etiqueta: string; valor: number }[] } = $props();

    let colores = ['oklch(93.6% 0.032 17.717)', 'oklch(88.5% 0.062 18.334)', 'oklch(70.4% 0.191 22.216)', 'oklch(63.7% 0.237 25.331)'];

	let placement: ArcLabelPlacement = $state('callout');
	let offset = $state(-2);
</script>

<PieChart
	data={datos}
	key="etiqueta"
	value="valor"
	cRange={colores}
	innerRadius={-35}
	padding={{ top: 24, bottom: 24, left: 80, right: 89 }}
	labels={{
		placement,
		offset,
		value: 'etiqueta',
		class: 'text-gris-secundario/62 text-xs',
	}}
	height={206}
/>
