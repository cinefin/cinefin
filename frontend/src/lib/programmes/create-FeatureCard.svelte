<script lang="ts">
	import { ChevronDown, ChevronUp, Dices, Film, Sliders, X } from '@lucide/svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import { itemTypeDisplay } from '$lib/item-types';
	import { formatRuntime } from '$lib/format';
	import {
		audioTrackLabel,
		hasSubtitleChoice,
		itemTitle,
		slotFilterText,
		subtitleTrackLabel,
		type SelectedItem
	} from '$lib/programmes/create-types';

	interface Props {
		item: SelectedItem;
		position: number;
		count: number;
		onswap: () => void;
		onfilters: () => void;
		onremove: () => void;
		onmove: (direction: number) => void;
		onaudio: (index: number) => void;
		onsubtitle: (index: number | null) => void;
	}

	let { item, position, count, onswap, onfilters, onremove, onmove, onaudio, onsubtitle }: Props =
		$props();

	const type = $derived(itemTypeDisplay(item.kind === 'random' ? 'random_movie' : 'feature'));
	const facts = $derived.by(() => {
		if (item.kind !== 'movie') return slotFilterText(item);
		return [
			item.year ? String(item.year) : null,
			item.certification,
			item.runtime ? formatRuntime(item.runtime) : null,
			item.resolution
		]
			.filter(Boolean)
			.join(' · ');
	});

	const audioChoice = $derived(item.kind === 'movie' && item.audio_tracks.length > 1);
	const subtitleChoice = $derived(item.kind === 'movie' && hasSubtitleChoice(item));

	const iconButton =
		'rounded-sm p-1 text-faint transition-colors hover:bg-surface-3 hover:text-text ' +
		'disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-faint';
	const trackLabel = 'self-center text-xs text-muted';
	const trackSelect = 'h-8 w-full min-w-0 text-xs';
</script>

<article class="flex gap-3 border border-border bg-surface-1 {type.classes.edge}">
	<div class="w-36 shrink-0 self-stretch border-r border-border bg-surface-2">
		<div class="aspect-[2/3] w-full overflow-hidden">
			{#if item.kind === 'movie' && item.thumbnail_url}
				<img
					src={item.thumbnail_url}
					alt="{item.title} poster"
					class="h-full w-full object-cover"
				/>
			{:else}
				<div class="flex h-full items-center justify-center {type.classes.icon}">
					{#if item.kind === 'random'}<Dices size={32} />{:else}<Film size={32} />{/if}
				</div>
			{/if}
		</div>
	</div>

	<div class="flex min-w-0 flex-1 flex-col gap-2 py-2.5 pr-2.5">
		<div class="flex items-center gap-2">
			<span class="font-mono text-xs text-faint">{String(position).padStart(2, '0')}</span>
			<TypeBadge type={item.kind === 'random' ? 'random_movie' : 'feature'} short icon />
			<div class="ml-auto flex shrink-0 items-center gap-1">
				{#if count > 1}
					<button
						type="button"
						class={iconButton}
						disabled={position === 1}
						title="Move earlier in the running order"
						onclick={() => onmove(-1)}
					>
						<ChevronUp size={14} />
					</button>
					<button
						type="button"
						class={iconButton}
						disabled={position === count}
						title="Move later in the running order"
						onclick={() => onmove(1)}
					>
						<ChevronDown size={14} />
					</button>
				{/if}
				<button
					type="button"
					class="rounded-sm p-1 text-faint transition-colors hover:bg-surface-3 hover:text-danger"
					title={item.kind === 'random' ? 'Remove this random movie' : 'Remove this movie'}
					onclick={onremove}
				>
					<X size={14} />
				</button>
			</div>
		</div>

		<div class="min-w-0">
			<h3 class="truncate text-sm font-semibold" title={item.kind === 'movie' ? item.title : ''}>
				{itemTitle(item)}
			</h3>
			<p class="flex min-w-0 items-center gap-1.5 text-xs text-muted">
				<span class="truncate">{facts}</span>
				{#if item.kind === 'movie' && !item.runtime}
					<Badge variant="outline">No runtime</Badge>
				{/if}
			</p>
		</div>

		{#if item.kind === 'movie'}
			<div class="grid max-w-[22rem] grid-cols-[4.5rem_minmax(0,1fr)] items-center gap-x-2 gap-y-2">
				<span class={trackLabel}>Audio</span>
				{#if audioChoice}
					<Select
						value={String(item.audio_track_index)}
						class={trackSelect}
						onchange={(e) => onaudio(parseInt((e.currentTarget as HTMLSelectElement).value, 10))}
					>
						{#each item.audio_tracks as track, idx (track.id)}
							<option value={String(idx)}>{audioTrackLabel(track, idx)}</option>
						{/each}
					</Select>
				{:else}
					<Select value="0" disabled class={trackSelect}>
						<option value="0">
							{item.audio_tracks.length
								? audioTrackLabel(item.audio_tracks[0], 0)
								: 'Default audio'}
						</option>
					</Select>
				{/if}

				<span class={trackLabel}>Subtitles</span>
				{#if subtitleChoice}
					<Select
						value={item.subtitle_track_index === null ? '' : String(item.subtitle_track_index)}
						class={trackSelect}
						onchange={(e) => {
							const v = (e.currentTarget as HTMLSelectElement).value;
							onsubtitle(v === '' ? null : parseInt(v, 10));
						}}
					>
						<option value="">Off</option>
						{#each item.subtitle_tracks as track, idx (track.id)}
							<option value={String(idx)}>{subtitleTrackLabel(track, idx)}</option>
						{/each}
					</Select>
				{:else}
					<Select value="" disabled class={trackSelect}>
						<option value="">None</option>
					</Select>
				{/if}
			</div>

			<div class="mt-auto flex flex-wrap items-center gap-2">
				<Button size="sm" title="Choose a different movie for this feature" onclick={onswap}>
					Change movie
				</Button>
				<Button size="sm" title="Use a random movie for this feature instead" onclick={onfilters}>
					<Dices size={12} /> Random
				</Button>
			</div>
		{:else}
			<p class="text-xs text-faint">Chosen when the playlist is generated.</p>

			<div class="mt-auto flex flex-wrap items-center gap-2">
				<Button size="sm" title="Edit this random movie’s filters" onclick={onfilters}>
					<Sliders size={12} /> Filters…
				</Button>
				<Button size="sm" title="Choose a specific movie for this feature" onclick={onswap}>
					Choose a movie
				</Button>
			</div>
		{/if}
	</div>
</article>
