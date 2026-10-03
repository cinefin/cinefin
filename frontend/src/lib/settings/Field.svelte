<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { SettingsStore } from './form.svelte';

	interface Props {
		label?: string;
		forId?: string;
		hint?: string;
		dirty?: boolean;
		error?: string | null;
		/** A settings-store field: its unsaved mark and save error come from the store. */
		store?: SettingsStore;
		field?: string;
		class?: string;
		children: Snippet;
		hintSnippet?: Snippet;
	}

	let {
		label,
		forId,
		hint,
		store,
		field,
		class: cls = '',
		children,
		hintSnippet,
		...own
	}: Props = $props();

	const dirty = $derived(own.dirty ?? (!!field && !!store?.isDirty(field)));
	const error = $derived(own.error ?? (field ? store?.errorFor(field) : null));
</script>

<div class={cls}>
	{#if label}
		<label class="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted" for={forId}>
			{label}
			{#if dirty}
				<span class="h-1.5 w-1.5 bg-warning" title="Unsaved change" aria-label="Unsaved change"
				></span>
			{/if}
		</label>
	{/if}
	{@render children()}
	{#if error}
		<p class="mt-1.5 text-xs text-danger" role="alert">{error}</p>
	{/if}
	{#if hint}
		<p class="mt-1.5 text-xs leading-relaxed text-faint">{hint}</p>
	{/if}
	{#if hintSnippet}
		<p class="mt-1.5 text-xs leading-relaxed text-faint">{@render hintSnippet()}</p>
	{/if}
</div>
