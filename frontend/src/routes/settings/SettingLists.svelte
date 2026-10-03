<script lang="ts">
	// A section's lists: stacked, then side by side once the page has room for both, the busier
	// one (Players, the library source, the printer) in the wider column.
	import type { Snippet } from 'svelte';

	let { wider = 'first', children }: { wider?: 'first' | 'second'; children: Snippet } = $props();
</script>

<div class="@container">
	<div
		class="grid items-start gap-6 {wider === 'first'
			? '@min-[92rem]:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]'
			: '@min-[92rem]:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]'}"
	>
		{@render children()}
	</div>
</div>
