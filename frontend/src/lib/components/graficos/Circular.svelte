<script lang="ts">
	import { PieChart, type ArcLabelPlacement } from 'layerchart';

    let longData = [        
        { year: 2019, basket: 1, fruit: 'En atención', value: 2 },
        { year: 2019, basket: 1, fruit: 'Resueltos', value: 3 },
        { year: 2019, basket: 1, fruit: 'Cerrados', value: 4 }
    ]

    let fruitColors = ['oklch(93.6% 0.032 17.717)', 'oklch(88.5% 0.062 18.334)', 'oklch(70.4% 0.191 22.216)', 'oklch(63.7% 0.237 25.331)'];
	
	let placement: ArcLabelPlacement = $state('callout');
	let offset = $state(-2);

	const data = longData.filter((d) => d.year === 2019);
</script>

<PieChart
	{data}
	key="fruit"
	value="value"
	cRange={fruitColors}
	innerRadius={-35}
	padding={{ top: 24, bottom: 24, left: 80, right: 89 }}
	labels={{
		placement,
		offset,
		value: 'fruit',
		class: 'text-gris-secundario/62 text-xs',
	}}
	height={206}
/>