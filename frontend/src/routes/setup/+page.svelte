<script lang="ts">
	// First-run setup wizard. Setup is finalised at the end of step 1 (POST
	// /installer/complete); steps 2-5 hit the regular settings/playout/sync
	// endpoints, which the installer-redirect middleware only allows once setup
	// is complete. The step reached is persisted server-side so closing the
	// browser resumes at steps 2-5.
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import {
		ArrowLeft,
		ArrowRight,
		Check,
		CircleAlert,
		CircleCheck,
		CircleX,
		House,
		Plug
	} from '@lucide/svelte';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { onInvalidate } from '$lib/invalidate';
	import { unwrapLoose } from '$lib/jobs';
	import type { ApiJob } from '$lib/jobs';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { onMount } from 'svelte';

	const STEP_META: Record<number, { title: string; subtitle: string }> = {
		1: {
			title: 'Set up your theater',
			subtitle:
				'A name and an optional password. Continuing finishes setup, and the rest can be changed later in Settings.'
		},
		2: {
			title: 'Connect the player',
			subtitle:
				'Cinefin plays your programmes through a playout agent on the machine at your screen. Add it now or skip and do it later.'
		},
		3: {
			title: 'Your movies',
			subtitle: 'Sync a movie library from Jellyfin or Plex'
		},
		4: {
			title: 'Tickets',
			subtitle: 'Auditorium size and ticket printing. Optional'
		},
		5: {
			title: "You're all set",
			subtitle: 'A quick check of how everything is looking.'
		}
	};
	const STEP_LABELS = ['Your theater', 'Playback', 'Your movies', 'Tickets', 'Done'];

	// null until the status check resolves — nothing renders before that, so a
	// configured box never flashes the wizard on its way to the dashboard.
	let step = $state<number | null>(null);

	let cinemaName = $state('');
	let ratingsSystem = $state('BBFC');
	let adminUsername = $state('admin');
	let adminPassword = $state('');
	let adminPasswordConfirm = $state('');
	let step1Error = $state('');
	// True once setup is finalised (POST /installer/complete). Re-submitting
	// step 1 after that must NOT call /complete again (it 400s) — persist the
	// editable fields via /settings and move on.
	let finalized = $state(false);

	let completing = $state(false); // step 1 finalise (POST /installer/complete)

	let hostName = $state('');
	let hostUrl = $state('');
	let hostToken = $state('');
	let serverUrl = $state('');
	let step2Loaded = false;
	let step2Error = $state('');

	let saving = $state(false); // shared by the steps that save (2-4)

	let sourceType = $state('');
	let sourceUrl = $state('');
	let sourceToken = $state('');
	let sourceLibraries = $state('Films,Movies');
	let startSync = $state(true);
	let testResult = $state<{ kind: 'pending' | 'ok' | 'error'; message: string } | null>(null);
	let testing = $state(false);
	let step3Error = $state('');

	let ticketRows = $state('10');
	let ticketSeats = $state('20');
	let printerDevice = $state('');
	let step4Loaded = false;
	let step4Error = $state('');

	type CheckState = 'ok' | 'warn' | 'err' | 'pending';
	interface CheckAction {
		label: string;
		href?: string;
		step?: number;
	}
	interface CheckRow {
		state: CheckState;
		sub: string;
		action?: CheckAction;
	}
	const CHECK_TITLES: Record<string, string> = {
		player: 'Player',
		media: 'Media library'
	};
	let checks = $state<Record<string, CheckRow>>({
		player: { state: 'pending', sub: 'Checking…' },
		media: { state: 'pending', sub: 'Checking…' }
	});
	let checklistStop: (() => void) | null = null;
	let checklistBusy = false;

	onMount(() => {
		void init();
		return () => stopChecklist();
	});

	async function init() {
		let configured = false;
		let wizardStep = 0;
		try {
			const { data } = await api.GET('/api/v2/installer/status');
			configured = !!data?.configured;
			wizardStep = data?.wizard_step || 0;
		} catch {
			// Offline status check — just show the form.
		}

		finalized = configured;
		// Setup already done: normally leave, but honour an in-progress
		// post-finalise step so a reload/closed browser doesn't lose it.
		if (configured) {
			if (wizardStep >= 2 && wizardStep <= 5) {
				goStep(wizardStep);
				return;
			}
			void goto(`${base}/`, { replaceState: true });
			return;
		}
		step = 1;
	}

	function goStep(n: number) {
		step = n;
		// Steps 2-4 are post-finalise: remember where we are server-side
		// (best-effort).
		if (n >= 2)
			void api.POST('/api/v2/installer/wizard-step', { body: { step: n } }).catch(() => {});
		if (n === 2 && !step2Loaded) void loadStep2();
		if (n === 4 && !step4Loaded) void loadStep4();
		if (n === 5) startChecklist();
		else stopChecklist();
		window.scrollTo(0, 0);
	}

	/** User-facing message for a failed API call (server envelope → fallback). */
	function errorMessage(e: unknown, fallback: string): string {
		const err = toApiError(e);
		return err.message && !err.message.startsWith('Request failed') ? err.message : fallback;
	}

	function submitStep1(e: SubmitEvent) {
		e.preventDefault();
		step1Error = '';
		if (!cinemaName.trim()) {
			step1Error = 'Please enter a theater name';
			return;
		}
		// Optional admin password — blank leaves auth off.
		if (adminPassword && adminPassword !== adminPasswordConfirm) {
			step1Error = 'Passwords do not match';
			return;
		}
		// Already finalised (came Back to step 1)? /complete would 400 — just
		// persist the editable fields and continue.
		void (finalized ? saveStep1AndContinue() : finalizeSetup());
	}

	// Re-visited step 1: name/ratings go through the regular settings endpoint
	// (the session is authenticated post-finalise); the admin password can't be
	// changed here.
	async function saveStep1AndContinue() {
		step1Error = '';
		completing = true;
		try {
			await mutate(
				api.POST('/api/v2/settings/', {
					body: {
						cinema_name: cinemaName.trim(),
						ratings_system: ratingsSystem
					}
				})
			);
			goStep(2);
		} catch (e) {
			step1Error = errorMessage(e, 'Could not save changes. Please try again.');
		} finally {
			completing = false;
		}
	}

	// End of step 1: one atomic POST /installer/complete that creates the
	// account, logs the session in, and marks setup done.
	async function finalizeSetup() {
		step1Error = '';
		const name = cinemaName.trim();
		const body: {
			cinema_name: string;
			ratings_system: string;
			admin_username?: string;
			admin_password?: string;
			start_sync: boolean;
		} = {
			cinema_name: name,
			ratings_system: ratingsSystem,
			start_sync: false
		};
		if (adminPassword) {
			body.admin_password = adminPassword;
			body.admin_username = adminUsername.trim() || 'admin';
		}

		completing = true;
		try {
			const result = await api.POST('/api/v2/installer/complete', { body });
			if (result.error !== undefined || !result.data)
				throw toApiError(result.error, result.response);
			finalized = true;
			goStep(2);
		} catch (e) {
			step1Error = errorMessage(e, 'Setup failed. Please try again.');
		} finally {
			completing = false;
		}
	}

	async function loadStep2() {
		step2Loaded = true;
		// Prefill the streaming base URL from the saved value, else this origin.
		try {
			const data = await unwrap(api.GET('/api/v2/settings/'));
			serverUrl = data.settings.playout_server_url || window.location.origin;
		} catch {
			serverUrl = serverUrl || window.location.origin;
		}
	}

	async function saveStep2() {
		step2Error = '';
		saving = true;
		try {
			await mutate(
				api.POST('/api/v2/settings/', { body: { playout_server_url: serverUrl.trim() } })
			);
			// The first host is auto-activated. Skipped cleanly when left blank.
			if (hostName.trim() && hostUrl.trim()) {
				const result = await api.POST('/api/v2/playout/hosts', {
					body: {
						name: hostName.trim(),
						base_url: hostUrl.trim(),
						token: hostToken.trim() || undefined
					}
				});
				if (result.error !== undefined) throw toApiError(result.error, result.response);
			}
			goStep(3);
		} catch (e) {
			step2Error = errorMessage(e, 'Could not save. Please try again.');
		} finally {
			saving = false;
		}
	}

	function onSourceTypeChange() {
		testResult = null;
	}

	async function testConnection() {
		if (!sourceUrl.trim() || !sourceToken.trim()) {
			testResult = { kind: 'error', message: 'Enter the server URL and token first' };
			return;
		}
		testing = true;
		testResult = { kind: 'pending', message: 'Connecting…' };
		try {
			const result = await api.POST('/api/v2/installer/test-connection', {
				body: { sync_type: sourceType, url: sourceUrl.trim(), token: sourceToken.trim() }
			});
			if (result.error !== undefined || !result.data)
				throw toApiError(result.error, result.response);
			const libs = result.data.libraries ?? [];
			if (libs.length) sourceLibraries = libs.join(',');
			testResult = {
				kind: 'ok',
				message: `Connected - ${libs.length} ${libs.length === 1 ? 'library' : 'libraries'} found`
			};
		} catch (e) {
			testResult = { kind: 'error', message: errorMessage(e, 'Connection failed') };
		} finally {
			testing = false;
		}
	}

	function intOr(v: string, fallback: number): number {
		const n = parseInt(v, 10);
		return Number.isNaN(n) ? fallback : n;
	}

	async function saveStep3() {
		step3Error = '';
		if (sourceType && (!sourceUrl.trim() || !sourceToken.trim())) {
			step3Error = 'Enter the media server URL and token, or set Server to “None”.';
			return;
		}
		saving = true;
		try {
			// Add a media source as a regular sync source and kick off the first
			// sync if asked. Skipped cleanly when no server was chosen.
			if (sourceType) {
				const created = (await api.POST('/api/v2/sync/sources', {
					body: {
						name: sourceType === 'plex' ? 'Plex' : 'Jellyfin',
						sync_type: sourceType,
						url: sourceUrl.trim(),
						token: sourceToken.trim(),
						libraries: sourceLibraries.trim() || 'Films,Movies',
						enabled: true
					}
				})) as unknown as {
					error?: unknown;
					response: Response;
					data?: { source?: { id?: number } };
				};
				if (created.error !== undefined) throw toApiError(created.error, created.response);
				const sourceId = created.data?.source?.id;
				if (startSync && sourceId != null) {
					await api.POST('/api/v2/sync/sources/{source_id}/runs', {
						params: { path: { source_id: sourceId } },
						body: { max_attempts: 1 }
					});
				}
			}
			goStep(4);
		} catch (e) {
			step3Error = errorMessage(e, 'Could not save. Please try again.');
		} finally {
			saving = false;
		}
	}

	// ---- step 4: tickets ------------------------------------------------------

	async function loadStep4() {
		step4Loaded = true;

		// Ticket settings live in general settings.
		try {
			const data = await unwrap(api.GET('/api/v2/settings/'));
			const g = data.settings;
			ticketRows = String(g.ticket_total_rows ?? 10);
			ticketSeats = String(g.ticket_seats_per_row ?? 20);
			printerDevice = g.ticket_printer_device ?? '';
		} catch {
			/* leave placeholders */
		}
	}

	async function saveStep4() {
		step4Error = '';
		saving = true;
		try {
			await mutate(
				api.POST('/api/v2/settings/', {
					body: {
						ticket_total_rows: intOr(ticketRows, 10),
						ticket_seats_per_row: intOr(ticketSeats, 20),
						ticket_printer_device: printerDevice.trim()
					}
				})
			);
			goStep(5);
		} catch (e) {
			step4Error = errorMessage(e, 'Could not save settings. Please try again.');
		} finally {
			saving = false;
		}
	}

	// ---- step 5: readiness checklist actions ----------------------------------

	function startChecklist() {
		if (checklistStop) return;
		void refreshChecklist();
		// The server pings the `setup` key on the real-time channel while setup is
		// unfinished; re-probe on that instead of a local interval.
		checklistStop = onInvalidate('setup', () => void refreshChecklist());
	}

	function stopChecklist() {
		checklistStop?.();
		checklistStop = null;
	}

	function setCheck(name: string, state: CheckState, sub: string, action?: CheckAction) {
		checks[name] = { state, sub, action };
	}

	async function refreshChecklist() {
		if (checklistBusy) return;
		checklistBusy = true;
		try {
			// Each probe resolves to null on failure so one flaky endpoint
			// doesn't blank the whole checklist.
			const [mpv, sources, jobs, movies] = await Promise.all([
				unwrapLoose<{ connected?: boolean }>(api.GET('/api/v2/mpv/status')).catch(() => null),
				unwrapLoose<{ sources?: { id: number }[] }>(api.GET('/api/v2/sync/sources')).catch(
					() => null
				),
				unwrapLoose<{ jobs?: ApiJob[] }>(
					api.GET('/api/v2/sync/jobs', { params: { query: { limit: 10 } } })
				).catch(() => null),
				unwrap(api.GET('/api/v2/movies/list', { params: { query: { per_page: 1 } } })).catch(
					() => null
				)
			]);

			renderPlayerCheck(mpv);
			renderMediaCheck(sources, jobs, movies);
		} finally {
			checklistBusy = false;
		}
	}

	function renderPlayerCheck(mpv: { connected?: boolean } | null) {
		if (!mpv) {
			setCheck('player', 'warn', "Couldn't check the player status");
		} else if (mpv.connected) {
			setCheck('player', 'ok', 'Connected and ready for playout');
		} else {
			setCheck(
				'player',
				'warn',
				"Not connected - playback won't work until the playout host is up",
				{
					label: 'Settings',
					href: `${base}/settings`
				}
			);
		}
	}

	function renderMediaCheck(
		sourcesData: { sources?: { id: number }[] } | null,
		jobsData: { jobs?: ApiJob[] } | null,
		moviesData: { pagination?: { total?: number } } | null
	) {
		if (!sourcesData) {
			setCheck('media', 'warn', "Couldn't check media sources");
			return;
		}
		const sources = sourcesData.sources ?? [];
		if (!sources.length) {
			setCheck('media', 'warn', 'No media source configured - add one to sync your movies', {
				label: 'Add source',
				href: `${base}/settings?tab=library`
			});
			return;
		}

		const movies = (n: number) => `${n} ${n === 1 ? 'movie' : 'movies'}`;
		const jobs = jobsData?.jobs ?? [];
		const active = jobs.find((j) => j.is_active);
		if (active) {
			if (active.state === 'queued') {
				setCheck('media', 'pending', 'Initial sync queued - waiting to start…');
			} else {
				setCheck(
					'media',
					'pending',
					`Syncing your library - ${movies(active.current || 0)} so far…`
				);
			}
			return;
		}

		const latest = jobs[0] ?? null;
		if (latest && latest.state === 'failed') {
			setCheck('media', 'err', 'Last sync failed - open the sync panel to retry', {
				label: 'Open sync',
				href: `${base}/settings?tab=library`
			});
			return;
		}

		const movieTotal = moviesData?.pagination?.total ?? null;
		if (movieTotal) {
			setCheck('media', 'ok', `Synced - ${movies(movieTotal)} in your library`);
		} else if (latest) {
			setCheck('media', 'warn', 'Sync finished but found no movies - check the library names', {
				label: 'Open sync',
				href: `${base}/settings?tab=library`
			});
		} else {
			setCheck('media', 'warn', 'Source configured - no sync has run yet', {
				label: 'Run sync',
				href: `${base}/settings?tab=library`
			});
		}
	}

	async function finish() {
		stopChecklist();
		try {
			await api.POST('/api/v2/installer/wizard-step', { body: { step: 0 } });
		} catch {
			/* still leave */
		}
		void goto(`${base}/`, { replaceState: true });
	}
</script>

<svelte:head>
	<title>Set up Cinefin</title>
</svelte:head>

<div class="fixed inset-0 z-40 overflow-y-auto bg-bg">
	{#if step === null}
		<div class="flex h-full items-center justify-center">
			<Spinner />
		</div>
	{:else}
		<main class="mx-auto w-full max-w-2xl px-4 py-10">
			<header class="mb-8 text-center">
				<!-- The mark at 2× its grid (56px), warm-up playing — the wizard is
				     the product's first paint, so it gets the ceremony (spec M1). -->
				<svg
					class="warmup mx-auto mb-4 text-text"
					height="56"
					viewBox="0 0 36 48"
					fill="none"
					aria-hidden="true"
				>
					<path
						class="fr"
						fill-rule="evenodd"
						clip-rule="evenodd"
						d="M0 0h36v48H0V0Zm3 3h30v42H3V3Z"
						fill="currentColor"
					/>
					<g class="perf" fill="currentColor">
						<rect x="6" y="6" width="4" height="6" /><rect x="6" y="16" width="4" height="6" />
						<rect x="6" y="26" width="4" height="6" /><rect x="6" y="36" width="4" height="6" />
						<rect x="26" y="6" width="4" height="6" /><rect x="26" y="16" width="4" height="6" />
						<rect x="26" y="26" width="4" height="6" /><rect x="26" y="36" width="4" height="6" />
					</g>
					<rect class="ch ch-r" x="13" y="6" width="10" height="10" fill="#FF2F4D" />
					<rect class="ch ch-g" x="13" y="19" width="10" height="10" fill="#25E88A" />
					<rect class="ch ch-b" x="13" y="32" width="10" height="10" fill="#3A7BFF" />
				</svg>
				<h1 class="text-xl font-semibold text-text">{STEP_META[step].title}</h1>
				<p class="mx-auto mt-1.5 max-w-md text-sm text-muted">{STEP_META[step].subtitle}</p>
				<ol class="mt-5 flex items-center justify-center gap-2" aria-hidden="true">
					{#each STEP_LABELS as label, i (label)}
						{@const n = i + 1}
						<li
							class="flex items-center gap-1.5 text-xs
								{n === step ? 'text-text' : n < step ? 'text-accent' : 'text-faint'}"
						>
							<span
								class="flex h-5 w-5 items-center justify-center rounded-sm border text-[0.65rem]
									{n === step
									? 'border-accent bg-accent text-on-accent'
									: n < step
										? 'border-accent text-accent'
										: 'border-border-strong'}"
							>
								{#if n < step}<Check class="h-3 w-3" />{:else}{n}{/if}
							</span>
							{label}
						</li>
					{/each}
				</ol>
			</header>

			{#if step === 1}
				<form class="space-y-4" onsubmit={submitStep1}>
					<section class="border border-border bg-surface-1 p-4">
						<div class="mb-4">
							<h2 class="text-sm font-semibold text-text">Your theater</h2>
							<p class="mt-0.5 text-xs text-muted">A name. Everything else is optional.</p>
						</div>
						<div class="space-y-4">
							<div>
								<label class="mb-1 block text-xs font-medium text-muted" for="cinema-name"
									>Theater name</label
								>
								<Input id="cinema-name" bind:value={cinemaName} placeholder="e.g. The Roxy" />
								<p class="mt-1 text-xs text-faint">Shown around the app and printed on tickets.</p>
							</div>
							<div>
								<label class="mb-1 block text-xs font-medium text-muted" for="ratings-system"
									>Ratings system</label
								>
								<Select id="ratings-system" bind:value={ratingsSystem} class="w-full">
									<option value="BBFC">BBFC (British - U, PG, 12, 12A, 15, 18, R18)</option>
									<option value="MPAA">MPAA (US - G, PG, PG-13, R, NC-17)</option>
								</Select>
								<p class="mt-1 text-xs text-faint">
									How age ratings are displayed and matched. Movies and trailers are classified
									using this system.
								</p>
							</div>
						</div>
					</section>

					<section class="border border-border bg-surface-1 p-4">
						<div class="mb-4">
							<h2 class="text-sm font-semibold text-text">
								Secure your install
								<span class="ml-1 text-xs font-normal text-accent">recommended</span>
							</h2>
							<p class="mt-0.5 text-xs text-muted">
								Set a password to require a login before anyone can control the theater, run
								commands, or restore backups. Leave blank to run without one.
							</p>
						</div>
						<div class="space-y-4">
							<div>
								<label class="mb-1 block text-xs font-medium text-muted" for="admin-username"
									>Admin username</label
								>
								<Input id="admin-username" bind:value={adminUsername} placeholder="admin" />
							</div>
							<div class="grid gap-4 sm:grid-cols-2">
								<div>
									<label class="mb-1 block text-xs font-medium text-muted" for="admin-password"
										>Password <span class="font-normal text-faint">optional</span></label
									>
									<Input
										id="admin-password"
										type="password"
										bind:value={adminPassword}
										placeholder="Leave blank to skip"
									/>
								</div>
								<div>
									<label
										class="mb-1 block text-xs font-medium text-muted"
										for="admin-password-confirm">Confirm password</label
									>
									<Input
										id="admin-password-confirm"
										type="password"
										bind:value={adminPasswordConfirm}
										placeholder="Repeat password"
									/>
								</div>
							</div>
							<p class="text-xs text-faint">
								Any password you like - this is a single-user home system.
							</p>
						</div>
					</section>

					{#if step1Error}
						<div class="border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
							{step1Error}
						</div>
					{/if}

					<div class="flex justify-end">
						<Button type="submit" variant="primary" disabled={completing}>
							{completing ? 'Setting up…' : 'Continue'}
							<ArrowRight class="h-3.5 w-3.5" />
						</Button>
					</div>
				</form>
			{:else if step === 2}
				<div class="space-y-4">
					<section class="border border-border bg-surface-1 p-4">
						<div class="mb-4">
							<h2 class="text-sm font-semibold text-text">Playout host</h2>
							<p class="mt-0.5 text-xs text-muted">
								Cinefin plays through the playout agent on the machine at your screen. Run the
								agent, then copy its address and token from the tray icon and paste them here.
							</p>
						</div>
						<div class="space-y-4">
							<div class="grid gap-4 sm:grid-cols-2">
								<div>
									<label class="mb-1 block text-xs font-medium text-muted" for="set-host-name"
										>Name</label
									>
									<Input id="set-host-name" bind:value={hostName} placeholder="Booth PC" />
								</div>
								<div>
									<label class="mb-1 block text-xs font-medium text-muted" for="set-host-url"
										>Agent address</label
									>
									<Input
										id="set-host-url"
										bind:value={hostUrl}
										placeholder="http://127.0.0.1:8089"
									/>
								</div>
							</div>
							<div>
								<label class="mb-1 block text-xs font-medium text-muted" for="set-host-token"
									>Agent token</label
								>
								<Input
									id="set-host-token"
									type="password"
									bind:value={hostToken}
									placeholder="paste from the agent's tray icon"
								/>
								<p class="mt-1 text-xs text-faint">
									Leave the name and address blank to skip. Add the host later.
								</p>
							</div>
							<div>
								<label class="mb-1 block text-xs font-medium text-muted" for="set-server-url"
									>Streaming base URL</label
								>
								<Input
									id="set-server-url"
									bind:value={serverUrl}
									placeholder="http://cinema.local:8000"
								/>
								<p class="mt-1 text-xs text-faint">
									The player streams idents, movies, trailers and custom media from Cinefin at this
									URL, so the playout machine must be able to reach it. Prefilled with this
									browser's address. Change it if the machine sees Cinefin differently. Blank uses
									the server default.
								</p>
							</div>
						</div>
					</section>

					{#if step2Error}
						<div class="border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
							{step2Error}
						</div>
					{/if}

					<div class="flex items-center justify-between">
						<Button variant="ghost" onclick={() => goStep(1)}>
							<ArrowLeft class="h-3.5 w-3.5" /> Back
						</Button>
						<div class="flex items-center gap-2">
							<Button variant="ghost" onclick={() => goStep(3)}>Skip for now</Button>
							<Button variant="primary" disabled={saving} onclick={saveStep2}>
								{saving ? 'Saving…' : 'Save & continue'}
								<ArrowRight class="h-3.5 w-3.5" />
							</Button>
						</div>
					</div>
				</div>
			{:else if step === 3}
				<div class="space-y-4">
					<section class="border border-border bg-surface-1 p-4">
						<div class="mb-4">
							<h2 class="text-sm font-semibold text-text">
								Media library <span class="ml-1 text-xs font-normal text-faint">optional</span>
							</h2>
							<p class="mt-0.5 text-xs text-muted">
								Connect a Jellyfin or Plex server to sync your movies. Optional
							</p>
						</div>
						<div class="space-y-4">
							<div class="grid gap-4 sm:grid-cols-[10rem_1fr]">
								<div>
									<label class="mb-1 block text-xs font-medium text-muted" for="source-type"
										>Server</label
									>
									<Select
										id="source-type"
										bind:value={sourceType}
										onchange={onSourceTypeChange}
										class="w-full"
									>
										<option value="">- None -</option>
										<option value="plex">Plex</option>
										<option value="jellyfin">Jellyfin</option>
									</Select>
								</div>
								<div>
									<label class="mb-1 block text-xs font-medium text-muted" for="source-url"
										>Server URL</label
									>
									<Input
										id="source-url"
										bind:value={sourceUrl}
										placeholder="http://10.0.0.5:32400"
										disabled={!sourceType}
									/>
								</div>
							</div>
							<div>
								<label class="mb-1 block text-xs font-medium text-muted" for="source-token"
									>API token</label
								>
								<Input
									id="source-token"
									bind:value={sourceToken}
									placeholder="X-Plex-Token / Jellyfin API key"
									disabled={!sourceType}
								/>
							</div>
							<div class="flex items-center gap-3">
								<Button disabled={!sourceType || testing} onclick={testConnection}>
									<Plug class="h-3.5 w-3.5" /> Test connection
								</Button>
								{#if testResult}
									<span
										class="text-xs
											{testResult.kind === 'ok'
											? 'text-success'
											: testResult.kind === 'error'
												? 'text-danger'
												: 'text-muted'}"
									>
										{testResult.message}
									</span>
								{/if}
							</div>
							<div>
								<label class="mb-1 block text-xs font-medium text-muted" for="source-libraries"
									>Libraries</label
								>
								<Input
									id="source-libraries"
									bind:value={sourceLibraries}
									placeholder="Comma-separated library names"
									disabled={!sourceType}
								/>
								<p class="mt-1 text-xs text-faint">
									Which libraries to sync. A successful test fills this in for you.
								</p>
							</div>
							<label
								class="flex items-center gap-2 text-sm {sourceType ? 'text-text' : 'text-faint'}"
							>
								<input
									type="checkbox"
									bind:checked={startSync}
									disabled={!sourceType}
									class="accent-accent"
								/>
								Start syncing movies now
							</label>
						</div>
					</section>

					{#if step3Error}
						<div class="border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
							{step3Error}
						</div>
					{/if}

					<div class="flex items-center justify-between">
						<Button variant="ghost" onclick={() => goStep(2)}>
							<ArrowLeft class="h-3.5 w-3.5" /> Back
						</Button>
						<div class="flex items-center gap-2">
							<Button variant="ghost" onclick={() => goStep(4)}>Skip for now</Button>
							<Button variant="primary" disabled={saving} onclick={saveStep3}>
								{saving ? 'Saving…' : 'Save & continue'}
								<ArrowRight class="h-3.5 w-3.5" />
							</Button>
						</div>
					</div>
				</div>
			{:else if step === 4}
				<div class="space-y-4">
					<section class="border border-border bg-surface-1 p-4">
						<div class="mb-4">
							<h2 class="text-sm font-semibold text-text">
								Ticket printer <span class="ml-1 text-xs font-normal text-faint">optional</span>
							</h2>
							<p class="mt-0.5 text-xs text-muted">
								Set your auditorium size and thermal printer device if you'll be printing tickets.
							</p>
						</div>
						<div class="space-y-4">
							<div class="grid gap-4 sm:grid-cols-2">
								<div>
									<label class="mb-1 block text-xs font-medium text-muted" for="set-rows"
										>Rows</label
									>
									<Input id="set-rows" type="number" bind:value={ticketRows} />
								</div>
								<div>
									<label class="mb-1 block text-xs font-medium text-muted" for="set-seats"
										>Seats per row</label
									>
									<Input id="set-seats" type="number" bind:value={ticketSeats} />
								</div>
							</div>
							<div>
								<label class="mb-1 block text-xs font-medium text-muted" for="set-printer-device"
									>Printer device</label
								>
								<Input
									id="set-printer-device"
									bind:value={printerDevice}
									placeholder="/dev/usb/lp0"
								/>
							</div>
						</div>
					</section>

					{#if step4Error}
						<div class="border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
							{step4Error}
						</div>
					{/if}

					<div class="flex items-center justify-between">
						<Button variant="ghost" onclick={() => goStep(3)}>
							<ArrowLeft class="h-3.5 w-3.5" /> Back
						</Button>
						<div class="flex items-center gap-2">
							<Button variant="ghost" onclick={() => goStep(5)}>Skip for now</Button>
							<Button variant="primary" disabled={saving} onclick={saveStep4}>
								{saving ? 'Saving…' : 'Save & continue'}
								<ArrowRight class="h-3.5 w-3.5" />
							</Button>
						</div>
					</div>
				</div>
			{:else if step === 5}
				<div class="space-y-4">
					<section class="border border-border bg-surface-1 p-4">
						<div class="mb-4">
							<h2 class="text-sm font-semibold text-text">You're all set</h2>
							<p class="mt-0.5 text-xs text-muted">
								These checks update live. None of them block you.
							</p>
						</div>
						<ul class="divide-y divide-border" aria-live="polite">
							{#each Object.entries(checks) as [name, row] (name)}
								<li class="flex items-center gap-3 py-3">
									<span
										class="flex h-5 w-5 shrink-0 items-center justify-center
											{row.state === 'ok'
											? 'text-success'
											: row.state === 'warn'
												? 'text-warning'
												: row.state === 'err'
													? 'text-danger'
													: 'text-muted'}"
									>
										{#if row.state === 'ok'}
											<CircleCheck class="h-4.5 w-4.5" />
										{:else if row.state === 'warn'}
											<CircleAlert class="h-4.5 w-4.5" />
										{:else if row.state === 'err'}
											<CircleX class="h-4.5 w-4.5" />
										{:else}
											<i class="lamp-pending h-2 w-2 bg-faint" aria-hidden="true"></i>
										{/if}
									</span>
									<span class="min-w-0 flex-1">
										<span class="block text-sm font-medium text-text">{CHECK_TITLES[name]}</span>
										<span class="block text-xs text-muted">{row.sub}</span>
									</span>
									{#if row.action}
										{#if row.action.step}
											<button
												type="button"
												class="shrink-0 text-xs text-accent hover:underline"
												onclick={() => goStep(row.action!.step!)}
											>
												{row.action.label}
											</button>
										{:else}
											<a
												class="shrink-0 text-xs text-accent hover:underline"
												href={row.action.href}
											>
												{row.action.label}
											</a>
										{/if}
									{/if}
								</li>
							{/each}
						</ul>
					</section>

					<div class="flex items-center justify-between">
						<Button variant="ghost" onclick={() => goStep(4)}>
							<ArrowLeft class="h-3.5 w-3.5" /> Back
						</Button>
						<Button variant="primary" onclick={finish}>
							<House class="h-3.5 w-3.5" /> Go to dashboard
						</Button>
					</div>
				</div>
			{/if}
		</main>
	{/if}
</div>

<style>
	/* The guide's warm-up, verbatim (spec M1). */
	@media (prefers-reduced-motion: no-preference) {
		.warmup .fr {
			animation: frame-in 0.5s cubic-bezier(0.22, 0.61, 0.36, 1) both;
		}
		.warmup .ch {
			transform-origin: center;
			animation: warm-strike 0.55s cubic-bezier(0.22, 0.61, 0.36, 1) both;
		}
		.warmup .ch-r {
			animation-delay: 0.2s;
		}
		.warmup .ch-g {
			animation-delay: 0.33s;
		}
		.warmup .ch-b {
			animation-delay: 0.46s;
		}
		.warmup .perf {
			animation: frame-in 0.4s cubic-bezier(0.22, 0.61, 0.36, 1) 0.6s both;
		}
		.lamp-pending {
			animation: lamp-pulse 1.6s cubic-bezier(0.22, 0.61, 0.36, 1) infinite;
		}
	}
	@keyframes warm-strike {
		from {
			opacity: 0;
			transform: translateY(4px) scaleY(0.72);
		}
		to {
			opacity: 1;
			transform: none;
		}
	}
	@keyframes frame-in {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}
	@keyframes lamp-pulse {
		50% {
			opacity: 0.3;
		}
	}
</style>
