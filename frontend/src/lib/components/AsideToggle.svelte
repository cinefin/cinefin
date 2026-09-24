<script lang="ts">
	/** Collapse/expand control for a detail page's left column. Lives in the tab strip (not on the
	 *  column, which is what disappears); lg+ only, since two columns only exist there. */
	import { PanelLeftClose, PanelLeftOpen } from '@lucide/svelte';

	interface Props {
		collapsed: boolean;
		/** What the column holds, lower case — "the bill", "the template details". */
		label: string;
		ontoggle: () => void;
	}

	let { collapsed, label, ontoggle }: Props = $props();
</script>

<button
	type="button"
	class="my-1.5 hidden shrink-0 items-center rounded-sm border border-transparent p-1.5 text-faint
		transition-colors hover:border-border-strong hover:text-text lg:inline-flex"
	aria-pressed={collapsed}
	title={collapsed ? `Show ${label}` : `Hide ${label} - give the rundown the full width`}
	aria-label={collapsed ? `Show ${label}` : `Hide ${label}`}
	onclick={ontoggle}
>
	{#if collapsed}
		<PanelLeftOpen size={15} aria-hidden="true" />
	{:else}
		<PanelLeftClose size={15} aria-hidden="true" />
	{/if}
</button>
