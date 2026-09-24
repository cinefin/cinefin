<script lang="ts">
	import { ArrowLeftRight, Film } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import { pickMovieIntoBlock } from '../pick-actions';
	import type { EditorBlock, EditorContext } from '../types';

	interface Props {
		block: EditorBlock;
		ctx: EditorContext;
		commit: (mutate: () => void) => void;
	}

	let { block, ctx, commit }: Props = $props();

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
	const commandOptions = $derived(
		ctx.commands.map((c) => ({ value: String(c.id), label: c.name }))
	);

	async function chooseMovie(): Promise<void> {
		await pickMovieIntoBlock(block, ctx, commit);
	}

	function setTrack(field: 'audio_track' | 'subtitle_track', value: string): void {
		commit(() => {
			block.content[field] = value === '' ? null : parseInt(value, 10);
		});
	}
</script>

{#if !block.content.movie_id}
	<div class="flex flex-wrap items-center gap-3">
		<p class="text-sm text-muted">No movie chosen yet.</p>
		<Button size="sm" onclick={() => void chooseMovie()}>
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
					value={block.content.audio_track != null ? String(block.content.audio_track) : ''}
					options={audioOptions}
					placeholder="Default"
					onchange={(v) => setTrack('audio_track', v)}
				/>
			</ConfigField>
			<ConfigField label="Subtitles">
				<ConfigSelect
					value={block.content.subtitle_track != null ? String(block.content.subtitle_track) : ''}
					options={subtitleOptions}
					placeholder="None"
					onchange={(v) => setTrack('subtitle_track', v)}
				/>
			</ConfigField>
			<ConfigField label="Credits command">
				<ConfigSelect
					value={block.content.credits_command_id ? String(block.content.credits_command_id) : ''}
					options={commandOptions}
					placeholder="None"
					onchange={(v) =>
						commit(() => {
							block.content.credits_command_id = v === '' ? null : parseInt(v, 10);
						})}
				/>
			</ConfigField>
			{#snippet actions()}
				<Button size="sm" onclick={() => void chooseMovie()}>
					<ArrowLeftRight size={12} /> Change movie
				</Button>
			{/snippet}
		</ConfigForm>
	</div>
{/if}
