<script lang="ts">
	import { X } from '@lucide/svelte';

	/**
	 * Tag chips + entry field (port of the legacy media page's TagInput).
	 * Enter or comma commits the typed tag; Backspace on an empty field pops
	 * the last chip. Bind `tags` for the current list. `suggestions` offers
	 * existing tag names as native datalist autocomplete (already-added tags
	 * are filtered out).
	 */
	interface Props {
		tags?: string[];
		placeholder?: string;
		id?: string;
		suggestions?: string[];
	}

	let { tags = $bindable([]), placeholder = 'Add a tag…', id, suggestions = [] }: Props = $props();

	let value = $state('');

	const uid = $props.id();
	const available = $derived(suggestions.filter((s) => !tags.includes(s)));
	const listId = $derived(available.length ? `${uid}-tag-options` : undefined);

	function add(raw: string) {
		const v = raw.trim().replace(/,+$/, '').trim();
		if (v && !tags.includes(v)) tags.push(v);
	}

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' || e.key === ',') {
			e.preventDefault();
			add(value);
			value = '';
		} else if (e.key === 'Backspace' && !value && tags.length) {
			tags.pop();
		}
	}

	/** Commit whatever is typed (e.g. before a form submit reads `tags`). */
	export function commit() {
		add(value);
		value = '';
	}
</script>

<div
	class="flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-border-strong bg-surface-2 px-2 py-1.5 focus-within:border-accent-dim"
>
	{#each tags as tag, i (tag)}
		<span
			class="inline-flex items-center gap-1 rounded-sm bg-surface-3 px-1.5 py-0.5 text-xs text-text"
		>
			{tag}
			<button
				type="button"
				class="text-muted hover:text-danger"
				aria-label="Remove tag {tag}"
				onclick={() => tags.splice(i, 1)}
			>
				<X size={12} />
			</button>
		</span>
	{/each}
	<input
		{id}
		type="text"
		{placeholder}
		list={listId}
		bind:value
		{onkeydown}
		onchange={() => commit()}
		onblur={() => commit()}
		class="h-6 min-w-24 flex-1 bg-transparent text-sm text-text outline-none placeholder:text-faint"
	/>
	{#if listId}
		<!-- change (not just blur) commits, so picking a suggestion with the
		     mouse turns into a chip immediately. -->
		<datalist id={listId}>
			{#each available as s (s)}
				<option value={s}></option>
			{/each}
		</datalist>
	{/if}
</div>
