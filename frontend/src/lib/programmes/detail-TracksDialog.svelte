<script lang="ts">
	// Saves through PATCH /blocks/{block}/tracks, not PUT /programmes/{id}: the full update can
	// drop a trailer rule bound to a random movie, and this one also updates the playlist's rows.
	import { api, toApiError } from '$lib/api/client';
	import type { components } from '$lib/api/types.gen';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import TrackRadios from './TrackRadios.svelte';
	import { showToast } from '$lib/toast.svelte';
	import { attempt } from '$lib/settings/form.svelte';

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

	async function save() {
		if (saving || blockId === null) return;
		saving = true;
		const path = { programme_id: programmeId, block_id: blockId };
		await attempt(async () => {
			const res = await api.PATCH('/api/v2/programmes/{programme_id}/blocks/{block_id}/tracks', {
				params: { path },
				body: { audio_track_index: draftAudio, subtitle_track_index: draftSubtitle }
			});
			if (res.error) throw toApiError(res.error, res.response);
			showToast('Track selection saved', 'success');
			open = false;
			onsaved?.();
		}, 'Could not save the track selection');
		saving = false;
	}
</script>

<Dialog bind:open title="Tracks - {title}">
	<TrackRadios
		name="cpd"
		audioTracks={detail?.audio_tracks ?? []}
		subtitleTracks={detail?.subtitle_tracks ?? []}
		bind:audio={draftAudio}
		bind:subtitle={draftSubtitle}
	/>
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
