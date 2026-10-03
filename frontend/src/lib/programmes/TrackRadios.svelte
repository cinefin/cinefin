<script lang="ts">
	import {
		audioTrackLabel,
		subtitleTrackLabel,
		type AudioTrack,
		type SubtitleTrack
	} from './create-types';

	interface Props {
		/** Radio group name prefix (`{name}-audio`, `{name}-subtitle`). */
		name: string;
		audioTracks: AudioTrack[];
		subtitleTracks: SubtitleTrack[];
		audio: number | null;
		subtitle: number | null;
	}

	let {
		name,
		audioTracks,
		subtitleTracks,
		audio = $bindable(),
		subtitle = $bindable()
	}: Props = $props();

	const legend = 'mb-1 w-full border-b border-border pb-1 text-sm font-semibold';
</script>

{#snippet radio(group: string, checked: boolean, onchange: () => void, label: string)}
	<label
		class="flex cursor-pointer items-start gap-2 rounded-sm -mx-2 px-2 py-1.5 text-sm hover:bg-surface-2"
	>
		<input type="radio" name="{name}-{group}" class="mt-0.5 accent-accent" {checked} {onchange} />
		<span class="min-w-0">{label}</span>
	</label>
{/snippet}

<div class="grid gap-4 sm:grid-cols-2">
	<fieldset class="min-w-0">
		<legend class={legend}>Audio</legend>
		{#each audioTracks as track, idx (track.id)}
			{@render radio('audio', audio === idx, () => (audio = idx), audioTrackLabel(track, idx))}
		{:else}
			<p class="py-1.5 text-sm text-muted">
				No track data - the movie plays with its default audio.
			</p>
		{/each}
	</fieldset>

	<fieldset class="min-w-0">
		<legend class={legend}>Subtitles</legend>
		{#if subtitleTracks.length}
			{@render radio('subtitle', subtitle === null, () => (subtitle = null), 'Off')}
			{#each subtitleTracks as track, idx (track.id)}
				{@render radio(
					'subtitle',
					subtitle === idx,
					() => (subtitle = idx),
					subtitleTrackLabel(track, idx)
				)}
			{/each}
		{:else}
			<p class="py-1.5 text-sm text-muted">This movie has no subtitle tracks.</p>
		{/if}
	</fieldset>
</div>
