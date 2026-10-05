<script lang="ts">
	import { LineChart, defaultChartPadding } from 'layerchart';
	import { curveCatmullRom } from 'd3-shape';

	let { classLinea, datos }: { classLinea?: string; datos: { date: Date; valor: number }[] } = $props();
</script>

<LineChart
	data={datos}
	x="date"
	y="valor"
    grid={ false }
	props={{ spline: { curve: curveCatmullRom, class: classLinea }, }}
	padding={defaultChartPadding({ right: 10 })}
	height={170}
/>
