<script lang="ts">
	import { Images, RotateCcw, Save, Wand2 } from '@lucide/svelte';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import type { components } from '$lib/api/types.gen';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import { base } from '$app/paths';
	import MediaPickerDialog from './MediaPickerDialog.svelte';
	import { showToast } from '$lib/toast.svelte';

	type ProgrammeDetail = components['schemas']['ProgrammeDetailSchema'];

	interface Props {
		programme: ProgrammeDetail;
		onsaved?: () => void;
	}

	let { programme, onsaved }: Props = $props();

	let templateId = $state('');
	let duration = $state('');
	let backgroundType = $state('color');
	let backgroundColor = $state('#000000');
	let backgroundFile = $state('');
	let fadeIn = $state('0');
	let fadeOut = $state('0');

	function resetForm() {
		templateId = programme.title_template_id ? String(programme.title_template_id) : '';
		duration = programme.title_duration != null ? String(programme.title_duration) : '';
		backgroundType = programme.title_background_type || 'color';
		backgroundColor = programme.title_background_color || '#000000';
		backgroundFile = programme.title_background_file || '';
		fadeIn = String(programme.title_fade_in ?? 0);
		fadeOut = String(programme.title_fade_out ?? 0);
	}

	// Re-sync the form only when the SAVED values change, so a background detail
	// refresh doesn't wipe an edit in progress.
	const savedSignature = $derived(
		[
			programme.id,
			programme.title_template_id,
			programme.title_duration,
			programme.title_background_type,
			programme.title_background_color,
			programme.title_background_file,
			programme.title_fade_in,
			programme.title_fade_out
		].join('|')
	);
	let syncedSignature = $state('');
	$effect(() => {
		if (savedSignature === syncedSignature) return;
		syncedSignature = savedSignature;
		resetForm();
	});

	let saving = $state(false);
	let pickerOpen = $state(false);

	let templates = $state<components['schemas']['TitleTemplateSchema'][]>([]);
	$effect(() => {
		void (async () => {
			try {
				// Bare-array endpoint (no envelope) — read res.data directly.
				const res = await api.GET('/api/v2/titlegen/templates');
				templates = res.data ?? [];
			} catch (e) {
				console.error('Failed to load title templates:', e);
			}
		})();
	});

	const backgroundName = $derived(
		backgroundFile ? backgroundFile.split('/').pop() || backgroundFile : 'None chosen'
	);

	const generated = $derived(!!programme.title_file_generated);
	const missingCard = $derived(!!programme.title_template_id && !generated);

	// Live preview of the SELECTED design (saved or not); `v` busts the cache when
	// that template is edited on /titles.
	const selectedTemplate = $derived(templates.find((t) => String(t.id) === templateId) ?? null);
	const previewSrc = $derived(
		templateId
			? `/api/v2/titlegen/templates/${templateId}/preview?programme_id=${programme.id}` +
					`&v=${encodeURIComponent(selectedTemplate?.updated_at ?? '')}`
			: ''
	);

	async function saveAndGenerate() {
		if (saving) return;
		saving = true;
		try {
			await unwrap(
				api.PUT('/api/v2/programmes/{programme_id}', {
					params: { path: { programme_id: programme.id } },
					body: {
						// 0 clears the template (matches the legacy save payload).
						title_template_id: templateId === '' ? 0 : parseInt(templateId, 10),
						title_duration: duration ? parseInt(duration, 10) : null,
						title_background_type: backgroundType,
						title_background_color: backgroundColor,
						title_background_file: backgroundFile,
						title_fade_in: parseFloat(fadeIn) || 0,
						title_fade_out: parseFloat(fadeOut) || 0
					}
				})
			);

			if (templateId) {
				const res = await api.POST('/api/v2/titlegen/programmes/{programme_id}/generate', {
					params: { path: { programme_id: programme.id } },
					body: { regenerate: true }
				});
				if (res.error) throw toApiError(res.error, res.response);
				if (!res.data?.success) throw new Error(res.data?.message || 'Generation failed');
				showToast('Title card saved and generated', 'success');
			} else {
				showToast('Title configuration saved', 'success');
			}
			onsaved?.();
		} catch (e) {
			showToast(`Title card: ${e instanceof Error ? e.message : 'save failed'}`, 'error');
		} finally {
			saving = false;
		}
	}
</script>

<div class="space-y-4 p-4">
	<p class="text-sm">
		{#if !programme.title_template_id}
			<span class="text-muted">
				No title screen - the programme opens on the System Ident. Choose a template to give it one.
			</span>
		{:else if missingCard}
			<span class="text-warning">Title card not generated yet - save to render it.</span>
		{:else}
			<span class="text-muted">Title card generated.</span>
		{/if}
	</p>

	{#if previewSrc}
		<figure class="max-w-3xl">
			<div class="film-grain overflow-hidden border border-border bg-black">
				<img
					src={previewSrc}
					alt="Preview of the selected title design"
					class="aspect-video w-full object-contain"
				/>
			</div>
			<figcaption class="mt-1 text-xs text-faint">
				Preview of the selected design, rendered with this programme's features. The saved card may
				differ if you change the background or duration below.
			</figcaption>
		</figure>
	{/if}

	<div class="grid max-w-3xl gap-3 sm:grid-cols-2">
		<label class="flex flex-col gap-1 text-xs text-muted">
			<span>
				Template
				<a class="text-accent hover:underline" href="{base}/titles">(edit templates)</a>
			</span>
			<Select bind:value={templateId}>
				<option value="">No title (use the System Ident)</option>
				{#each templates as t (t.id)}
					<option value={String(t.id)}>{t.name}</option>
				{/each}
			</Select>
		</label>

		<label class="flex flex-col gap-1 text-xs text-muted">
			Duration (s)
			<Input type="number" bind:value={duration} placeholder="template default" />
		</label>

		<label class="flex flex-col gap-1 text-xs text-muted">
			Background
			<Select bind:value={backgroundType}>
				<option value="color">Solid colour</option>
				<option value="image">Static image</option>
				<option value="video">Video</option>
			</Select>
		</label>

		{#if backgroundType === 'color'}
			<label class="flex flex-col gap-1 text-xs text-muted">
				Colour
				<input
					type="color"
					bind:value={backgroundColor}
					class="h-9 w-full rounded-md border border-border-strong bg-surface-2 px-1"
				/>
			</label>
		{:else}
			<div class="flex flex-col gap-1 text-xs text-muted">
				Background media
				<div class="flex items-center gap-2">
					<span class="min-w-0 flex-1 truncate text-sm text-text" title={backgroundFile}>
						{backgroundName}
					</span>
					<Button size="sm" onclick={() => (pickerOpen = true)}>
						<Images size={13} /> Choose from library
					</Button>
				</div>
				<span class="text-faint">
					Pick from your user-media library. The card is generated on the server and streamed to the
					playout host.
				</span>
			</div>
		{/if}

		<label class="flex flex-col gap-1 text-xs text-muted">
			Fade in (s)
			<Input type="number" bind:value={fadeIn} />
		</label>

		<label class="flex flex-col gap-1 text-xs text-muted">
			Fade out (s)
			<Input type="number" bind:value={fadeOut} />
		</label>
	</div>

	<div class="flex flex-wrap items-center gap-2 border-t border-border pt-3">
		<Button variant="primary" disabled={saving} onclick={() => void saveAndGenerate()}>
			{#if templateId}
				<Wand2 size={14} /> {saving ? 'Saving…' : 'Save & generate'}
			{:else}
				<Save size={14} /> {saving ? 'Saving…' : 'Save'}
			{/if}
		</Button>
		<Button disabled={saving} title="Discard these changes" onclick={resetForm}>
			<RotateCcw size={13} /> Revert
		</Button>
	</div>
</div>

<MediaPickerDialog bind:open={pickerOpen} onpick={(item) => (backgroundFile = item.file_path)} />
