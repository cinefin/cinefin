<script lang="ts">
	// The ONE server films come from: two would race for the same film (both match on tmdbid), the
	// last sync silently overwriting the other's paths and tracks. Swapping servers is Remove, then Add.
	import {
		ArrowRight,
		BadgeCheck,
		CheckCircle2,
		CircleAlert,
		Clock,
		FilePlus2,
		FileMinus2,
		Plug,
		Plus,
		RefreshCw,
		RotateCw,
		Server,
		Trash2
	} from '@lucide/svelte';
	import { base } from '$app/paths';
	import { api, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import { JobStream, jobIsActive, unwrapLoose, type ApiJob, type JobEvent } from '$lib/jobs';
	import { showToast } from '$lib/toast.svelte';
	import { invalidate } from '$lib/invalidate';
	import { relativeTime } from '$lib/format';
	import { attempt, errorText, raw, runCheck, type SettingsStore } from '$lib/settings/form.svelte';
	import type { CheckState } from '$lib/settings/types';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Menu, { type MenuItem } from '$lib/components/ui/Menu.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ChaseMark from '$lib/components/ChaseMark.svelte';
	import CheckResult from './CheckResult.svelte';
	import Field from '$lib/settings/Field.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import SettingList from './SettingList.svelte';
	import SettingLists from './SettingLists.svelte';
	import SettingRow from './SettingRow.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import { untrack } from 'svelte';

	interface Props {
		store: SettingsStore;
		confirm: ConfirmDialog['confirm'];
	}
	let { store, confirm }: Props = $props();

	// The TMDB key is part of the page's settings draft (trailers.tmdb_api_key) and saves itself.
	let tmdbTesting = $state(false);
	let tmdbResult = $state<CheckState>(null);

	async function testTmdb() {
		tmdbTesting = true;
		tmdbResult = { state: 'pending', message: 'Testing…' };
		tmdbResult = await runCheck(() =>
			raw(
				api.POST('/api/v2/settings/test-tmdb/', {
					body: { api_key: store.trailers.tmdb_api_key.trim() || null }
				})
			)
		);
		tmdbTesting = false;
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
	const sourceQ = query(() =>
		unwrapLoose<{ source: Source | null; types: { type_id: string; label: string }[] }>(
			api.GET('/api/v2/sync/source')
		)
	);
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
				// The receipt, "last sync" and the log come with the full row.
				void loadCurrentJob();
				void sourceQ.refresh();
				invalidate(['sync', 'movies']);
			},
			// A run that finished while the stream was down never sends its complete event.
			onOpen: () => void loadCurrentJob()
		}
	);
	$effect(() => {
		stream.open();
		return () => stream.close();
	});

	async function loadCurrentJob() {
		try {
			const data = await unwrapLoose<{ jobs: ApiJob[] }>(
				api.GET('/api/v2/sync/jobs', { params: { query: { limit: 1 } } })
			);
			job = data.jobs?.[0] ?? null;
		} catch {
			// Garnish: the card works without the last run.
		}
	}

	const receipt = $derived.by(() => {
		const counts = job?.counts;
		if (!counts) return '';
		const parts = ['added', 'updated', 'removed', 'unmatched', 'failed']
			.map((key) => [(counts as Record<string, number>)[key], key] as const)
			.filter(([n]) => n)
			.map(([n, key]) => `${n} ${key}`);
		return parts.length ? parts.join(' · ') : 'nothing changed';
	});

	// What the last run changed: Job.counts.changes carries up to 50 titles per bucket.
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

	let busy = $state('');

	// Runs one of the card's actions, marking it busy until it settles.
	async function busyWith(key: string, fail: string, fn: () => Promise<unknown>) {
		busy = key;
		await attempt(fn, fail);
		busy = '';
	}

	const films = (n: number) => `${n} ${n === 1 ? 'film' : 'films'}`;

	async function syncNow(deep = false) {
		if (!source) return;
		const source_id = source.id;
		await busyWith(deep ? 'deep' : 'sync', 'Could not start the sync', async () => {
			await unwrapLoose(
				api.POST('/api/v2/sync/sources/{source_id}/runs', {
					params: { path: { source_id } },
					body: { operation: 'sync', params: deep ? { deep: true } : {}, max_attempts: 1 }
				})
			);
			showToast(deep ? 'Full re-scan started' : 'Sync started', 'success');
		});
	}

	async function cancelRun() {
		if (!source) return;
		const path = { source_id: source.id };
		await attempt(
			() =>
				unwrapLoose(
					api.DELETE('/api/v2/sync/sources/{source_id}/runs/current', { params: { path } })
				),
			'Could not cancel'
		);
	}

	async function findCertificates() {
		await busyWith('ratings', 'Could not start the lookup', async () => {
			await unwrap(api.POST('/api/v2/trailers/ratings/update', { body: { scope: 'movies' } }));
			showToast('Looking up missing certificates', 'success');
		});
	}

	async function testConnection() {
		if (!source) return;
		const source_id = source.id;
		await busyWith('test', 'Could not reach the server', async () => {
			const data = await unwrapLoose<{ ok: boolean; message: string }>(
				api.POST('/api/v2/sync/sources/{source_id}/test', { params: { path: { source_id } } })
			);
			showToast(
				data.message || (data.ok ? 'Connected' : 'Could not connect'),
				data.ok ? 'success' : 'error'
			);
		});
	}

	// Removal asks in a dialog, which can also delete the source's films (else they stay, orphaned).
	let removeOpen = $state(false);
	let removeAlsoMovies = $state(false);
	let removing = $state(false);

	function removeSource() {
		removeAlsoMovies = false;
		removeOpen = !!source;
	}

	async function confirmRemoveSource() {
		if (!source) return;
		const source_id = source.id;
		removing = true;
		await attempt(async () => {
			const res = await unwrapLoose<{ movies_deleted?: number }>(
				api.DELETE('/api/v2/sync/sources/{source_id}', {
					params: { path: { source_id }, query: { delete_movies: removeAlsoMovies } }
				})
			);
			const n = res?.movies_deleted ?? 0;
			showToast(
				removeAlsoMovies && n > 0
					? `Library source removed and ${films(n)} deleted`
					: 'Library source removed',
				'success'
			);
			removeOpen = false;
			void sourceQ.load();
			invalidate('sync');
			if (removeAlsoMovies) invalidate('movies');
		}, 'Could not remove the source');
		removing = false;
	}

	// Deletes every film in the library (any source, orphans too).
	async function clearLibrary() {
		let preview: { total: number; in_use: number };
		try {
			preview = await unwrap(api.GET('/api/v2/movies/clear-library'));
		} catch (e) {
			showToast(errorText(e, 'Could not read the library'), 'error');
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
			`Delete all ${films(preview.total)} from the library?${used} This cannot be undone.`,
			{ confirmLabel: 'Delete all' }
		);
		if (!ok) return;
		await attempt(async () => {
			const data = await unwrap(api.POST('/api/v2/movies/clear-library'));
			showToast(`Deleted ${films(data.deleted)}`, 'success');
			invalidate('movies');
			void sourceQ.load();
		}, 'Could not clear the library');
	}

	// The Sync now caret's menu, and the separate More menu.
	const idle = $derived(busy === '');
	const syncMenuItems = $derived<MenuItem[]>([
		{
			label: 'Full re-scan',
			icon: RotateCw,
			onclick: () => void syncNow(true),
			disabled: running || !idle
		}
	]);
	const moreItems = $derived<MenuItem[]>([
		{
			label: 'Find missing certificates',
			icon: BadgeCheck,
			onclick: () => void findCertificates(),
			disabled: !idle
		}
	]);

	const QUALITY = [
		['720', 'Up to 720p'],
		['1080', 'Up to 1080p'],
		['1440', 'Up to 1440p'],
		['2160', 'Up to 2160p (4K)'],
		['best', 'Best available']
	] as const;

	const typeLabel = $derived(
		types.find((t) => t.type_id === source?.sync_type)?.label ?? source?.sync_type ?? ''
	);

	// The "Server and libraries" row opens the edit form in place, filled from the source.
	let editOpen = $state(false);
	$effect(() => {
		if (editOpen) untrack(openEdit);
		else untrack(() => (formOpen = false));
	});

	let formOpen = $state(false);
	let fType = $state('');
	let fName = $state('');
	let fUrl = $state('');
	let fToken = $state('');
	let fLibs = $state<string[]>([]);
	let saving = $state(false);

	// `available` (from probing the server) is null until a probe runs; `manual` is the typed-names
	// fallback for when it can't be reached.
	let available = $state<string[] | null>(null);
	let probing = $state(false);
	let probeMsg = $state('');
	let manual = $state(false);
	let manualText = $state('');

	const splitLibs = (csv: string) =>
		csv
			.split(',')
			.map((s) => s.trim())
			.filter(Boolean);

	// What the server reported plus anything already chosen, so a saved library it no longer lists
	// never silently drops.
	const libOptions = $derived([...new Set([...(available ?? []), ...fLibs])]);

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

	function serverMissing(): boolean {
		const missing = !fUrl.trim()
			? 'The server URL is required'
			: !source && !fToken.trim()
				? 'An API token is required'
				: '';
		if (missing) showToast(missing, 'error');
		return !!missing;
	}

	async function fetchLibraries() {
		if (serverMissing()) return;
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
			probeMsg = errorText(e, 'Could not reach the server');
		} finally {
			probing = false;
		}
	}

	function openForm(type: string, name: string, url = '', libraries = 'Movies') {
		fType = type;
		fName = name;
		fUrl = url;
		fToken = '';
		resetLibs(libraries);
		formOpen = true;
	}

	const openAdd = (typeId: string) =>
		openForm(typeId, types.find((t) => t.type_id === typeId)?.label ?? typeId);

	function openEdit() {
		if (source) openForm(source.sync_type, source.name, source.url, source.libraries);
	}

	async function save() {
		if (serverMissing()) return;
		const libraries = (manual ? splitLibs(manualText) : fLibs).join(',');
		if (!libraries) {
			showToast('Choose at least one library', 'error');
			return;
		}
		saving = true;
		await attempt(async () => {
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
			editOpen = false;
			void sourceQ.load();
			invalidate('sync');
		}, 'Could not save the source');
		saving = false;
	}
</script>

{#snippet sourceForm()}
	<div class="max-w-2xl space-y-4">
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
			<Button
				onclick={() => {
					formOpen = false;
					editOpen = false;
				}}>Cancel</Button
			>
		</div>
	</div>
{/snippet}

<SettingLists>
	<SettingList
		title="Media server"
		text={source
			? `${films(source.movie_count)} · one server; to switch, remove it and add the other`
			: 'Where your films come from'}
	>
		{#snippet actions()}
			{#if source}
				<div class="inline-flex items-stretch">
					<Button
						size="sm"
						variant="primary"
						class="rounded-r-none"
						disabled={running || busy !== ''}
						onclick={() => void syncNow(false)}
					>
						<RefreshCw size={13} /> Sync now
					</Button>
					<Menu
						size="sm"
						variant="primary"
						caretOnly
						ariaLabel="More sync options"
						class="rounded-l-none border-l border-on-accent/25"
						items={syncMenuItems}
					/>
				</div>
			{/if}
		{/snippet}
		{#if sourceQ.loading}
			<div class="p-4"><Spinner label="Loading the library source…" /></div>
		{:else if sourceQ.error}
			<div class="p-4"><ErrorState error={sourceQ.error} retry={() => void sourceQ.load()} /></div>
		{:else if !source && !formOpen}
			<EmptyState
				icon={Server}
				title="No library source yet"
				message="Cinefin reads your films from one media server. Pick the one you run."
				compact
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
		{:else if !source}
			<div class="p-4">{@render sourceForm()}</div>
		{:else}
			<SettingRow label={source.name} summary="{typeLabel} · {source.url}">
				{#snippet labelSnippet()}
					<StatusLamp colour={source.enabled ? 'green' : 'neutral'}>
						<span class="sr-only">{source.enabled ? 'Syncing' : 'Not syncing'}</span>
					</StatusLamp>
					<span class="font-medium">{source.name}</span>
				{/snippet}
				{#snippet control()}
					{#if !source.enabled}<Badge variant="outline">Disabled</Badge>{/if}
					<Button
						size="sm"
						variant="ghost"
						disabled={busy !== ''}
						onclick={() => void testConnection()}
					>
						<Plug size={13} /> Test
					</Button>
				{/snippet}
			</SettingRow>

			<SettingRow label="Last sync" hint="Reads only what changed">
				{#snippet summarySnippet()}
					{#if running}
						<span class="inline-flex items-center gap-2">
							<ChaseMark height={12} />
							{job?.phase || 'Scanning'}{job?.percentage ? ` · ${Math.round(job.percentage)}%` : ''}
							{#if job?.current_item}<span class="truncate text-faint">{job.current_item}</span
								>{/if}
						</span>
					{:else if job}
						<span class="inline-flex items-center gap-1.5">
							{#if job.state === 'success'}<CheckCircle2 size={13} class="text-success" />
							{:else}<CircleAlert size={13} class="text-danger" />{/if}
							{source.last_sync ? relativeTime(source.last_sync) : 'never'} · {receipt}
						</span>
					{:else}
						<span class="inline-flex items-center gap-1.5"><Clock size={13} /> Never synced</span>
					{/if}
				{/snippet}
				{#snippet control()}
					{#if running}
						<Button size="sm" onclick={() => void cancelRun()}>Stop</Button>
					{:else if changeGroups.length}
						<Button size="sm" variant="ghost" onclick={() => (changesOpen = true)}>
							Changes <ArrowRight size={12} />
						</Button>
					{/if}
					<Menu size="sm" variant="ghost" label="More" align="right" items={moreItems} />
				{/snippet}
			</SettingRow>

			{#if job?.log?.length}
				<SettingRow label="Log" hint="The last run" summary="{job.log.length} lines">
					<pre
						class="max-h-72 overflow-auto bg-surface-2 p-2 font-mono text-xs whitespace-pre-wrap text-muted">{job.log
							.map((entry) => `${entry.level}  ${entry.message}`)
							.join('\n')}</pre>
				</SettingRow>
			{/if}

			<SettingRow
				label="Server and libraries"
				hint="Its address, token and libraries"
				summary={source.libraries || '-'}
				bind:open={editOpen}
			>
				{#if editOpen}{@render sourceForm()}{/if}
			</SettingRow>

			<SettingRow
				label="Remove"
				danger
				hint={source.name}
				summary="Stop using this server, or empty the library"
			>
				{#snippet control()}
					<Button
						size="sm"
						variant="ghost"
						disabled={running || busy !== ''}
						onclick={() => void clearLibrary()}
					>
						Clear library…
					</Button>
					<Button size="sm" variant="danger" disabled={running} onclick={removeSource}>
						<Trash2 size={13} /> Remove
					</Button>
				{/snippet}
			</SettingRow>
		{/if}
	</SettingList>

	<SettingList title="Metadata and trailers" text="From TMDB">
		<SettingRow
			label="TMDB API key"
			hint="Matches films and finds trailers"
			summary={store.trailers.tmdb_api_key.trim() ? (tmdbResult?.message ?? 'Set') : 'Not set'}
		>
			<div class="max-w-xl">
				<Field label="API key" forId="set-tmdb-key" {store} field="trailers.tmdb_api_key">
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
			</div>
		</SettingRow>
		<SettingRow
			label="Trailer quality"
			hint="The most a trailer downloads at"
			summary={QUALITY.find(([v]) => v === store.trailers.download_quality)?.[1] ??
				store.trailers.download_quality}
		>
			<div class="max-w-sm">
				<Field
					label="Download quality"
					forId="set-trailer-quality"
					{store}
					field="trailers.download_quality"
				>
					<Select
						id="set-trailer-quality"
						bind:value={store.trailers.download_quality}
						class="w-full"
					>
						{#each QUALITY as [v, l] (v)}<option value={v}>{l}</option>{/each}
					</Select>
					{#snippet hintSnippet()}
						YouTube trailers often top out at 1080p; a higher setting is only used when a better
						source exists. Up to 1080p trailers come as H.264, which every player can show; above
						that they are VP9 or AV1, which some players cannot.
					{/snippet}
				</Field>
			</div>
		</SettingRow>
	</SettingList>
</SettingLists>

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
					Also delete its {films(source.movie_count)} from the library
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
