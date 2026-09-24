<script lang="ts">
	import { fade } from 'svelte/transition';
	import { Box, Image, TriangleAlert, Upload, Video, X } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { query } from '$lib/api/query.svelte';
	import { uploadWithProgress } from '$lib/upload';
	import { showToast } from '$lib/toast.svelte';
	import type { SettingsStore } from '$lib/settings/form.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Field from './Field.svelte';

	interface Props {
		store: SettingsStore;
	}
	let { store }: Props = $props();

	const TABS = [
		{ id: 'identity', label: 'Identity' },
		{ id: 'cards', label: 'Certification cards' }
	];
	let tab = $state('identity');

	let rcSystem = $state('BBFC');
	const cards = query(() =>
		unwrap(api.GET('/api/v2/rating-cards', { params: { query: { system: rcSystem } } }))
	);

	function pickSystem(system: string) {
		rcSystem = system;
		void cards.load();
	}

	const SOURCE_LABELS: Record<string, string> = {
		static_video: 'Static video',
		custom_background: 'Custom background',
		bundled_background: 'Bundled background',
		none: 'No card source'
	};

	let fileInput: HTMLInputElement | undefined = $state();
	let uploadTarget: string | null = null;

	function pickUpload(cert: string) {
		uploadTarget = cert;
		fileInput?.click();
	}

	async function onFilePicked() {
		const file = fileInput?.files?.[0];
		if (fileInput) fileInput.value = '';
		if (!file || !uploadTarget) return;
		try {
			const res = await uploadWithProgress<{ message?: string }>(
				'/api/v2/rating-cards/upload',
				file,
				{ system: rcSystem, certification: uploadTarget }
			);
			showToast(res?.message || 'Card saved', 'success');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not save the card file', 'error');
		}
		void cards.refresh();
	}

	async function removeOverride(cert: string, kind: 'video' | 'background') {
		try {
			const msg = await mutate(
				api.DELETE('/api/v2/rating-cards', {
					params: { query: { system: rcSystem, certification: cert, kind } }
				})
			);
			showToast(msg || 'Override removed', 'success');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not remove the override', 'error');
		}
		void cards.refresh();
	}

	let previewOpen = $state(false);
	let previewCert = $state('');
	const previewUrl = $derived(
		previewCert
			? `/api/v2/rating-cards/preview?system=${encodeURIComponent(rcSystem)}&certification=${encodeURIComponent(previewCert)}&_=${Date.now()}`
			: ''
	);

	function openPreview(cert: string) {
		previewCert = cert;
		previewOpen = true;
	}
</script>

<Tabs
	tabs={TABS}
	value={tab}
	label="Theater settings"
	onselect={(id) => (tab = id)}
	panelId={(id) => `tp-${id}`}
/>

{#if tab === 'identity'}
	<div
		role="tabpanel"
		id="tp-identity"
		aria-labelledby="tab-identity"
		class="mt-4 max-w-xl space-y-4"
		in:fade={{ duration: 120 }}
	>
		<Field
			label="Theater name"
			forId="set-cinema-name"
			hint="Printed on tickets and shown around the app."
			dirty={store.isDirty('cinema_name')}
			error={store.errorFor('cinema_name')}
		>
			<Input id="set-cinema-name" bind:value={store.main.cinema_name} placeholder="Cinefin" />
		</Field>
		<Field
			label="Ratings system"
			forId="set-ratings-system"
			hint="Used when syncing ratings from Jellyfin/Plex and when fetching trailer certifications from TMDB. Ratings that don't belong to this system are flagged across the app."
			dirty={store.isDirty('ratings_system')}
			error={store.errorFor('ratings_system')}
		>
			<Select id="set-ratings-system" bind:value={store.main.ratings_system}>
				<option value="BBFC">BBFC (British - U, PG, 12, 12A, 15, 18, R18)</option>
				<option value="MPAA">MPAA (US - G, PG, PG-13, R, NC-17)</option>
			</Select>
		</Field>
	</div>
{:else if tab === 'cards'}
	<div
		role="tabpanel"
		id="tp-cards"
		aria-labelledby="tab-cards"
		class="mt-4"
		in:fade={{ duration: 120 }}
	>
		<Tabs
			class="mb-3"
			tabs={[
				{ id: 'BBFC', label: 'BBFC' },
				{ id: 'MPAA', label: 'MPAA' }
			]}
			value={rcSystem}
			label="Ratings system"
			onselect={(id) => pickSystem(id)}
		/>

		{#if cards.loading}
			<Spinner label="Loading card sources…" />
		{:else if cards.error}
			<ErrorState compact error={cards.error} retry={() => void cards.load()} />
		{:else if cards.data}
			<div class="divide-y divide-border rounded-md border border-border">
				{#each cards.data.cards as card (card.certification)}
					{@const previewable =
						card.source === 'custom_background' || card.source === 'bundled_background'}
					<div class="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
						<button
							type="button"
							class="flex min-w-0 flex-1 items-center gap-3 text-left {previewable
								? 'cursor-pointer'
								: 'cursor-default'}"
							title={previewable ? 'Preview the composed card' : undefined}
							onclick={() => previewable && openPreview(card.certification)}
						>
							<span class="w-12 shrink-0 font-mono font-semibold">{card.certification}</span>
							<span
								class="flex items-center gap-1.5 text-xs {card.source === 'none'
									? 'text-warning'
									: 'text-muted'}"
							>
								{#if card.source === 'static_video'}<Video size={13} />
								{:else if card.source === 'none'}<TriangleAlert size={13} />
								{:else if card.source === 'bundled_background'}<Box size={13} />
								{:else}<Image size={13} />{/if}
								{SOURCE_LABELS[card.source] ?? card.source}
							</span>
						</button>
						<span class="flex shrink-0 items-center gap-1.5">
							<Button size="sm" onclick={() => pickUpload(card.certification)}>
								<Upload size={13} /> Upload
							</Button>
							{#if card.static_video}
								<Button
									size="sm"
									variant="danger"
									title="Remove the static video"
									onclick={() => removeOverride(card.certification, 'video')}
								>
									<X size={13} /> Video
								</Button>
							{/if}
							{#if card.custom_background}
								<Button
									size="sm"
									variant="danger"
									title="Remove the custom background"
									onclick={() => removeOverride(card.certification, 'background')}
								>
									<X size={13} /> Background
								</Button>
							{/if}
						</span>
					</div>
				{/each}
			</div>
		{/if}
		<p class="mt-3 text-xs text-faint">
			Every certificate needs a card source. A <strong>static video</strong> is played as-is (the
			fit for MPAA-style cards, which don't carry the movie title); a
			<strong>background image</strong> has the movie title composited onto it per movie. Uploads apply
			immediately and regenerate that certificate's cards on the next playlist build. Click a background-based
			row to preview the composed card.
		</p>
		<input
			type="file"
			bind:this={fileInput}
			accept=".jpg,.jpeg,.mp4"
			hidden
			onchange={onFilePicked}
		/>
	</div>
{/if}

<Dialog bind:open={previewOpen} title="{rcSystem} {previewCert} - card preview" size="2xl">
	{#if previewOpen}
		<img src={previewUrl} alt="Composed certification card preview" class="w-full" />
	{/if}
	<p class="mt-2 text-xs text-faint">
		Rendered exactly as the generator composes it, with a sample movie title.
	</p>
</Dialog>
