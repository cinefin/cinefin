<script lang="ts">
	import { Captions, Dices, Film, Headphones, Sliders, TriangleAlert } from '@lucide/svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import type { components } from '$lib/api/types.gen';
	import { itemTypeDisplay } from '$lib/item-types';
	import { audioTrackLabel, codecLabel, subtitleTrackLabel } from './create-types';
	import type { ProgrammeItem } from './types';
	import { formatDuration, formatFileSize } from './helpers';

	type MovieDetail = components['schemas']['MovieDetailSchema'];

	interface Props {
		item: ProgrammeItem;
		detail?: MovieDetail | null;
		genreNames?: string[];
		onopentracks?: () => void;
		class?: string;
	}

	let { item, detail = null, genreNames = [], onopentracks, class: cls = '' }: Props = $props();

	const d = $derived(item.details ?? {});
	const type = $derived(itemTypeDisplay(item.type));

	let synopsisOpen = $state(false);
	// Whether the clamp is hiding something — measured, not guessed from length.
	let synopsisEl = $state<HTMLParagraphElement>();
	let synopsisClamped = $state(false);
	$effect(() => {
		const el = synopsisEl;
		if (!el) return;
		const measure = () => {
			if (!synopsisOpen) synopsisClamped = el.scrollHeight > el.clientHeight + 1;
		};
		measure();
		const observer = new ResizeObserver(measure);
		observer.observe(el);
		return () => observer.disconnect();
	});

	const audioIndex = $derived(d.audio_track ?? null);
	const subtitleIndex = $derived(d.subtitle_track ?? null);

	const audioLabel = $derived.by(() => {
		if (detail) {
			const idx = audioIndex ?? 0;
			const track = detail.audio_tracks?.[idx];
			if (track) return audioTrackLabel(track, idx);
			return detail.audio_tracks?.length ? `Track ${idx + 1}` : 'Default audio';
		}
		// Fallback: the labels the block payload resolved server-side.
		const t = d.selected_audio_track;
		if (t) {
			const bits = [String(t.language || '').toUpperCase()];
			if (t.codec) bits.push(String(t.codec).toUpperCase());
			if (t.channels) bits.push(`${t.channels}ch`);
			return bits.filter(Boolean).join(' · ');
		}
		return audioIndex !== null ? `Track ${audioIndex + 1}` : 'Default audio';
	});

	const subtitleLabel = $derived.by(() => {
		if (detail) {
			if (subtitleIndex === null) return detail.subtitle_tracks?.length ? 'Off' : 'None';
			const track = detail.subtitle_tracks?.[subtitleIndex];
			return track ? subtitleTrackLabel(track, subtitleIndex) : `Track ${subtitleIndex + 1}`;
		}
		const t = d.selected_subtitle_track;
		if (t) {
			const bits = [String(t.language || '').toUpperCase()];
			if (t.forced) bits.push('forced');
			if (t.sdh) bits.push('SDH');
			return bits.filter(Boolean).join(' ');
		}
		return subtitleIndex !== null ? `Track ${subtitleIndex + 1}` : 'Off';
	});

	const hasSubs = $derived(subtitleIndex !== null);
	const canChoose = $derived(
		!!detail &&
			((detail.audio_tracks?.length ?? 0) > 1 || (detail.subtitle_tracks?.length ?? 0) > 0)
	);

	const resolution = $derived(detail?.resolution || d.resolution || null);
	const fileSize = $derived(detail?.file_size ?? d.file_size ?? null);
	const filePath = $derived(detail?.file_path || d.file_path || null);
	const director = $derived(detail?.director || d.director || null);
	const synopsis = $derived(detail?.description || d.synopsis || null);
	const audioCodec = $derived.by(() => {
		const track = detail?.audio_tracks?.[audioIndex ?? 0];
		return track?.codec ? codecLabel(track.codec) : null;
	});
	const qualityBits = $derived([resolution, audioCodec].filter(Boolean) as string[]);
	const factsTitle = $derived(
		[fileSize ? formatFileSize(fileSize) : null, filePath].filter(Boolean).join('\n') || undefined
	);

	const yearRange = $derived.by(() => {
		if (d.year_from && d.year_to) return `${d.year_from}-${d.year_to}`;
		if (d.year_from) return `${d.year_from}+`;
		if (d.year_to) return `≤${d.year_to}`;
		return null;
	});
	const matching = $derived(d.matching_count ?? 0);
	const unfiltered = $derived(!d.genre_names?.length && !d.certification && !yearRange);

	const artCell = 'w-48 shrink-0 self-start sm:w-52';
	const artBox = 'film-grain aspect-[2/3] w-full overflow-hidden bg-surface-2';
	const factsCol = 'flex min-w-0 flex-1 flex-col gap-2 p-3';
</script>

<article class="border border-border bg-surface-1 {type.classes.edge} {cls}">
	{#if item.type === 'random_movie'}
		<div class="flex gap-3">
			<div
				class="{artCell} border-r border-dashed
					{matching === 0 ? 'border-danger/50' : 'border-border-strong'}"
			>
				<div class="{artBox} flex items-center justify-center text-faint">
					<Dices size={44} class={type.classes.icon} />
				</div>
			</div>
			<div class={factsCol}>
				<div>
					<h3 class="text-base leading-tight font-semibold">
						Random movie{(d.count ?? 1) > 1 ? ` ×${d.count}` : ''}
					</h3>
					<p class="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-sm text-muted">
						{#if d.genre_names?.length}<span>{d.genre_names.join(', ')}</span>{/if}
						{#if d.certification}<Badge variant="outline">{d.certification}</Badge>{/if}
						{#if yearRange}<span>{yearRange}</span>{/if}
						{#if unfiltered}<span>Any movie</span>{/if}
					</p>
				</div>
				<p class="text-sm text-muted">Chosen at random when the playlist is generated.</p>
				<p
					class="mt-auto border-t border-border pt-2.5 font-mono text-xs
						{matching === 0 ? 'text-danger' : 'text-muted'}"
				>
					{#if matching === 0}
						<TriangleAlert size={11} class="mr-1 inline" />0 movies match - the playlist will skip
						this slot
					{:else}
						{matching} movies match
					{/if}
				</p>
			</div>
		</div>
	{:else}
		<div class="flex gap-3">
			<div class="{artCell} border-r border-border">
				<div class={artBox}>
					{#if d.thumbnail_url}
						<img
							src={d.thumbnail_url}
							alt="{item.title} poster"
							class="h-full w-full object-cover"
						/>
					{:else}
						<div class="flex h-full items-center justify-center text-faint"><Film size={44} /></div>
					{/if}
				</div>
			</div>

			<div class={factsCol}>
				<div>
					<h3 class="text-base leading-tight font-semibold">{item.title}</h3>
					<p
						class="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-sm text-muted"
						title={factsTitle}
					>
						<span>{detail?.year || d.year || '-'}</span>
						{#if d.certification}
							<span class="text-faint">·</span>
							<Badge variant="outline">{d.certification}</Badge>
						{/if}
						<span class="text-faint">·</span>
						<span class="font-mono">{formatDuration(item.duration_seconds)}</span>
						{#each qualityBits as bit (bit)}
							<span class="text-faint">·</span>
							<span class="font-mono">{bit}</span>
						{/each}
					</p>
				</div>

				{#if director}
					<p class="text-sm" title="Director">{director}</p>
				{/if}

				{#if genreNames.length}
					<p class="text-sm text-muted">{genreNames.join(', ')}</p>
				{/if}

				{#if synopsis}
					<div>
						<p
							bind:this={synopsisEl}
							class="text-sm leading-relaxed text-muted {synopsisOpen ? '' : 'line-clamp-4'}"
						>
							{synopsis}
						</p>
						{#if synopsisClamped}
							<button
								type="button"
								class="mt-0.5 text-xs text-accent hover:underline"
								aria-expanded={synopsisOpen}
								onclick={() => (synopsisOpen = !synopsisOpen)}
							>
								{synopsisOpen ? 'Show less' : 'Show more'}
							</button>
						{/if}
					</div>
				{/if}

				<div
					class="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border
						pt-2.5 text-sm"
				>
					<span class="flex min-w-0 items-center gap-1.5" title="Audio track">
						<Headphones size={13} class="shrink-0 text-faint" />
						<span class="min-w-0 truncate">{audioLabel}</span>
					</span>
					<span
						class="flex min-w-0 items-center gap-1.5 {hasSubs ? '' : 'text-faint'}"
						title="Subtitle track"
					>
						<Captions size={13} class="shrink-0 text-faint" />
						<span class="min-w-0 truncate">
							{hasSubs ? subtitleLabel : `Subtitles ${subtitleLabel.toLowerCase()}`}
						</span>
					</span>
					<Button
						class="ml-auto"
						size="sm"
						disabled={!canChoose}
						title={canChoose
							? 'Choose the audio and subtitle tracks this feature plays with'
							: 'This movie has one audio track and no subtitles'}
						onclick={() => onopentracks?.()}
					>
						<Sliders size={13} /> Tracks…
					</Button>
				</div>
			</div>
		</div>
	{/if}
</article>
