<script lang="ts">
	import { ArrowLeftRight, Film } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import { pickMovieIntoBlock } from '../pick-actions';
	import { idOptions, type ConfigProps } from '../types';

	let { block, ctx, commit }: ConfigProps = $props();

	const audioOptions = $derived(
		(block.details.audio_tracks ?? []).map((t) => ({
			value: String(t.index),
			label:
				`${t.language || 'Unknown'} - ${t.codec || ''} ${t.channels ? `(${t.channels}ch)` : ''}`.trim()
		}))
	);
	const subtitleOptions = $derived(
		(block.details.subtitle_tracks ?? []).map((t) => ({
			value: String(t.index),
			label: `${t.language || 'Unknown'}${t.forced ? ' (Forced)' : ''}${t.sdh ? ' (SDH)' : ''}`
		}))
	);

	const chooseMovie = () => void pickMovieIntoBlock(block, ctx, commit);
</script>

{#if !block.content.movie_id}
	<div class="flex flex-wrap items-center gap-3">
		<p class="text-sm text-muted">No movie chosen yet.</p>
		<Button size="sm" onclick={chooseMovie}>
			<Film size={12} /> Choose movie…
		</Button>
	</div>
{:else}
	<div class="flex items-start gap-4">
		{#if block.details.thumbnail_url}
			<img
				src={block.details.thumbnail_url}
				alt=""
				loading="lazy"
				class="aspect-[2/3] w-[4.75rem] shrink-0 bg-surface-3 object-cover"
			/>
		{:else}
			<div
				class="flex aspect-[2/3] w-[4.75rem] shrink-0 items-center justify-center bg-surface-3 text-faint"
			>
				<Film size={18} aria-hidden="true" />
			</div>
		{/if}
		<ConfigForm class="min-w-0 flex-1">
			<ConfigField label="Audio">
				<ConfigSelect
					value={block.content.audio_track}
					options={audioOptions}
					placeholder="Default"
					onnumber={(v) => commit(() => (block.content.audio_track = v))}
				/>
			</ConfigField>
			<ConfigField label="Subtitles">
				<ConfigSelect
					value={block.content.subtitle_track}
					options={subtitleOptions}
					placeholder="None"
					onnumber={(v) => commit(() => (block.content.subtitle_track = v))}
				/>
			</ConfigField>
			<ConfigField label="Credits command">
				<ConfigSelect
					value={block.content.credits_command_id}
					options={idOptions(ctx.commands)}
					placeholder="None"
					onnumber={(v) => commit(() => (block.content.credits_command_id = v))}
				/>
			</ConfigField>
			{#snippet actions()}
				<Button size="sm" onclick={chooseMovie}>
					<ArrowLeftRight size={12} /> Change movie
				</Button>
			{/snippet}
		</ConfigForm>
	</div>
{/if}
