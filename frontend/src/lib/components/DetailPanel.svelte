<script lang="ts">
	/** The detail drawer for one library item (trailer, media clip): ui/SidePanel plus the
	 *  loading/error states those views share. Type-specific content goes in `children`, its
	 *  actions in `actions` (pinned at the foot); mount only while an item is open. */
	import type { Snippet } from 'svelte';
	import SidePanel from '$lib/components/ui/SidePanel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';

	interface Props {
		/** Accessible name for the drawer — the item's title once known. */
		label: string;
		/** Ids of the items the host is listing — powers prev/next. */
		ids?: number[];
		currentId?: number | null;
		loading?: boolean;
		/** A short error string to show in place of the body. */
		error?: string | null;
		onclose: () => void;
		onstep?: (id: number) => void;
		children: Snippet;
		actions?: Snippet;
	}

	let {
		label,
		ids = [],
		currentId = null,
		loading = false,
		error = null,
		onclose,
		onstep,
		children,
		actions
	}: Props = $props();
</script>

<SidePanel
	{label}
	{ids}
	{currentId}
	{onclose}
	{onstep}
	footer={actions && !loading && !error ? actions : undefined}
>
	{#if loading}
		<Spinner label="Loading…" />
	{:else if error}
		<p class="text-sm text-danger">{error}</p>
	{:else}
		{@render children()}
	{/if}
</SidePanel>
