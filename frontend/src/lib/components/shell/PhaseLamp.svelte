<script lang="ts">
	// A playout lamp from `$lib/playout/phase`: on air is the solid red tally, else a status lamp.
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Tally from '$lib/components/Tally.svelte';
	import type { Lamp } from '$lib/playout/phase';

	let { lamp }: { lamp: Lamp } = $props();
</script>

{#if lamp.tally}
	<Tally label={lamp.label} />
{:else}
	<StatusLamp colour={lamp.colour} pending={lamp.pending} quiet={lamp.quiet}
		>{lamp.label}</StatusLamp
	>
{/if}
