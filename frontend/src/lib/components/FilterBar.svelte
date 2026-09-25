<script lang="ts">
	import type { Snippet } from 'svelte';
	import {
		Check,
		ChevronDown,
		FilterX,
		LayoutGrid,
		List,
		SlidersHorizontal,
		X
	} from '@lucide/svelte';
	import {
		anyFilterActive,
		isMulti,
		isToggle,
		type FilterControl,
		type MultiSelectFilter,
		type SelectFilter,
		type SortSpec,
		type ToggleFilter
	} from '$lib/filters';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';

	interface SearchSpec {
		value: string;
		placeholder: string;
		onchange: (value: string) => void;
		debounce?: number;
	}

	interface Props {
		search?: SearchSpec;
		filters?: FilterControl[];
		sort?: SortSpec;
		/** Result count readout, e.g. "142 movies (filtered)". */
		count?: string;
		/** Grid/list toggle — bind it; rendered only when viewKey is set. */
		view?: 'grid' | 'list';
		/** localStorage key the view choice persists under. */
		viewKey?: string;
		/** Clears every filter (and restores the default sort) — page-owned. */
		onreset?: () => void;
		/** Collapse filter controls behind one "Filters" button. Defaults on past three filters
		 *  (where the bar starts wrapping); what is active still reads out as chips beneath. */
		filterPanel?: boolean;
		/** Page-local extras rendered inline after the declared controls. */
		children?: Snippet;
		/** Page-local extras for the right-hand cluster, before the view toggle (e.g. a zoom control). */
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
		filterPanel,
		children,
		viewExtras
	}: Props = $props();

	const panelled = $derived(filterPanel ?? filters.length > 3);

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

	const selectChips = $derived(
		filters.filter((f): f is SelectFilter => !isToggle(f) && !isMulti(f) && f.value !== '')
	);
	const toggleChips = $derived(filters.filter((f): f is ToggleFilter => isToggle(f) && f.value));
	const multiFilters = $derived(filters.filter((f): f is MultiSelectFilter => isMulti(f)));
	const multiChips = $derived(
		multiFilters.flatMap((f) => f.values.map((v) => ({ filter: f, value: v })))
	);
	const filtersActive = $derived(anyFilterActive(filters) || Boolean(search?.value));
	const resetVisible = $derived(filtersActive || (sort ? sort.value !== sort.default : false));

	function chipValueLabel(f: SelectFilter): string {
		return f.options.find((o) => o.value === f.value)?.label ?? f.value;
	}

	function multiOptionLabel(f: MultiSelectFilter, value: string): string {
		return f.options.find((o) => o.value === value)?.label ?? value;
	}

	function toggleMultiValue(f: MultiSelectFilter, value: string, on: boolean) {
		const next = on ? [...f.values, value] : f.values.filter((v) => v !== value);
		f.onchange(next);
	}

	function optionLabel(o: { label: string; count?: number }): string {
		return o.count != null ? `${o.label} (${o.count})` : o.label;
	}

	const activeCount = $derived(selectChips.length + toggleChips.length + multiChips.length);

	// Each multi filter has its own dropdown (independent of the Filters panel).
	let openMultiId = $state<string | null>(null);
	let multiRoot = $state<HTMLDivElement>();

	$effect(() => {
		if (openMultiId === null) return;
		const onClick = (e: MouseEvent) => {
			if (multiRoot && !multiRoot.contains(e.target as Node)) openMultiId = null;
		};
		const onKeydown = (e: KeyboardEvent) => {
			if (e.key === 'Escape') openMultiId = null;
		};
		window.addEventListener('click', onClick);
		window.addEventListener('keydown', onKeydown);
		return () => {
			window.removeEventListener('click', onClick);
			window.removeEventListener('keydown', onKeydown);
		};
	});

	let panelOpen = $state(false);
	let panelRoot = $state<HTMLDivElement>();

	$effect(() => {
		if (!panelOpen) return;
		const onClick = (e: MouseEvent) => {
			if (panelRoot && !panelRoot.contains(e.target as Node)) panelOpen = false;
		};
		const onKeydown = (e: KeyboardEvent) => {
			if (e.key === 'Escape') panelOpen = false;
		};
		window.addEventListener('click', onClick);
		window.addEventListener('keydown', onKeydown);
		return () => {
			window.removeEventListener('click', onClick);
			window.removeEventListener('keydown', onKeydown);
		};
	});

	const toggleClasses = (on: boolean) =>
		`h-9 border bg-surface-2 px-2.5 text-sm whitespace-nowrap transition-colors ` +
		`active:brightness-90 ${
			on
				? 'border-accent text-accent'
				: 'border-border-strong text-muted hover:border-faint hover:text-text'
		}`;
</script>

{#snippet multiControl(f: MultiSelectFilter)}
	<div class="relative">
		<button
			type="button"
			aria-expanded={openMultiId === f.id}
			aria-haspopup="dialog"
			class="flex h-9 items-center gap-1.5 border bg-surface-2 px-2.5 text-sm transition-colors
			{f.values.length
				? 'border-accent text-accent'
				: 'border-border-strong text-muted hover:border-faint hover:text-text'}"
			onclick={(e) => {
				e.stopPropagation();
				openMultiId = openMultiId === f.id ? null : f.id;
			}}
		>
			{f.label}
			{#if f.values.length}
				<span class="font-mono text-xs">{f.values.length}</span>
			{/if}
			<ChevronDown
				size={12}
				class="transition-transform {openMultiId === f.id ? 'rotate-180' : ''}"
			/>
		</button>

		{#if openMultiId === f.id}
			<div
				bind:this={multiRoot}
				role="dialog"
				aria-label={f.label}
				class="absolute left-0 z-30 mt-1 flex max-h-72 w-56 flex-col gap-0.5 overflow-y-auto
				border border-border-strong bg-surface-1 p-1.5"
			>
				{#if f.options.length}
					<p class="px-1.5 pb-1 text-[0.65rem] text-faint">Match all selected</p>
					{#each f.options as o (o.value)}
						{@const on = f.values.includes(o.value)}
						<button
							type="button"
							role="menuitemcheckbox"
							aria-checked={on}
							class="flex items-center gap-2 px-1.5 py-1 text-left text-sm transition-colors
							{on ? 'text-accent' : 'text-muted hover:text-text'}"
							onclick={() => toggleMultiValue(f, o.value, !on)}
						>
							<span
								class="flex h-3.5 w-3.5 shrink-0 items-center justify-center border
								{on ? 'border-accent bg-accent/15' : 'border-border-strong'}"
							>
								{#if on}<Check size={11} />{/if}
							</span>
							<span class="min-w-0 flex-1 truncate">{optionLabel(o)}</span>
						</button>
					{/each}
				{:else}
					<p class="px-1.5 py-1 text-sm text-faint">No options</p>
				{/if}
			</div>
		{/if}
	</div>
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
				<div class="relative" bind:this={panelRoot}>
					<button
						type="button"
						aria-expanded={panelOpen}
						aria-haspopup="dialog"
						class="flex h-9 items-center gap-1.5 border bg-surface-2 px-2.5 text-sm
						transition-colors {activeCount
							? 'border-accent text-accent'
							: 'border-border-strong text-muted hover:border-faint hover:text-text'}"
						onclick={() => (panelOpen = !panelOpen)}
					>
						<SlidersHorizontal size={14} />
						Filters
						{#if activeCount}
							<span class="font-mono text-xs">{activeCount}</span>
						{/if}
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
									<button
										type="button"
										aria-pressed={f.value}
										class="{toggleClasses(f.value)} w-full"
										onclick={() => f.onchange(!f.value)}
									>
										{f.label}
									</button>
								{:else if isMulti(f)}
									<label class="flex flex-col gap-1 text-xs text-muted">
										{f.label}
										{@render multiControl(f)}
									</label>
								{:else if !f.chipOnly}
									<label class="flex flex-col gap-1 text-xs text-muted">
										{f.label}
										<Select
											class="w-full"
											value={f.value}
											onchange={(e) => f.onchange((e.currentTarget as HTMLSelectElement).value)}
										>
											<option value="">{f.allLabel}</option>
											{#each f.options as o (o.value)}
												<option value={o.value}>{optionLabel(o)}</option>
											{/each}
										</Select>
									</label>
								{/if}
							{/each}
						</div>
					{/if}
				</div>
			{:else}
				{#each filters as f (f.id)}
					{#if isToggle(f)}
						<button
							type="button"
							aria-pressed={f.value}
							title={f.label}
							class={toggleClasses(f.value)}
							onclick={() => f.onchange(!f.value)}
						>
							{f.label}
						</button>
					{:else if isMulti(f)}
						{@render multiControl(f)}
					{:else if !f.chipOnly}
						<Select
							value={f.value}
							onchange={(e) => f.onchange((e.currentTarget as HTMLSelectElement).value)}
						>
							<option value="">{f.allLabel}</option>
							{#each f.options as o (o.value)}
								<option value={o.value}>{optionLabel(o)}</option>
							{/each}
						</Select>
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
			{#if count}
				<span class="font-mono text-xs whitespace-nowrap text-muted">{count}</span>
			{/if}

			{#if viewExtras}{@render viewExtras()}{/if}

			{#if viewKey}
				<div class="flex border border-border-strong" role="group" aria-label="View">
					<button
						type="button"
						title="Grid view"
						aria-label="Grid view"
						aria-pressed={view === 'grid'}
						onclick={() => (view = 'grid')}
						class="flex h-9 w-9 items-center justify-center {view === 'grid'
							? 'bg-surface-3 text-accent'
							: 'bg-surface-2 text-muted hover:text-text'}"
					>
						<LayoutGrid size={15} />
					</button>
					<button
						type="button"
						title="List view"
						aria-label="List view"
						aria-pressed={view === 'list'}
						onclick={() => (view = 'list')}
						class="flex h-9 w-9 items-center justify-center border-l border-border-strong
							{view === 'list' ? 'bg-surface-3 text-accent' : 'bg-surface-2 text-muted hover:text-text'}"
					>
						<List size={15} />
					</button>
				</div>
			{/if}
		</div>
	</div>

	{#if selectChips.length || toggleChips.length || multiChips.length}
		<div class="flex flex-wrap items-center gap-1.5 border-t border-border px-2 py-1.5">
			{#each multiChips as { filter, value } (filter.id + ':' + value)}
				<button
					type="button"
					title="Clear {filter.label} filter"
					class="inline-flex items-center gap-1 border border-border-strong bg-surface-2 px-1.5
						py-px font-mono text-[0.65rem] text-muted
						hover:border-danger/60 hover:text-danger"
					onclick={() => toggleMultiValue(filter, value, false)}
				>
					{filter.label}: {multiOptionLabel(filter, value)}
					<X size={10} />
				</button>
			{/each}
			{#each selectChips as f (f.id)}
				<button
					type="button"
					title="Clear {f.label} filter"
					class="inline-flex items-center gap-1 border border-border-strong bg-surface-2 px-1.5
						py-px font-mono text-[0.65rem] text-muted
						hover:border-danger/60 hover:text-danger"
					onclick={() => f.onchange('')}
				>
					{f.label}: {chipValueLabel(f)}
					<X size={10} />
				</button>
			{/each}
			{#each toggleChips as f (f.id)}
				<button
					type="button"
					title="Clear {f.label} filter"
					class="inline-flex items-center gap-1 border border-border-strong bg-surface-2 px-1.5
						py-px font-mono text-[0.65rem] text-muted
						hover:border-danger/60 hover:text-danger"
					onclick={() => f.onchange(false)}
				>
					{f.label}
					<X size={10} />
				</button>
			{/each}
		</div>
	{/if}
</div>
