<script lang="ts">
	import { Box, Image, TriangleAlert, Upload, Video, X } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { query } from '$lib/api/query.svelte';
	import { uploadWithProgress } from '$lib/upload';
	import { showToast } from '$lib/toast.svelte';
	import { attempt, type SettingsStore } from '$lib/settings/form.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import SectionTabs from './SectionTabs.svelte';
	import TabPanel from './TabPanel.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Field from '$lib/settings/Field.svelte';
	import StoreField, { storeField } from '$lib/settings/StoreField.svelte';

	let { store }: { store: SettingsStore } = $props();

	const TABS = [
		{ id: 'identity', label: 'Identity' },
		{ id: 'cards', label: 'Certification cards' }
	];
	let tab = $state('identity');

	const IDENTITY = [
		storeField('cinema_name', 'Theater name', 'set-cinema-name', {
			hint: 'Printed on tickets and shown around the app.',
			placeholder: 'Cinefin'
		}),
		storeField('ratings_system', 'Ratings system', 'set-ratings-system', {
			hint: "Used when syncing ratings from Jellyfin/Plex and when fetching trailer certifications from TMDB. Ratings that don't belong to this system are flagged across the app.",
			options: [
				['BBFC', 'BBFC (British - U, PG, 12, 12A, 15, 18, R18)'],
				['MPAA', 'MPAA (US - G, PG, PG-13, R, NC-17)']
			]
		})
	];
	const SEATING = [
		storeField('ticket_total_rows', 'Rows', 'set-rows', { hint: 'Lettered A-Z, max 26.' }),
		storeField('ticket_seats_per_row', 'Seats per row', 'set-seats')
	];

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

	const OVERRIDES = [
		{ kind: 'video', has: 'static_video', what: 'static video', label: 'Video' },
		{ kind: 'background', has: 'custom_background', what: 'custom background', label: 'Background' }
	] as const;

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
		const certification = uploadTarget;
		await attempt(async () => {
			const res = await uploadWithProgress<{ message?: string }>(
				'/api/v2/rating-cards/upload',
				file,
				{ system: rcSystem, certification }
			);
			showToast(res?.message || 'Card saved', 'success');
		}, 'Could not save the card file');
		void cards.refresh();
	}

	async function removeOverride(cert: string, kind: 'video' | 'background') {
		await attempt(async () => {
			const msg = await mutate(
				api.DELETE('/api/v2/rating-cards', {
					params: { query: { system: rcSystem, certification: cert, kind } }
				})
			);
			showToast(msg || 'Override removed', 'success');
		}, 'Could not remove the override');
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

<SectionTabs tabs={TABS} bind:value={tab} label="Theater settings" prefix="tp" />

{#if tab === 'identity'}
	<TabPanel prefix="tp" tab="identity" class="mt-4 max-w-xl space-y-4">
		{#each IDENTITY as f (f.id)}
			<StoreField {store} {...f} />
		{/each}
		<div class="grid gap-4 sm:grid-cols-3">
			{#each SEATING as f (f.id)}
				<StoreField {store} {...f} type="number" />
			{/each}
			<Field label="Seats" hint="Tickets are allocated from these.">
				<div class="flex h-9 items-center font-mono text-lg">
					{(
						(parseInt(store.main.ticket_total_rows, 10) || 0) *
						(parseInt(store.main.ticket_seats_per_row, 10) || 0)
					).toLocaleString()}
				</div>
			</Field>
		</div>
	</TabPanel>
{:else if tab === 'cards'}
	<TabPanel prefix="tp" tab="cards" class="mt-4">
		<Tabs
			class="mb-3"
			tabs={[
				{ id: 'BBFC', label: 'BBFC' },
				{ id: 'MPAA', label: 'MPAA' }
			]}
			value={rcSystem}
			label="Ratings system"
			onselect={pickSystem}
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
							{#each OVERRIDES as o (o.kind)}
								{#if card[o.has]}
									<Button
										size="sm"
										variant="danger"
										title="Remove the {o.what}"
										onclick={() => removeOverride(card.certification, o.kind)}
									>
										<X size={13} />
										{o.label}
									</Button>
								{/if}
							{/each}
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
	</TabPanel>
{/if}

<Dialog bind:open={previewOpen} title="{rcSystem} {previewCert} - card preview" size="2xl">
	{#if previewOpen}
		<img src={previewUrl} alt="Composed certification card preview" class="w-full" />
	{/if}
	<p class="mt-2 text-xs text-faint">
		Rendered exactly as the generator composes it, with a sample movie title.
	</p>
</Dialog>
