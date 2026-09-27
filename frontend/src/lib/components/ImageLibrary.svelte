<script lang="ts">
	// An image library (title images, ticket images) as a tile grid: upload, delete, and —
	// with `onselect` — pick one. Deleting an image a template or design still uses is
	// refused by the server, which names them.
	import { Trash2, Upload } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { query } from '$lib/api/query.svelte';
	import { showToast } from '$lib/toast.svelte';
	import { uploadWithProgress } from '$lib/upload';
	import ConfirmDialog from './ConfirmDialog.svelte';
	import type { components } from '$lib/api/types.gen';

	type LibraryImage = components['schemas']['ImageSchema'];

	interface Props {
		library: 'titles' | 'tickets';
		/** The picked image's name, when picking. */
		selected?: string | null;
		onselect?: (image: LibraryImage) => void;
	}
	let { library, selected = null, onselect }: Props = $props();

	const ACCEPT = { titles: 'image/png,image/jpeg', tickets: 'image/png,image/jpeg,image/gif' };

	const images = query(() =>
		unwrap(api.GET('/api/v2/images/{library}', { params: { path: { library } } }))
	);

	let input = $state<HTMLInputElement>();
	let uploading = $state(false);
	let confirmDialog = $state<ConfirmDialog>();

	async function upload() {
		const file = input?.files?.[0];
		if (!file) return;
		uploading = true;
		try {
			const created = await uploadWithProgress<LibraryImage>(`/api/v2/images/${library}`, file);
			await images.refresh();
			onselect?.(created);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Upload failed', 'error');
		} finally {
			uploading = false;
			if (input) input.value = '';
		}
	}

	async function remove(image: LibraryImage) {
		if (!(await confirmDialog?.confirm(`Delete “${image.name}”?`, { confirmLabel: 'Delete' })))
			return;
		try {
			await mutate(
				api.DELETE('/api/v2/images/{library}/{name}', {
					params: { path: { library, name: image.name } }
				})
			);
			await images.refresh();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not delete the image', 'error');
		}
	}
</script>

<div class="flex flex-wrap gap-2">
	{#each images.data ?? [] as image (image.name)}
		<div
			class="group relative w-24 border p-1.5 {selected === image.name
				? 'border-accent'
				: 'border-border'} bg-surface-2"
		>
			{#snippet face()}
				<img
					src={image.url}
					alt=""
					class="h-14 w-full object-contain {library === 'tickets' ? 'bg-white' : 'bg-shell'}"
				/>
				<span class="mt-1 block truncate text-xs text-muted">{image.name}</span>
			{/snippet}
			{#if onselect}
				<button
					type="button"
					class="block w-full text-left"
					title={image.name}
					aria-pressed={selected === image.name}
					onclick={() => onselect(image)}>{@render face()}</button
				>
			{:else}
				<div title={image.name}>{@render face()}</div>
			{/if}
			<button
				type="button"
				class="absolute top-0.5 right-0.5 rounded-sm bg-surface-1 p-0.5 text-muted opacity-0 group-hover:opacity-100 hover:text-danger focus-visible:opacity-100"
				aria-label="Delete {image.name}"
				onclick={() => void remove(image)}
			>
				<Trash2 size={12} />
			</button>
		</div>
	{/each}
	<button
		type="button"
		class="flex h-[5.25rem] w-24 flex-col items-center justify-center gap-1 border border-dashed border-border-strong text-xs text-muted hover:border-accent-dim hover:text-text disabled:opacity-45"
		disabled={uploading}
		onclick={() => input?.click()}
	>
		<Upload size={15} />
		{uploading ? 'Uploading…' : 'Add image'}
	</button>
</div>
<input type="file" bind:this={input} accept={ACCEPT[library]} hidden onchange={upload} />
<ConfirmDialog bind:this={confirmDialog} />
