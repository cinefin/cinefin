<script lang="ts">
	/**
	 * Status is a LAMP, not a pill (spec §06): one exposure-shaped square —
	 * the mark's own module — beside plain sentence-case words. No border, no
	 * tinted capsule, no round dot. Settled lamps hold steady; only a state
	 * in transition (`pending`) pulses.
	 *
	 * The one loud state is not a lamp — use `Tally.svelte` for On air.
	 */
	import type { Snippet } from 'svelte';

	interface Props {
		/** Channel: blue interactive, red live, green ready; amber warning;
		 *  neutral for idle/off states. */
		colour: 'blue' | 'red' | 'green' | 'amber' | 'neutral';
		/** State in transition — the lamp breathes. */
		pending?: boolean;
		/** Quiet text (muted instead of text). */
		quiet?: boolean;
		class?: string;
		children: Snippet;
	}

	let { colour, pending = false, quiet = false, class: cls = '', children }: Props = $props();

	const LAMP: Record<string, string> = {
		blue: 'bg-accent',
		red: 'bg-danger',
		green: 'bg-success',
		amber: 'bg-warning',
		neutral: 'bg-faint'
	};
</script>

<span
	class="inline-flex items-center gap-2 text-xs font-medium {quiet
		? 'text-muted'
		: 'text-text'} {cls}"
>
	<i class="h-2 w-2 flex-none {LAMP[colour]} {pending ? 'lamp-pending' : ''}"></i>
	{@render children()}
</span>
