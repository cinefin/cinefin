<script lang="ts">
	/** The one item-type badge (tint from lib/item-types.ts) — never hand-roll a tint. */
	import Badge from '$lib/components/ui/Badge.svelte';
	import { itemTypeDisplay } from '$lib/item-types';

	interface Props {
		type: string | null | undefined;
		/** Compact operator wording ("Feature", "Trailers", "Hold", "Cert"). */
		short?: boolean;
		/** Draw the type icon inside the badge too. */
		icon?: boolean;
		/** Override the label (e.g. "Cue" for an instant command block). */
		label?: string;
		/** In a column (a rundown rail): one fixed width, centred label (spec §05). */
		col?: boolean;
		class?: string;
	}

	let { type, short = false, icon = false, label, col = false, class: cls = '' }: Props = $props();

	const meta = $derived(itemTypeDisplay(type));
	const text = $derived(label ?? (short ? meta.short : meta.label));
	const Icon = $derived(meta.icon);
</script>

<Badge
	variant="type"
	class="{meta.classes.badge} {col ? 'w-[4.5rem] justify-center !px-1' : ''} {cls}"
>
	{#if icon}<Icon size={11} aria-hidden="true" />{/if}
	{text}
</Badge>
