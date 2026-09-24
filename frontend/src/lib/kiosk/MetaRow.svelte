<script lang="ts">
	import { fmtRuntime } from './time';
	import type { KioskFilmish } from './types';

	interface Props {
		film: KioskFilmish;
	}
	let { film }: Props = $props();

	const bits = $derived(
		[
			film.cert ? { cert: true, text: film.cert } : null,
			film.year ? { cert: false, text: String(film.year) } : null,
			film.runtime ? { cert: false, text: fmtRuntime(film.runtime) } : null
		].filter((b) => b !== null)
	);
</script>

{#if bits.length}
	<div class="meta-row">
		{#each bits as bit, i (bit.text)}
			{#if i}<i class="dot"></i>{/if}
			{#if bit.cert}<span class="cert">{bit.text}</span>{:else}<span>{bit.text}</span>{/if}
		{/each}
	</div>
{/if}
