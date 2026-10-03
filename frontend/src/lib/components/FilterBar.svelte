<script lang="ts">
	import type { Snippet } from 'svelte';
	import { ChevronDown, FilterX, LayoutGrid, List, SlidersHorizontal, X } from '@lucide/svelte';
	import {
		anyFilterActive,
		isToggle,
		type FilterControl,
		type SelectFilter,
		type SortSpec,
		type ToggleFilter
	} from '$lib/filters';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import { dismiss } from '$lib/components/dismiss';

	interface Props {
		search?: {
			value: string;
			placeholder: string;
			onchange: (value: string) => void;
			debounce?: number;
		};
		filters?: FilterControl[];
		sort?: SortSpec;
		/** Result count readout, e.g. "142 movies (filtered)". */
		count?: string;
		/** Grid/list toggle — bind it; rendered only when viewKey (its localStorage key) is set. */
		view?: 'grid' | 'list';
		viewKey?: string;
		/** Clears every filter (and restores the default sort) — page-owned. */
		onreset?: () => void;
		/** Page-local extras rendered inline after the declared controls. */
		children?: Snippet;
		/** Extras for the right-hand cluster, before the view toggle (e.g. a zoom control). */
		viewExtras?: Snippet;
	}

	let {
		search,
		filters = [],
		sort,
		count,
		view = $bindable('grid'),
		viewKey,
		onreset,
		children,
		viewExtras
	}: Props = $props();

	// Past three filters the bar starts wrapping, so they collapse behind one "Filters" button.
	const panelled = $derived(filters.length > 3);

	// Search: local text, debounced onchange; external sets flow back without clobbering typing.
	// svelte-ignore state_referenced_locally
	let searchText = $state(search?.value ?? '');
	// svelte-ignore state_referenced_locally
	let emitted = search?.value ?? '';
	let searchTimer: ReturnType<typeof setTimeout> | undefined;

	$effect(() => {
		const v = search?.value ?? '';
		if (v !== emitted) {
			emitted = v;
			searchText = v;
		}
	});

	function onSearchInput() {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => {
			const v = searchText.trim();
			if (v === emitted) return;
			emitted = v;
			search?.onchange(v);
		}, search?.debounce ?? 300);
	}

	$effect(() => () => clearTimeout(searchTimer));

	$effect(() => {
		if (viewKey) localStorage.setItem(viewKey, view);
	});

	const chips = $derived(
		filters.flatMap((f): { f: FilterControl; text: string; clear: () => void }[] =>
			isToggle(f)
				? f.value
					? [{ f, text: f.label, clear: () => f.onchange(false) }]
					: []
				: f.value !== ''
					? [{ f, text: `${f.label}: ${chipValueLabel(f)}`, clear: () => f.onchange('') }]
					: []
		)
	);
	const resetVisible = $derived(
		anyFilterActive(filters) ||
			Boolean(search?.value) ||
			(sort ? sort.value !== sort.default : false)
	);

	function chipValueLabel(f: SelectFilter): string {
		return f.options.find((o) => o.value === f.value)?.label ?? f.value;
	}

	function optionLabel(o: { label: string; count?: number }): string {
		return o.count != null ? `${o.label} (${o.count})` : o.label;
	}

	let panelOpen = $state(false);

	const toggleClasses = (on: boolean) =>
		`h-9 border bg-surface-2 px-2.5 text-sm whitespace-nowrap transition-colors ` +
		`active:brightness-90 ${
			on
				? 'border-accent text-accent'
				: 'border-border-strong text-muted hover:border-faint hover:text-text'
		}`;
</script>

{#snippet toggleControl(f: ToggleFilter, inPanel: boolean)}
	<button
		type="button"
		aria-pressed={f.value}
		title={inPanel ? undefined : f.label}
		class="{toggleClasses(f.value)}{inPanel ? ' w-full' : ''}"
		onclick={() => f.onchange(!f.value)}
	>
		{f.label}
	</button>
{/snippet}

{#snippet selectControl(f: SelectFilter, cls?: string)}
	<Select
		class={cls}
		value={f.value}
		onchange={(e) => f.onchange((e.currentTarget as HTMLSelectElement).value)}
	>
		<option value="">{f.allLabel}</option>
		{#each f.options as o (o.value)}<option value={o.value}>{optionLabel(o)}</option>{/each}
	</Select>
{/snippet}

{#snippet viewButton(v: 'grid' | 'list', label: string, Icon: typeof List, cls = '')}
	<button
		type="button"
		title={label}
		aria-label={label}
		aria-pressed={view === v}
		onclick={() => (view = v)}
		class="flex h-9 w-9 items-center justify-center {cls} {view === v
			? 'bg-surface-3 text-accent'
			: 'bg-surface-2 text-muted hover:text-text'}"
	>
		<Icon size={15} />
	</button>
{/snippet}

<div class="mb-4 border-y border-border bg-surface-1">
	<div class="flex items-start gap-2 px-2 py-2">
		<div class="flex min-w-0 flex-1 flex-wrap items-center gap-2">
			{#if search}
				<Input
					type="search"
					placeholder={search.placeholder}
					bind:value={searchText}
					oninput={onSearchInput}
					class="w-full sm:w-56"
				/>
			{/if}

			{#if panelled}
				<div class="relative" {@attach dismiss(() => (panelOpen = false))}>
					<button
						type="button"
						aria-expanded={panelOpen}
						aria-haspopup="dialog"
						class="flex h-9 items-center gap-1.5 border bg-surface-2 px-2.5 text-sm
						transition-colors {chips.length
							? 'border-accent text-accent'
							: 'border-border-strong text-muted hover:border-faint hover:text-text'}"
						onclick={() => (panelOpen = !panelOpen)}
					>
						<SlidersHorizontal size={14} />
						Filters
						{#if chips.length}<span class="font-mono text-xs">{chips.length}</span>{/if}
						<ChevronDown size={12} class="transition-transform {panelOpen ? 'rotate-180' : ''}" />
					</button>

					{#if panelOpen}
						<div
							role="dialog"
							aria-label="Filters"
							class="absolute left-0 z-30 mt-1 flex w-72 flex-col gap-2.5 border
							border-border-strong bg-surface-1 p-3"
						>
							{#each filters as f (f.id)}
								{#if isToggle(f)}
									{@render toggleControl(f, true)}
								{:else if !f.chipOnly}
									<label class="flex flex-col gap-1 text-xs text-muted">
										{f.label}
										{@render selectControl(f, 'w-full')}
									</label>
								{/if}
							{/each}
						</div>
					{/if}
				</div>
			{:else}
				{#each filters as f (f.id)}
					{#if isToggle(f)}
						{@render toggleControl(f, false)}
					{:else if !f.chipOnly}
						{@render selectControl(f)}
					{/if}
				{/each}
			{/if}

			{#if sort}
				<Select
					value={sort.value}
					onchange={(e) => sort.onchange((e.currentTarget as HTMLSelectElement).value)}
				>
					{#each sort.options as o (o.value)}
						<option value={o.value}>{optionLabel(o)}</option>
					{/each}
				</Select>
			{/if}

			{#if children}{@render children()}{/if}

			{#if resetVisible && onreset}
				<Button variant="ghost" onclick={onreset} title="Clear search, filters and sort">
					<FilterX size={14} /> Reset
				</Button>
			{/if}
		</div>

		<div class="flex shrink-0 items-center gap-2">
			{#if count}<span class="font-mono text-xs whitespace-nowrap text-muted">{count}</span>{/if}

			{#if viewExtras}{@render viewExtras()}{/if}

			{#if viewKey}
				<div class="flex border border-border-strong" role="group" aria-label="View">
					{@render viewButton('grid', 'Grid view', LayoutGrid)}
					{@render viewButton('list', 'List view', List, 'border-l border-border-strong')}
				</div>
			{/if}
		</div>
	</div>

	{#if chips.length}
		<div class="flex flex-wrap items-center gap-1.5 border-t border-border px-2 py-1.5">
			{#each chips as { f, text, clear } (f.id)}
				<button
					type="button"
					title="Clear {f.label} filter"
					class="inline-flex items-center gap-1 border border-border-strong bg-surface-2 px-1.5
						py-px font-mono text-[0.65rem] text-muted
						hover:border-danger/60 hover:text-danger"
					onclick={clear}
				>
					{text}
					<X size={10} />
				</button>
			{/each}
		</div>
	{/if}
</div>
