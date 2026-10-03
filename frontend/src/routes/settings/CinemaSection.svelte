<script lang="ts">
	import { Box, Eye, Image, TriangleAlert, Upload, Video, X } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { query } from '$lib/api/query.svelte';
	import { uploadWithProgress } from '$lib/upload';
	import { showToast } from '$lib/toast.svelte';
	import { attempt, type SettingsStore } from '$lib/settings/form.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import SettingList from './SettingList.svelte';
	import SettingLists from './SettingLists.svelte';
	import SettingRow from './SettingRow.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import StoreField, { optionLabel, storeField } from '$lib/settings/StoreField.svelte';

	let { store }: { store: SettingsStore } = $props();

	const NAME = storeField('cinema_name', 'Theater name', 'set-cinema-name', {
		placeholder: 'Cinefin'
	});
	const RATINGS = storeField('ratings_system', 'Ratings system', 'set-ratings-system', {
		hint: "Used when syncing ratings from Jellyfin/Plex and when fetching trailer certifications from TMDB. Ratings that don't belong to this system are flagged across the app.",
		options: [
			['BBFC', 'BBFC (British - U, PG, 12, 12A, 15, 18, R18)'],
			['MPAA', 'MPAA (US - G, PG, PG-13, R, NC-17)']
		]
	});
	const SEATING = [
		storeField('ticket_total_rows', 'Rows', 'set-rows', { hint: 'Lettered A-Z, max 26.' }),
		storeField('ticket_seats_per_row', 'Seats per row', 'set-seats')
	];
	const seatingSummary = $derived.by(() => {
		const rows = parseInt(store.main.ticket_total_rows, 10) || 0;
		const per = parseInt(store.main.ticket_seats_per_row, 10) || 0;
		return `${rows} rows of ${per} · ${(rows * per).toLocaleString()} seats`;
	});

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

<SettingLists>
	<SettingList title="The theater">
		<SettingRow label="Name" hint="On tickets and around the app" summary={store.main.cinema_name}>
			<div class="max-w-md"><StoreField {store} {...NAME} /></div>
		</SettingRow>
		<SettingRow label="Seating" hint="Tickets are allocated from these" summary={seatingSummary}>
			<div class="grid max-w-md gap-4 sm:grid-cols-2">
				{#each SEATING as f (f.id)}
					<StoreField {store} {...f} type="number" />
				{/each}
			</div>
		</SettingRow>
		<SettingRow
			label="Ratings system"
			hint="Certificates from another system are flagged"
			summary={optionLabel(RATINGS, store.main.ratings_system)}
		>
			<div class="max-w-md"><StoreField {store} {...RATINGS} /></div>
		</SettingRow>
	</SettingList>

	<SettingList
		title="Certificate cards"
		text="Shown before a feature. A background gets the film's title on it; a video plays as it is."
	>
		{#snippet actions()}
			<label class="flex items-center gap-2 text-xs text-muted">
				Cards for
				<Select
					value={rcSystem}
					onchange={(e) => pickSystem((e.target as HTMLSelectElement).value)}
				>
					<option value="BBFC">BBFC</option>
					<option value="MPAA">MPAA</option>
				</Select>
			</label>
		{/snippet}
		{#if cards.loading}
			<div class="p-4"><Spinner label="Loading card sources…" /></div>
		{:else if cards.error}
			<div class="p-4">
				<ErrorState compact error={cards.error} retry={() => void cards.load()} />
			</div>
		{:else if cards.data}
			{#each cards.data.cards as card (card.certification)}
				{@const previewable =
					card.source === 'custom_background' || card.source === 'bundled_background'}
				<SettingRow label={card.certification}>
					{#snippet labelSnippet()}
						<span class="font-mono font-semibold">{card.certification}</span>
					{/snippet}
					{#snippet summarySnippet()}
						<span
							class="inline-flex items-center gap-1.5 {card.source === 'none'
								? 'text-warning'
								: ''}"
						>
							{#if card.source === 'static_video'}<Video size={13} />
							{:else if card.source === 'none'}<TriangleAlert size={13} />
							{:else if card.source === 'bundled_background'}<Box size={13} />
							{:else}<Image size={13} />{/if}
							{SOURCE_LABELS[card.source] ?? card.source}
						</span>
					{/snippet}
					{#snippet control()}
						{#if previewable}
							<Button size="sm" variant="ghost" onclick={() => openPreview(card.certification)}>
								<Eye size={13} /> Preview
							</Button>
						{/if}
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
					{/snippet}
				</SettingRow>
			{/each}
		{/if}
	</SettingList>
	<p class="-mt-3 text-xs text-faint">
		Upload a .jpg background or an .mp4 video for a certificate. It applies at once and its cards
		are made again on the next playlist build.
	</p>
	<input
		type="file"
		bind:this={fileInput}
		accept=".jpg,.jpeg,.mp4"
		hidden
		onchange={onFilePicked}
	/>
</SettingLists>

<Dialog bind:open={previewOpen} title="{rcSystem} {previewCert} - card preview" size="2xl">
	{#if previewOpen}
		<img src={previewUrl} alt="Composed certification card preview" class="w-full" />
	{/if}
	<p class="mt-2 text-xs text-faint">
		Rendered exactly as the generator composes it, with a sample movie title.
	</p>
</Dialog>
