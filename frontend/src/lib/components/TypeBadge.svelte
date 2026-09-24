<script lang="ts">
	/**
	 * The one item-type badge: a low-opacity tint of the type's family colour
	 * with a matching hairline border (see lib/item-types.ts). Use this
	 * everywhere a type is named in a chip — never hand-roll a tint.
	 */
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
		/**
		 * Badge sits in a COLUMN (a rundown/table rail): every badge takes the
		 * same fixed width with a centred label, so the rail reads as a rail
		 * at any pane width (spec §05 — ragged badge rails are a tell). The
		 * width (4.5rem) is snug around the longest short label (Trailers /
		 * Feature); floating badges (cards, headers) still hug their text.
		 */
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
