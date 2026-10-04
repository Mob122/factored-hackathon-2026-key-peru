<script lang="ts">
	import { LineChart, defaultChartPadding } from 'layerchart';
	import { curveCatmullRom } from 'd3-shape';
	import { createDateSeries } from '$lib/utils/data.js';

	let { classLinea }: { classLinea?: string } = $props();

	const data = createDateSeries({ count: 30, min: 50, max: 100, value: 'integer' });
</script>

<LineChart
	{data}	
	x="date"
	y="valor"    
    grid={ false }
	props={{ spline: { curve: curveCatmullRom, class: classLinea }, }}
	padding={defaultChartPadding({ right: 10 })}    
	height={170}
/>