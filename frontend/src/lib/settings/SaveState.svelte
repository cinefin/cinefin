<script lang="ts">
	// What a self-saving form last did: saving, saved, or why it could not.
	import { Check, TriangleAlert } from '@lucide/svelte';
	import type { AutoSave } from './autosave.svelte';

	interface Props {
		saver: AutoSave;
		/** Shown before the first save. */
		idle?: string;
		class?: string;
	}
	let { saver, idle = '', class: cls = '' }: Props = $props();

	const time = $derived(
		saver.savedAt?.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) ?? ''
	);
</script>

<span class="inline-flex items-center gap-1.5 text-xs {cls}" aria-live="polite">
	{#if saver.status === 'saving'}
		<span class="text-muted">Saving…</span>
	{:else if saver.status === 'saved'}
		<Check size={13} class="text-success" /><span class="text-muted">Saved {time}</span>
	{:else if saver.status === 'error'}
		<TriangleAlert size={13} class="text-danger" />
		<span class="text-danger" title={saver.error ?? undefined}>Couldn't save</span>
	{:else if idle}
		<span class="text-faint">{idle}</span>
	{/if}
</span>
