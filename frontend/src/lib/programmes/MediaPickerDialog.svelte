<script lang="ts">
	import { FolderOpen } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { Query } from '$lib/api/query.svelte';
	import type { components } from '$lib/api/types.gen';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { formatDuration } from './helpers';

	type MediaItem = components['schemas']['MediaItemSchema'];

	interface Props {
		open?: boolean;
		onpick: (item: MediaItem) => void;
	}

	let { open = $bindable(false), onpick }: Props = $props();

	let searchInput = $state('');
	let search = $state('');
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;
	function onSearchInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => (search = searchInput), 300);
	}

	const media = new Query<components['schemas']['MediaListDataSchema']>(() =>
		unwrap(
			api.GET('/api/v2/media/list', {
				params: { query: { search: search || null, per_page: 50 } }
			})
		)
	);

	$effect(() => {
		if (!open) return;
		void search;
		void media.load();
	});

	function pick(item: MediaItem) {
		open = false;
		onpick(item);
	}
</script>

<Dialog bind:open title="Choose a background">
	<div class="space-y-3">
		<Input
			type="search"
			placeholder="Search user media by title…"
			bind:value={searchInput}
			oninput={onSearchInput}
		/>

		{#if media.loading}
			<Spinner label="Loading user media…" />
		{:else if media.error}
			<ErrorState error={media.error} retry={() => void media.load()} compact />
		{:else if !media.data?.media.length}
			<EmptyState
				icon={FolderOpen}
				title={search ? 'No user media matches your search' : 'No user media yet'}
				message={search
					? 'Try a different search.'
					: 'Upload images or clips on the Media page first.'}
				compact
			/>
		{:else}
			<ul class="max-h-72 divide-y divide-border overflow-y-auto rounded-md border border-border">
				{#each media.data.media as item (item.id)}
					<li>
						<button
							type="button"
							class="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-surface-2"
							onclick={() => pick(item)}
						>
							<div class="h-9 w-14 shrink-0 overflow-hidden rounded-sm bg-surface-3">
								{#if item.screenshot_url}
									<img
										src={item.screenshot_url}
										alt=""
										loading="lazy"
										class="h-full w-full object-cover"
									/>
								{/if}
							</div>
							<div class="min-w-0 flex-1">
								<p class="truncate text-sm">{item.title}</p>
								<p class="truncate font-mono text-xs text-faint">{item.file_path}</p>
							</div>
							<span class="font-mono text-xs text-muted">{formatDuration(item.duration)}</span>
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</div>

	{#snippet footer()}
		<Button onclick={() => (open = false)}>Cancel</Button>
	{/snippet}
</Dialog>
