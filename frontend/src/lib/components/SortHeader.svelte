<script lang="ts">
	/**
	 * A sortable table header cell. Renders a `<th>` with a click-to-sort button
	 * and the active-direction arrow, shared by every list table so they behave
	 * the same. The host owns the `sort` string and applies it (client-side via
	 * `sortRows`, or by refetching for server-sorted lists); this only toggles.
	 */
	import { sortIndicator, toggleSort } from '$lib/filters';

	interface Props {
		/** The current signed sort key, e.g. "year" or "-year". */
		sort: string;
		/** This column's key. */
		col: string;
		label: string;
		/** First click sorts descending (dates, sizes, counts). */
		defaultDesc?: boolean;
		/** Called with the next sort string. */
		onsort: (next: string) => void;
		/** Extra classes on the `<th>` (width, alignment). */
		class?: string;
	}

	let { sort, col, label, defaultDesc = false, onsort, class: cls = '' }: Props = $props();
	const active = $derived(sort === col || sort === `-${col}`);
</script>

<th class="px-3 py-2 {cls}">
	<button
		type="button"
		class="inline-flex items-center gap-1 whitespace-nowrap hover:text-text {active
			? 'text-accent'
			: ''}"
		onclick={() => onsort(toggleSort(sort, col, defaultDesc))}
	>
		{label}<span class="font-mono text-[0.65em]">{sortIndicator(sort, col)}</span>
	</button>
</th>
