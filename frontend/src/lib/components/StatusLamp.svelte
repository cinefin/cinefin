<script lang="ts">
	/** Status is a lamp, not a pill (spec §06); only `pending` pulses. On air is `Tally`. */
	import type { Snippet } from 'svelte';

	interface Props {
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
