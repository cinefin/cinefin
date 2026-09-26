<script lang="ts">
	// Library source — the ONE server films come from. A library takes a single
	// server: two sources would race for the same film (both plugins match on
	// tmdbid globally), so the last sync would silently overwrite the other's
	// file path, resolution and tracks. Swapping servers is Remove-then-Add.
	import { onDestroy } from 'svelte';
	import {
		ArrowRight,
		BadgeCheck,
		CheckCircle2,
		CircleAlert,
		Clock,
		FilePlus2,
		FileMinus2,
		Pencil,
		Plug,
		Plus,
		RefreshCw,
		RotateCw,
		Server,
		Trash2
	} from '@lucide/svelte';
	import { base } from '$app/paths';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import { JobStream, jobIsActive, unwrapLoose, type ApiJob, type JobEvent } from '$lib/jobs';
	import { showToast } from '$lib/toast.svelte';
	import { invalidate } from '$lib/invalidate';
	import { relativeTime } from '$lib/format';
	import { raw, type SettingsStore } from '$lib/settings/form.svelte';
	import type { CheckState } from '$lib/settings/types';
	import { fade } from 'svelte/transition';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Menu, { type MenuItem } from '$lib/components/ui/Menu.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import ChaseMark from '$lib/components/ChaseMark.svelte';
	import CheckResult from './CheckResult.svelte';
	import Field from './Field.svelte';
	import Disclosure from './Disclosure.svelte';

	interface Props {
		store: SettingsStore;
		confirm: (message: string, opts?: { confirmLabel?: string }) => Promise<boolean>;
	}
	let { store, confirm }: Props = $props();

	const TABS = [
		{ id: 'source', label: 'Source' },
		{ id: 'metadata', label: 'Metadata' }
	];
	let tab = $state('source');

	// TMDB is the library's metadata source (sync matching + fill-in) and powers trailer discovery;
	// the key rides the page's main settings form (trailers.tmdb_api_key).
	let tmdbTesting = $state(false);
	let tmdbResult = $state<CheckState>(null);

	async function testTmdb() {
		tmdbTesting = true;
		tmdbResult = { state: 'pending', message: 'Testing…' };
		try {
			const res = await raw(
				api.POST('/api/v2/settings/test-tmdb/', {
					body: { api_key: store.trailers.tmdb_api_key.trim() || null }
				})
			);
			tmdbResult = { state: res.ok ? 'ok' : 'error', message: res.message };
		} catch (e) {
			tmdbResult = { state: 'error', message: e instanceof Error ? e.message : 'Test failed' };
		} finally {
			tmdbTesting = false;
		}
	}

	interface SourceType {
		type_id: string;
		label: string;
	}
	interface Source {
		id: number;
		name: string;
		sync_type: string;
		url: string;
		libraries: string;
		enabled: boolean;
		last_sync: string | null;
		movie_count: number;
	}
	interface TheSource {
		source: Source | null;
		types: SourceType[];
	}

	const sourceQ = query(() => unwrapLoose<TheSource>(api.GET('/api/v2/sync/source')));
	const source = $derived(sourceQ.data?.source ?? null);
	const types = $derived(sourceQ.data?.types ?? []);

	let job = $state<ApiJob | null>(null);
	const running = $derived(jobIsActive(job?.state));

	function apply(event: JobEvent) {
		job = { ...(job ?? ({} as ApiJob)), ...event, id: event.job_id } as ApiJob;
	}

	const stream = new JobStream(
		{ kind: 'sync' },
		{
			onState: apply,
			onProgress: apply,
			onComplete: (event) => {
				apply(event);
				// The receipt and "last sync" both come from the DB, and the log
				// only arrives with the full row.
				void loadCurrentJob();
				void sourceQ.refresh();
				invalidate(['sync', 'movies']);
			},
			// Reconnects reconcile against the DB: a run that finished while the
			// stream was down never sends a complete event on the new connection.
			onOpen: () => void loadCurrentJob()
		}
	);
	$effect(() => {
		stream.open();
		return () => stream.close();
	});
	onDestroy(() => stream.close());

	async function loadCurrentJob() {
		try {
			const data = await unwrapLoose<{ jobs: ApiJob[] }>(
				api.GET('/api/v2/sync/jobs', { params: { query: { limit: 1 } } })
			);
			job = data.jobs?.[0] ?? null;
		} catch {
			// The last run is garnish; the card works without it.
		}
	}

	const receipt = $derived.by(() => {
		const counts = job?.counts;
		if (!counts) return '';
		const parts: string[] = [];
		for (const [key, label] of [
			['added', 'added'],
			['updated', 'updated'],
			['removed', 'removed'],
			['unmatched', 'unmatched'],
			['failed', 'failed']
		] as const) {
			const value = (counts as Record<string, number>)[key];
			if (value) parts.push(`${value} ${label}`);
		}
		return parts.length ? parts.join(' · ') : 'nothing changed';
	});

	// ── What changed on the last run ─────────────────────────────────────────
	// The run receipt (Job.counts.changes) carries up to 50 titles per bucket.
	let changesOpen = $state(false);
	const CHANGE_GROUPS = [
		{ key: 'added', label: 'Added', icon: FilePlus2, link: true },
		{ key: 'updated', label: 'Updated', icon: RefreshCw, link: true },
		{ key: 'removed', label: 'Removed', icon: FileMinus2, link: false },
		{ key: 'unmatched', label: 'Unmatched', icon: CircleAlert, link: false }
	] as const;
	const changeGroups = $derived.by(() => {
		const changes = job?.counts?.changes;
		if (!changes) return [];
		return CHANGE_GROUPS.map((g) => ({ ...g, titles: changes[g.key] ?? [] })).filter(
			(g) => g.titles.length
		);
	});
	const hasChanges = $derived(changeGroups.length > 0);

	let busy = $state('');

	async function syncNow(deep = false) {
		if (!source) return;
		busy = deep ? 'deep' : 'sync';
		try {
			await unwrapLoose(
				api.POST('/api/v2/sync/sources/{source_id}/runs', {
					params: { path: { source_id: source.id } },
					body: { operation: 'sync', params: deep ? { deep: true } : {}, max_attempts: 1 }
				})
			);
			showToast(deep ? 'Full re-scan started' : 'Sync started', 'success');
		} catch (e) {
			showToast(toApiError(e).message || 'Could not start the sync', 'error');
		} finally {
			busy = '';
		}
	}

	async function cancelRun() {
		if (!source) return;
		try {
			await unwrapLoose(
				api.DELETE('/api/v2/sync/sources/{source_id}/runs/current', {
					params: { path: { source_id: source.id } }
				})
			);
		} catch (e) {
			showToast(toApiError(e).message || 'Could not cancel', 'error');
		}
	}

	async function findCertificates() {
		busy = 'ratings';
		try {
			await unwrap(api.POST('/api/v2/trailers/ratings/update', { body: { scope: 'movies' } }));
			showToast('Looking up missing certificates', 'success');
		} catch (e) {
			showToast(toApiError(e).message || 'Could not start the lookup', 'error');
		} finally {
			busy = '';
		}
	}

	async function testConnection() {
		if (!source) return;
		busy = 'test';
		try {
			const data = await unwrapLoose<{ ok: boolean; message: string }>(
				api.POST('/api/v2/sync/sources/{source_id}/test', {
					params: { path: { source_id: source.id } }
				})
			);
			showToast(
				data.message || (data.ok ? 'Connected' : 'Could not connect'),
				data.ok ? 'success' : 'error'
			);
		} catch (e) {
			showToast(toApiError(e).message || 'Could not reach the server', 'error');
		} finally {
			busy = '';
		}
	}

	// Removal opens a dialog so the operator can also delete the source's films
	// (otherwise they stay, orphaned) — see confirmRemoveSource.
	let removeOpen = $state(false);
	let removeAlsoMovies = $state(false);
	let removing = $state(false);

	function removeSource() {
		if (!source) return;
		removeAlsoMovies = false;
		removeOpen = true;
	}

	async function confirmRemoveSource() {
		if (!source) return;
		removing = true;
		try {
			const res = await unwrapLoose<{ movies_deleted?: number }>(
				api.DELETE('/api/v2/sync/sources/{source_id}', {
					params: { path: { source_id: source.id }, query: { delete_movies: removeAlsoMovies } }
				})
			);
			const n = res?.movies_deleted ?? 0;
			showToast(
				removeAlsoMovies && n > 0
					? `Library source removed and ${n} ${n === 1 ? 'film' : 'films'} deleted`
					: 'Library source removed',
				'success'
			);
			removeOpen = false;
			void sourceQ.load();
			invalidate('sync');
			if (removeAlsoMovies) invalidate('movies');
		} catch (e) {
			showToast(toApiError(e).message || 'Could not remove the source', 'error');
		} finally {
			removing = false;
		}
	}

	// Full wipe: delete every film in the library (any source, incl. orphans).
	async function clearLibrary() {
		let preview: { total: number; in_use: number };
		try {
			preview = await unwrap(api.GET('/api/v2/movies/clear-library'));
		} catch (e) {
			showToast(toApiError(e).message || 'Could not read the library', 'error');
			return;
		}
		if (preview.total === 0) {
			showToast('The library is already empty', 'info');
			return;
		}
		const used =
			preview.in_use > 0
				? ` ${preview.in_use} ${preview.in_use === 1 ? 'is' : 'are'} used in programmes and will be removed from them.`
				: '';
		const ok = await confirm(
			`Delete all ${preview.total} ${preview.total === 1 ? 'film' : 'films'} from the library?${used} This cannot be undone.`,
			{ confirmLabel: 'Delete all' }
		);
		if (!ok) return;
		try {
			const data = await unwrap(api.POST('/api/v2/movies/clear-library'));
			showToast(`Deleted ${data.deleted} ${data.deleted === 1 ? 'film' : 'films'}`, 'success');
			invalidate('movies');
			void sourceQ.load();
		} catch (e) {
			showToast(toApiError(e).message || 'Could not clear the library', 'error');
		}
	}

	// Sync-now caret menu + the separate "More" menu (spec: two groups).
	const syncMenuItems = $derived<MenuItem[]>([
		{
			label: 'Full re-scan',
			icon: RotateCw,
			onclick: () => void syncNow(true),
			disabled: running || busy !== ''
		}
	]);
	const moreItems = $derived<MenuItem[]>([
		{
			label: 'Test connection',
			icon: Plug,
			onclick: () => void testConnection(),
			disabled: busy !== ''
		},
		{
			label: 'Find certificates',
			icon: BadgeCheck,
			onclick: () => void findCertificates(),
			disabled: busy !== ''
		},
		{ separator: true },
		{ label: 'Edit source', icon: Pencil, onclick: openEdit, disabled: running },
		{
			label: 'Clear library…',
			icon: Trash2,
			danger: true,
			onclick: () => void clearLibrary(),
			disabled: running || busy !== ''
		},
		{
			label: 'Remove source',
			icon: Trash2,
			danger: true,
			onclick: () => removeSource(),
			disabled: running
		}
	]);

	let formOpen = $state(false);
	let fType = $state('');
	let fName = $state('');
	let fUrl = $state('');
	let fToken = $state('');
	let fLibs = $state<string[]>([]);
	let saving = $state(false);

	// Libraries come from probing the server. `available` is null until a probe
	// runs; `manual` is the typed-names fallback for when it can't be reached.
	let available = $state<string[] | null>(null);
	let probing = $state(false);
	let probeMsg = $state('');
	let manual = $state(false);
	let manualText = $state('');

	function splitLibs(csv: string): string[] {
		return csv
			.split(',')
			.map((s) => s.trim())
			.filter(Boolean);
	}

	// The whole picklist: what the server reported plus anything already chosen
	// (so a saved library the server no longer lists never silently drops).
	const libOptions = $derived.by(() => {
		const set = new Set<string>(available ?? []);
		for (const l of fLibs) set.add(l);
		return [...set];
	});

	function resetLibs(csv: string) {
		fLibs = splitLibs(csv);
		manualText = csv;
		available = null;
		probeMsg = '';
		manual = false;
	}

	function toggleLib(name: string) {
		fLibs = fLibs.includes(name) ? fLibs.filter((l) => l !== name) : [...fLibs, name];
	}

	async function fetchLibraries() {
		if (!fUrl.trim()) {
			showToast('The server URL is required', 'error');
			return;
		}
		if (!source && !fToken.trim()) {
			showToast('An API token is required', 'error');
			return;
		}
		probing = true;
		probeMsg = '';
		try {
			const data = await unwrapLoose<{ success: boolean; message: string; libraries: string[] }>(
				api.POST('/api/v2/sync/probe', {
					body: {
						sync_type: fType,
						url: fUrl.trim(),
						token: fToken.trim() || null,
						source_id: source?.id ?? null
					}
				})
			);
			if (!data.success) {
				available = null;
				probeMsg = data.message || 'Could not reach the server';
				return;
			}
			available = data.libraries ?? [];
			manual = false;
			probeMsg = available.length ? '' : 'The server reported no movie libraries.';
		} catch (e) {
			available = null;
			probeMsg = toApiError(e).message || 'Could not reach the server';
		} finally {
			probing = false;
		}
	}

	function openAdd(typeId: string) {
		fType = typeId;
		fName = types.find((t) => t.type_id === typeId)?.label ?? typeId;
		fUrl = '';
		fToken = '';
		resetLibs('Movies');
		formOpen = true;
	}

	function openEdit() {
		if (!source) return;
		fType = source.sync_type;
		fName = source.name;
		fUrl = source.url;
		fToken = '';
		resetLibs(source.libraries);
		formOpen = true;
	}

	async function save() {
		if (!fUrl.trim()) {
			showToast('The server URL is required', 'error');
			return;
		}
		if (!source && !fToken.trim()) {
			showToast('An API token is required', 'error');
			return;
		}
		const libraries = (manual ? splitLibs(manualText) : fLibs).join(',');
		if (!libraries) {
			showToast('Choose at least one library', 'error');
			return;
		}
		saving = true;
		try {
			if (source) {
				await unwrapLoose(
					api.PATCH('/api/v2/sync/sources/{source_id}', {
						params: { path: { source_id: source.id } },
						// An empty token means "keep the one you have".
						body: {
							name: fName,
							url: fUrl,
							libraries,
							...(fToken ? { token: fToken } : {})
						}
					})
				);
			} else {
				await unwrapLoose(
					api.POST('/api/v2/sync/sources', {
						body: {
							name: fName,
							sync_type: fType,
							url: fUrl,
							token: fToken,
							libraries,
							enabled: true
						}
					})
				);
			}
			showToast('Library source saved', 'success');
			formOpen = false;
			void sourceQ.load();
			invalidate('sync');
		} catch (e) {
			showToast(toApiError(e).message || 'Could not save the source', 'error');
		} finally {
			saving = false;
		}
	}
</script>

<Tabs
	tabs={TABS}
	value={tab}
	label="Library settings"
	onselect={(id) => (tab = id)}
	panelId={(id) => `lt-${id}`}
/>

{#if tab === 'source'}
	<div
		role="tabpanel"
		id="lt-source"
		aria-labelledby="tab-source"
		class="mt-4"
		in:fade={{ duration: 120 }}
	>
		{#if sourceQ.loading}
			<Spinner label="Loading the library source…" />
		{:else if sourceQ.error}
			<ErrorState error={sourceQ.error} retry={() => void sourceQ.load()} />
		{:else if !source && !formOpen}
			<EmptyState
				icon={Server}
				title="No library source yet"
				message="Cinefin reads your films from one media server. Pick the one you run."
			>
				{#snippet action()}
					<div class="flex gap-2">
						{#each types as t (t.type_id)}
							<Button variant="primary" onclick={() => openAdd(t.type_id)}>
								<Plus size={14} />
								{t.label}
							</Button>
						{/each}
					</div>
				{/snippet}
			</EmptyState>
		{:else if formOpen}
			<section class="max-w-2xl space-y-4 border border-border bg-surface-1 p-4">
				<h3 class="text-sm font-semibold">
					{source
						? `Edit ${source.name}`
						: `Add ${types.find((t) => t.type_id === fType)?.label ?? ''}`}
				</h3>
				<Field label="Name" forId="src-name">
					<Input id="src-name" bind:value={fName} />
				</Field>
				<Field label="Server URL" forId="src-url">
					<Input id="src-url" bind:value={fUrl} placeholder="http://192.0.2.10:32400" />
				</Field>
				<Field label="API token" forId="src-token">
					<Input id="src-token" type="password" bind:value={fToken} />
					{#snippet hintSnippet()}
						{source
							? 'Leave blank to keep the token you already have.'
							: 'Plex: X-Plex-Token. Jellyfin: an API key from its dashboard.'}
					{/snippet}
				</Field>
				<Field label="Libraries">
					{#if manual}
						<Input bind:value={manualText} placeholder="Films, Documentaries" />
					{:else}
						<div class="space-y-2">
							<Button size="sm" disabled={probing} onclick={() => void fetchLibraries()}>
								<RefreshCw size={14} />
								{probing ? 'Fetching…' : available ? 'Refresh list' : 'Fetch available libraries'}
							</Button>
							{#if available}
								{#if libOptions.length}
									<div class="space-y-1">
										{#each libOptions as name (name)}
											<label class="flex items-center gap-2 text-sm">
												<input
													type="checkbox"
													class="accent-accent"
													checked={fLibs.includes(name)}
													onchange={() => toggleLib(name)}
												/>
												{name}
												{#if !(available ?? []).includes(name)}
													<span class="text-xs text-faint">(not on server)</span>
												{/if}
											</label>
										{/each}
									</div>
								{/if}
							{/if}
							{#if probeMsg}
								<p class="text-sm text-danger">{probeMsg}</p>
							{/if}
						</div>
					{/if}
					{#snippet hintSnippet()}
						The movie libraries to read.
						<button
							type="button"
							class="text-accent hover:underline"
							onclick={() => {
								if (manual) fLibs = splitLibs(manualText);
								else manualText = fLibs.join(', ');
								manual = !manual;
							}}
						>
							{manual ? 'Pick from the server instead' : 'Enter names manually'}
						</button>
					{/snippet}
				</Field>
				<div class="flex gap-2">
					<Button variant="primary" disabled={saving} onclick={() => void save()}>
						{saving ? 'Saving…' : 'Save'}
					</Button>
					<Button onclick={() => (formOpen = false)}>Cancel</Button>
				</div>
			</section>
		{:else if source}
			<section class="max-w-2xl border border-border bg-surface-1">
				<div class="space-y-2.5 p-4">
					<div class="flex flex-wrap items-center gap-2">
						<Server size={15} class="text-muted" />
						<span class="font-medium">{source.name}</span>
						<code class="font-mono text-xs text-muted">{source.url}</code>
						<Badge variant={source.enabled ? 'default' : 'outline'}>
							{source.enabled ? 'Enabled' : 'Disabled'}
						</Badge>
					</div>

					<p class="text-sm text-muted">
						<span class="text-faint">Libraries</span>
						{source.libraries || '-'}
					</p>

					{#if running}
						<div class="space-y-2">
							<div class="flex items-center gap-2 text-sm">
								<ChaseMark height={14} />
								<span
									>{job?.phase || 'Scanning'}{job?.percentage ? ` - ${job.percentage}%` : ''}</span
								>
								{#if job?.current_item}
									<span class="min-w-0 truncate text-muted">{job.current_item}</span>
								{/if}
								<Button size="sm" class="ml-auto shrink-0" onclick={() => void cancelRun()}
									>Stop</Button
								>
							</div>
							{#if job?.total}
								<div
									class="h-1.5 overflow-hidden rounded-xs bg-surface-3"
									role="progressbar"
									aria-valuenow={Math.round(job.percentage)}
									aria-valuemin={0}
									aria-valuemax={100}
								>
									<div
										class="h-full bg-accent transition-[width]"
										style="width: {Math.max(0, Math.min(100, job.percentage))}%"
									></div>
								</div>
							{/if}
						</div>
					{:else if job}
						<p class="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm">
							{#if job.state === 'success'}
								<CheckCircle2 size={14} class="text-success" />
							{:else}
								<CircleAlert size={14} class="text-danger" />
							{/if}
							<span class="text-muted">Last sync</span>
							<span>{source.last_sync ? relativeTime(source.last_sync) : 'never'}</span>
							<span class="text-faint">·</span>
							<span class="font-mono text-xs">{receipt}</span>
							{#if hasChanges}
								<button
									type="button"
									class="ml-1 inline-flex items-center gap-1 text-xs text-accent hover:underline"
									onclick={() => (changesOpen = true)}
								>
									View changes <ArrowRight size={12} />
								</button>
							{/if}
						</p>
					{:else}
						<p class="flex items-center gap-1.5 text-sm text-muted">
							<Clock size={14} /> Never synced
						</p>
					{/if}
				</div>

				<div class="flex flex-wrap items-center gap-2 border-t border-border p-3">
					<!-- Split button: Sync now (background incremental) + a caret for the
					     re-scan variant. A separate "More" menu holds the rest, so the row
					     stays one line instead of six wrapping buttons. -->
					<div class="inline-flex items-stretch">
						<Button
							variant="primary"
							class="rounded-r-none"
							disabled={running || busy !== ''}
							onclick={() => void syncNow(false)}
						>
							<RefreshCw size={14} /> Sync now
						</Button>
						<Menu
							variant="primary"
							caretOnly
							ariaLabel="More sync options"
							class="rounded-l-none border-l border-on-accent/25"
							items={syncMenuItems}
						/>
					</div>
					<Menu label="More" items={moreItems} />
				</div>

				{#if job?.log?.length}
					<div class="border-t border-border px-3 py-2">
						<Disclosure title="Show the log">
							<pre
								class="max-h-72 overflow-auto bg-surface-2 p-2 font-mono text-xs whitespace-pre-wrap text-muted">{job.log
									.map((entry) => `${entry.level}  ${entry.message}`)
									.join('\n')}</pre>
						</Disclosure>
					</div>
				{/if}
			</section>
		{/if}
	</div>
{:else if tab === 'metadata'}
	<div
		role="tabpanel"
		id="lt-metadata"
		aria-labelledby="tab-metadata"
		class="mt-4 max-w-xl"
		in:fade={{ duration: 120 }}
	>
		<Field label="TMDB API key" forId="set-tmdb-key" dirty={store.isDirty('trailers.tmdb_api_key')}>
			<div class="flex gap-2">
				<Input
					id="set-tmdb-key"
					bind:value={store.trailers.tmdb_api_key}
					placeholder="TMDB API key (v3)"
				/>
				<Button disabled={tmdbTesting} onclick={testTmdb}><Plug size={14} /> Test</Button>
			</div>
			{#snippet hintSnippet()}
				Matches your films and fills in missing metadata during a sync, and powers trailer
				discovery. Get a free key from
				<a
					href="https://www.themoviedb.org/settings/api"
					target="_blank"
					rel="noopener"
					class="text-accent hover:underline">themoviedb.org → Settings → API</a
				>.
			{/snippet}
		</Field>
		<CheckResult result={tmdbResult} class="mt-2" />

		<Field
			label="Trailer download quality"
			forId="set-trailer-quality"
			dirty={store.isDirty('trailers.download_quality')}
			class="mt-5"
		>
			<Select id="set-trailer-quality" bind:value={store.trailers.download_quality} class="w-full">
				<option value="720">720p</option>
				<option value="1080">1080p</option>
				<option value="1440">1440p</option>
				<option value="2160">2160p (4K)</option>
				<option value="best">Best available</option>
			</Select>
			{#snippet hintSnippet()}
				The maximum resolution trailers download at. YouTube trailers often top out at 1080p; a
				higher setting is only used when a better source exists.
			{/snippet}
		</Field>
	</div>
{/if}

<!-- What changed on the last completed sync (Job.counts.changes). -->
<Dialog bind:open={changesOpen} title="Changes since last sync" size="lg">
	{#if source}
		<p class="mb-4 text-sm text-muted">
			{source.last_sync ? `Synced ${relativeTime(source.last_sync)}` : 'Last run'} · {receipt}
		</p>
	{/if}
	{#if changeGroups.length}
		<div class="space-y-5">
			{#each changeGroups as g (g.key)}
				{@const GroupIcon = g.icon}
				<section>
					<h3 class="mb-2 flex items-center gap-1.5 text-sm font-medium">
						<GroupIcon size={14} class="text-muted" />
						{g.label}
						<span class="font-mono text-xs text-faint">{g.titles.length}</span>
					</h3>
					<div class="flex flex-wrap gap-1.5">
						{#each g.titles as title (title)}
							{#if g.link}
								<a
									href="{base}/library?search={encodeURIComponent(title)}"
									class="max-w-full truncate rounded-sm border border-border-strong bg-surface-2 px-2 py-0.5 text-xs text-text hover:border-accent-dim hover:text-accent"
									title="Find “{title}” in the library"
								>
									{title}
								</a>
							{:else}
								<span
									class="max-w-full truncate rounded-sm border border-border bg-surface-1 px-2 py-0.5 text-xs text-muted"
									{title}
								>
									{title}
								</span>
							{/if}
						{/each}
					</div>
					{#if g.titles.length >= 50}
						<p class="mt-1.5 text-xs text-faint">First 50 shown.</p>
					{/if}
				</section>
			{/each}
		</div>
	{:else}
		<p class="text-sm text-muted">The last sync changed nothing.</p>
	{/if}
	{#snippet footer()}
		<Button onclick={() => (changesOpen = false)}>Close</Button>
	{/snippet}
</Dialog>

<Dialog bind:open={removeOpen} title="Remove library source" size="md">
	{#if source}
		<div class="space-y-3 p-4 text-sm">
			<p>
				Remove <span class="font-medium text-text">{source.name}</span>? You can then add a
				different server.
			</p>
			<label class="flex items-start gap-2">
				<input type="checkbox" bind:checked={removeAlsoMovies} class="mt-0.5" />
				<span>
					Also delete its {source.movie_count}
					{source.movie_count === 1 ? 'film' : 'films'} from the library
				</span>
			</label>
			<p class="text-xs text-muted">
				{removeAlsoMovies
					? 'The films are removed from the library and from any programmes that use them — this cannot be undone.'
					: 'The films stay in your library but stop being synced.'}
			</p>
		</div>
	{/if}
	{#snippet footer()}
		<Button onclick={() => (removeOpen = false)}>Cancel</Button>
		<Button variant="danger" disabled={removing} onclick={() => void confirmRemoveSource()}>
			{removing ? 'Removing…' : 'Remove'}
		</Button>
	{/snippet}
</Dialog>
