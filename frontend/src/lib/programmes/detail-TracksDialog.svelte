<script lang="ts">
	// GOTCHA: saves through PATCH /blocks/{block}/tracks, NOT PUT /programmes/{id}
	// — the full update round-trips every block and can't express a trailer rule
	// bound to a random movie, so it risks dropping blocks. The focused endpoint
	// also updates the generated playlist's MoviePlayback rows so the choice
	// reaches the player without regenerating the playlist.
	import { api, toApiError } from '$lib/api/client';
	import type { components } from '$lib/api/types.gen';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import { audioTrackLabel, subtitleTrackLabel } from './create-types';
	import { showToast } from '$lib/toast.svelte';

	type MovieDetail = components['schemas']['MovieDetailSchema'];

	interface Props {
		open?: boolean;
		programmeId: number;
		blockId: number | null;
		title: string;
		detail: MovieDetail | null;
		audioIndex: number | null;
		subtitleIndex: number | null;
		onsaved?: () => void;
	}

	let {
		open = $bindable(false),
		programmeId,
		blockId,
		title,
		detail,
		audioIndex,
		subtitleIndex,
		onsaved
	}: Props = $props();

	let draftAudio = $state<number | null>(null);
	let draftSubtitle = $state<number | null>(null);
	let saving = $state(false);

	$effect(() => {
		if (!open) return;
		draftAudio = audioIndex ?? 0;
		draftSubtitle = subtitleIndex;
	});

	const audioTracks = $derived(detail?.audio_tracks ?? []);
	const subtitleTracks = $derived(detail?.subtitle_tracks ?? []);

	async function save() {
		if (saving || blockId === null) return;
		saving = true;
		try {
			const res = await api.PATCH('/api/v2/programmes/{programme_id}/blocks/{block_id}/tracks', {
				params: { path: { programme_id: programmeId, block_id: blockId } },
				body: {
					audio_track_index: draftAudio,
					subtitle_track_index: draftSubtitle
				}
			});
			if (res.error) throw toApiError(res.error, res.response);
			showToast('Track selection saved', 'success');
			open = false;
			onsaved?.();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not save the track selection', 'error');
		} finally {
			saving = false;
		}
	}

	const radioRow =
		'flex cursor-pointer items-start gap-2 rounded-sm -mx-2 px-2 py-1.5 text-sm hover:bg-surface-2';
	const legend = 'mb-1 w-full border-b border-border pb-1 text-sm font-semibold';
</script>

<Dialog bind:open title="Tracks - {title}">
	<div class="grid gap-4 sm:grid-cols-2">
		<fieldset class="min-w-0">
			<legend class={legend}>Audio</legend>
			{#if audioTracks.length}
				{#each audioTracks as track, idx (track.id)}
					<label class={radioRow}>
						<input
							type="radio"
							name="cpd-audio"
							class="mt-0.5 accent-accent"
							checked={draftAudio === idx}
							onchange={() => (draftAudio = idx)}
						/>
						<span class="min-w-0">{audioTrackLabel(track, idx)}</span>
					</label>
				{/each}
			{:else}
				<p class="py-1.5 text-sm text-muted">
					No track data - the movie plays with its default audio.
				</p>
			{/if}
		</fieldset>

		<fieldset class="min-w-0">
			<legend class={legend}>Subtitles</legend>
			{#if subtitleTracks.length}
				<label class={radioRow}>
					<input
						type="radio"
						name="cpd-subtitle"
						class="mt-0.5 accent-accent"
						checked={draftSubtitle === null}
						onchange={() => (draftSubtitle = null)}
					/>
					<span>Off</span>
				</label>
				{#each subtitleTracks as track, idx (track.id)}
					<label class={radioRow}>
						<input
							type="radio"
							name="cpd-subtitle"
							class="mt-0.5 accent-accent"
							checked={draftSubtitle === idx}
							onchange={() => (draftSubtitle = idx)}
						/>
						<span class="min-w-0">{subtitleTrackLabel(track, idx)}</span>
					</label>
				{/each}
			{:else}
				<p class="py-1.5 text-sm text-muted">This movie has no subtitle tracks.</p>
			{/if}
		</fieldset>
	</div>
	<p class="mt-3 text-xs text-faint">
		Applies from the next time this programme plays - the playlist is not regenerated.
	</p>

	{#snippet footer()}
		<Button onclick={() => (open = false)}>Cancel</Button>
		<Button variant="primary" disabled={saving} onclick={() => void save()}>
			{saving ? 'Saving…' : 'Save tracks'}
		</Button>
	{/snippet}
</Dialog>
