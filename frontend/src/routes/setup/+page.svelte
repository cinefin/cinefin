<script lang="ts">
	// First-run setup. Step 1 finalises setup (POST /installer/complete); steps 2-5 use the
	// regular endpoints and resume from the server-kept step after a closed browser.
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import {
		CircleAlert,
		CircleCheck,
		CircleX,
		Film,
		Flag,
		House,
		MonitorSpeaker,
		Plug,
		Ticket
	} from '@lucide/svelte';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { raw } from '$lib/settings/form.svelte';
	import { onInvalidate } from '$lib/invalidate';
	import { unwrapLoose, type ApiJob } from '$lib/jobs';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import AddPlayerWizard from '$lib/playout/AddPlayerWizard.svelte';
	import WizardFrame, { type RailGroup, type WizardAction } from '$lib/wizard/WizardFrame.svelte';
	import { onMount } from 'svelte';

	// The steps, in order: step n is GROUPS[n - 1] (the server keeps the number).
	const GROUPS: Omit<RailGroup, 'done' | 'enabled'>[] = [
		{ id: 'theater', label: 'Your theater', icon: House },
		{ id: 'player', label: 'Player', icon: MonitorSpeaker },
		{ id: 'movies', label: 'Movies', icon: Film },
		{ id: 'tickets', label: 'Tickets', icon: Ticket },
		{ id: 'done', label: 'Done', icon: Flag }
	];

	// null until the status check resolves, so a configured box never flashes the wizard.
	let step = $state<number | null>(null);

	let cinemaName = $state('');
	let ratingsSystem = $state('BBFC');
	let adminUsername = $state('admin');
	let adminPassword = $state('');
	let adminPasswordConfirm = $state('');
	let step1Error = $state('');
	// Once finalised, re-submitting step 1 must not call /complete again (it 400s).
	let finalized = $state(false);
	let completing = $state(false);

	let pairedWith = $state('');
	let step2Loaded = false;

	let saving = $state(false); // shared by the steps that save (3-4)

	let sourceType = $state('');
	let sourceUrl = $state('');
	let sourceToken = $state('');
	let sourceLibraries = $state('Films,Movies');
	let startSync = $state(true);
	const TEST_COLOUR = { ok: 'text-success', error: 'text-danger', pending: 'text-muted' };
	let testResult = $state<{ kind: keyof typeof TEST_COLOUR; message: string } | null>(null);
	let testing = $state(false);
	let step3Error = $state('');

	let ticketRows = $state('10');
	let ticketSeats = $state('20');
	let printerDevice = $state('');
	let step4Loaded = false;
	let step4Error = $state('');

	type CheckState = 'ok' | 'warn' | 'err' | 'pending';
	interface CheckRow {
		state: CheckState;
		sub: string;
		action?: { label: string; href: string };
	}
	const CHECK_COLOUR: Record<CheckState, string> = {
		ok: 'text-success',
		warn: 'text-warning',
		err: 'text-danger',
		pending: 'text-muted'
	};
	const CHECK_ICON = { ok: CircleCheck, warn: CircleAlert, err: CircleX };
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
			// Offline status check: just show the form.
		}

		finalized = configured;
		// Setup done: leave, unless a post-finalise step is in progress.
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

	function goStep(n: number): void {
		step = n;
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
		if (adminPassword && adminPassword !== adminPasswordConfirm) {
			step1Error = 'Passwords do not match';
			return;
		}
		void finishStep1();
	}

	// Creates the account, logs the session in and marks setup done, atomically. Re-visited
	// once finalised, it only saves (the admin password can't be changed here; /complete 400s).
	async function finishStep1() {
		const wasFinal = finalized;
		const cinema = { cinema_name: cinemaName.trim(), ratings_system: ratingsSystem };
		completing = true;
		try {
			if (wasFinal) {
				await mutate(api.POST('/api/v2/settings/', { body: cinema }));
			} else {
				const admin = {
					admin_password: adminPassword,
					admin_username: adminUsername.trim() || 'admin'
				};
				const body = { ...cinema, start_sync: false, ...(adminPassword ? admin : {}) };
				await mutate(api.POST('/api/v2/installer/complete', { body }));
				finalized = true;
			}
			goStep(2);
		} catch (e) {
			const fail = wasFinal ? 'Could not save changes.' : 'Setup failed.';
			step1Error = errorMessage(e, `${fail} Please try again.`);
		} finally {
			completing = false;
		}
	}

	async function loadStep2() {
		step2Loaded = true;
		// The player streams everything from the streaming base URL: an unset one is saved
		// as this browser's address (edited in Settings › Playout).
		try {
			const data = await unwrap(api.GET('/api/v2/settings/'));
			if (!data.settings.playout_server_url) {
				await mutate(
					api.POST('/api/v2/settings/', {
						body: { playout_server_url: window.location.origin }
					})
				);
			}
		} catch {
			/* best effort: Settings › Playout shows it */
		}
	}

	async function testConnection() {
		if (!sourceUrl.trim() || !sourceToken.trim()) {
			testResult = { kind: 'error', message: 'Enter the server URL and token first' };
			return;
		}
		testing = true;
		testResult = { kind: 'pending', message: 'Connecting…' };
		try {
			const data = await raw(
				api.POST('/api/v2/installer/test-connection', {
					body: { sync_type: sourceType, url: sourceUrl.trim(), token: sourceToken.trim() }
				})
			);
			const libs = data.libraries ?? [];
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
			if (sourceType) {
				// The reply is the {success, data: {source}} envelope.
				const created = await unwrapLoose<{ source?: { id?: number } }>(
					api.POST('/api/v2/sync/sources', {
						body: {
							name: sourceType === 'plex' ? 'Plex' : 'Jellyfin',
							sync_type: sourceType,
							url: sourceUrl.trim(),
							token: sourceToken.trim(),
							libraries: sourceLibraries.trim() || 'Films,Movies',
							enabled: true
						}
					})
				);
				const sourceId = created.source?.id;
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

	async function loadStep4() {
		step4Loaded = true;
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

	function startChecklist() {
		if (checklistStop) return;
		void refreshChecklist();
		// The server pings the `setup` key while setup is unfinished.
		checklistStop = onInvalidate('setup', () => void refreshChecklist());
	}

	function stopChecklist() {
		checklistStop?.();
		checklistStop = null;
	}

	async function refreshChecklist() {
		if (checklistBusy) return;
		checklistBusy = true;
		try {
			// Each probe resolves to null on failure so one flaky endpoint can't blank the list.
			const orNull = <T,>(p: Promise<T>) => p.catch(() => null);
			const [mpv, sources, jobs, movies] = await Promise.all([
				orNull(unwrapLoose<{ connected?: boolean }>(api.GET('/api/v2/mpv/status'))),
				orNull(unwrapLoose<{ sources?: { id: number }[] }>(api.GET('/api/v2/sync/sources'))),
				orNull(
					unwrapLoose<{ jobs?: ApiJob[] }>(
						api.GET('/api/v2/sync/jobs', { params: { query: { limit: 10 } } })
					)
				),
				orNull(unwrap(api.GET('/api/v2/movies/list', { params: { query: { per_page: 1 } } })))
			]);

			checks.player = playerCheck(mpv);
			checks.media = mediaCheck(sources, jobs, movies);
		} finally {
			checklistBusy = false;
		}
	}

	const row = (state: CheckState, sub: string, action?: CheckRow['action']): CheckRow => ({
		state,
		sub,
		action
	});

	function playerCheck(mpv: { connected?: boolean } | null): CheckRow {
		if (!mpv) return row('warn', "Couldn't check the player status");
		if (mpv.connected) return row('ok', 'Connected and ready for playout');
		return row('warn', "Not connected - playback won't work until the playout host is up", {
			label: 'Playout settings',
			href: `${base}/settings?tab=playout`
		});
	}

	function mediaCheck(
		sourcesData: { sources?: { id: number }[] } | null,
		jobsData: { jobs?: ApiJob[] } | null,
		moviesData: { pagination?: { total?: number } } | null
	): CheckRow {
		if (!sourcesData) return row('warn', "Couldn't check media sources");
		const library = (label: string) => ({ label, href: `${base}/settings?tab=library` });
		if (!sourcesData.sources?.length)
			return row(
				'warn',
				'No media source configured - add one to sync your movies',
				library('Add source')
			);

		const movies = (n: number) => `${n} ${n === 1 ? 'movie' : 'movies'}`;
		const jobs = jobsData?.jobs ?? [];
		const active = jobs.find((j) => j.is_active);
		if (active)
			return row(
				'pending',
				active.state === 'queued'
					? 'Initial sync queued - waiting to start…'
					: `Syncing your library - ${movies(active.current || 0)} so far…`
			);

		const latest = jobs[0] ?? null;
		if (latest?.state === 'failed')
			return row('err', 'Last sync failed - open the sync panel to retry', library('Open sync'));
		const movieTotal = moviesData?.pagination?.total ?? null;
		if (movieTotal) return row('ok', `Synced - ${movies(movieTotal)} in your library`);
		if (latest)
			return row(
				'warn',
				'Sync finished but found no movies - check the library names',
				library('Open sync')
			);
		return row('warn', 'Source configured - no sync has run yet', library('Run sync'));
	}

	async function finish(): Promise<void> {
		stopChecklist();
		await api.POST('/api/v2/installer/wizard-step', { body: { step: 0 } }).catch(() => {}); // still leave
		void goto(`${base}/`, { replaceState: true });
	}

	// A passed step can be clicked to go back to it once setup is finalised.
	const rail = $derived<RailGroup[]>(
		GROUPS.map((g, i) => ({
			...g,
			done: i + 1 < (step ?? 1),
			enabled: finalized && i + 1 < (step ?? 1)
		}))
	);
	const goGroup = (id: string) => goStep(GROUPS.findIndex((g) => g.id === id) + 1);

	let step1Form = $state<HTMLFormElement>();
	const back = (n: number): WizardAction => ({ label: 'Back', onclick: () => goStep(n) });
	const skip = (n: number): WizardAction => ({ label: 'Skip for now', onclick: () => goStep(n) });
	const saveNext = (save: () => Promise<void>): WizardAction => ({
		label: saving ? 'Saving…' : 'Save and continue',
		disabled: saving,
		onclick: () => void save()
	});
	const frame = $derived.by(() => {
		switch (step) {
			case 1:
				return {
					title: 'Your theater',
					subtitle:
						'A name and an optional password. Continuing finishes setup; the rest can be changed later in Settings.',
					next: {
						label: completing ? 'Setting up…' : 'Continue',
						disabled: completing,
						onclick: () => step1Form?.requestSubmit()
					},
					error: step1Error
				};
			case 2:
				return {
					title: 'Player',
					subtitle: `${pairedWith} is ready. Add more players any time in Settings › Playout.`,
					back: back(1),
					next: { label: 'Continue', onclick: (): void => goStep(3) }
				};
			case 3:
				return {
					title: 'Your movies',
					subtitle: 'Sync a movie library from Jellyfin or Plex. Optional.',
					back: back(2),
					skip: skip(4),
					next: saveNext(saveStep3),
					error: step3Error
				};
			case 4:
				return {
					title: 'Tickets',
					subtitle:
						"Your auditorium's size and the thermal printer, if you will print tickets. Optional.",
					back: back(3),
					skip: skip(5),
					next: saveNext(saveStep4),
					error: step4Error
				};
			default:
				return {
					title: "You're all set",
					subtitle: 'These checks update live. None of them block you.',
					back: back(4),
					next: {
						label: 'Go to dashboard',
						icon: 'home' as const,
						onclick: (): void => void finish()
					}
				};
		}
	});
</script>

{#snippet label(id: string, text: string, optional = false)}
	<label class="mb-1 block text-xs font-medium text-muted" for={id}
		>{text}{#if optional}
			<span class="font-normal text-faint">optional</span>{/if}</label
	>
{/snippet}

<svelte:head>
	<title>Set up Cinefin</title>
</svelte:head>

<div class="fixed inset-0 z-40 flex flex-col overflow-y-auto bg-bg">
	{#if step === null}
		<div class="flex h-full items-center justify-center">
			<Spinner />
		</div>
	{:else}
		<header class="flex h-16 shrink-0 items-center gap-3 border-b border-border px-4 sm:px-6">
			<!-- The mark, warm-up playing: the wizard is the product's first paint, so it
			     gets the ceremony (spec M1). -->
			<svg class="warmup text-text" height="28" viewBox="0 0 36 48" fill="none" aria-hidden="true">
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
			<span class="font-display text-lg text-text">Cinefin</span>
			<span class="text-sm text-faint">Setup</span>
		</header>
		<div class="flex-1">
			{#if step === 2 && !pairedWith}
				<AddPlayerWizard
					rail={{ before: rail.slice(0, 1), after: rail.slice(2), onselect: goGroup }}
					onback={() => goStep(1)}
					onskip={() => goStep(3)}
					onfinish={(host) => {
						pairedWith = host.name;
						goStep(3);
					}}
				/>
			{:else}
				<WizardFrame
					groups={rail}
					group={GROUPS[step - 1].id}
					title={frame.title}
					subtitle={frame.subtitle}
					back={frame.back}
					skip={frame.skip}
					next={frame.next}
					error={frame.error}
					onselect={goGroup}
				>
					{#if step === 1}
						<form class="space-y-6" bind:this={step1Form} onsubmit={submitStep1}>
							<div class="space-y-4">
								<div>
									{@render label('cinema-name', 'Theater name')}
									<Input id="cinema-name" bind:value={cinemaName} placeholder="e.g. The Roxy" />
									<p class="mt-1 text-xs text-faint">
										Shown around the app and printed on tickets.
									</p>
								</div>
								<div>
									{@render label('ratings-system', 'Ratings system')}
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
										{@render label('admin-username', 'Admin username')}
										<Input id="admin-username" bind:value={adminUsername} placeholder="admin" />
									</div>
									<div class="grid gap-4 sm:grid-cols-2">
										<div>
											{@render label('admin-password', 'Password', true)}
											<Input
												id="admin-password"
												type="password"
												bind:value={adminPassword}
												placeholder="Leave blank to skip"
											/>
										</div>
										<div>
											{@render label('admin-password-confirm', 'Confirm password')}
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
						</form>
					{:else if step === 2}
						<p class="flex items-center gap-2 text-sm">
							<CircleCheck class="h-4 w-4 text-success" />
							<span><strong>{pairedWith}</strong> is paired and playing through Cinefin.</span>
						</p>
					{:else if step === 3}
						<div class="space-y-4">
							<div class="grid gap-4 sm:grid-cols-[10rem_1fr]">
								<div>
									{@render label('source-type', 'Server')}
									<Select
										id="source-type"
										bind:value={sourceType}
										onchange={() => (testResult = null)}
										class="w-full"
									>
										<option value="">- None -</option>
										<option value="plex">Plex</option>
										<option value="jellyfin">Jellyfin</option>
									</Select>
								</div>
								<div>
									{@render label('source-url', 'Server URL')}
									<Input
										id="source-url"
										bind:value={sourceUrl}
										placeholder="http://10.0.0.5:32400"
										disabled={!sourceType}
									/>
								</div>
							</div>
							<div>
								{@render label('source-token', 'API token')}
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
									<span class="text-xs {TEST_COLOUR[testResult.kind]}">
										{testResult.message}
									</span>
								{/if}
							</div>
							<div>
								{@render label('source-libraries', 'Libraries')}
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
					{:else if step === 4}
						<div class="space-y-4">
							<div class="grid gap-4 sm:grid-cols-2">
								<div>
									{@render label('set-rows', 'Rows')}
									<Input id="set-rows" type="number" bind:value={ticketRows} />
								</div>
								<div>
									{@render label('set-seats', 'Seats per row')}
									<Input id="set-seats" type="number" bind:value={ticketSeats} />
								</div>
							</div>
							<div>
								{@render label('set-printer-device', 'Printer device')}
								<Input
									id="set-printer-device"
									bind:value={printerDevice}
									placeholder="/dev/usb/lp0"
								/>
							</div>
						</div>
					{:else}
						<ul class="divide-y divide-border" aria-live="polite">
							{#each Object.entries(checks) as [name, row] (name)}
								<li class="flex items-center gap-3 py-3">
									<span
										class="flex h-5 w-5 shrink-0 items-center justify-center {CHECK_COLOUR[
											row.state
										]}"
									>
										{#if row.state !== 'pending'}
											{@const Icon = CHECK_ICON[row.state]}
											<Icon class="h-4.5 w-4.5" />
										{:else}
											<i class="lamp-pending h-2 w-2 bg-faint" aria-hidden="true"></i>
										{/if}
									</span>
									<span class="min-w-0 flex-1">
										<span class="block text-sm font-medium text-text">{CHECK_TITLES[name]}</span>
										<span class="block text-xs text-muted">{row.sub}</span>
									</span>
									{#if row.action}
										<a class="shrink-0 text-xs text-accent hover:underline" href={row.action.href}>
											{row.action.label}
										</a>
									{/if}
								</li>
							{/each}
						</ul>
					{/if}
				</WizardFrame>
			{/if}
		</div>
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
	}
	/* No `to` frames: they default to the element's own (opaque, untransformed) style. */
	@keyframes warm-strike {
		from {
			opacity: 0;
			transform: translateY(4px) scaleY(0.72);
		}
	}
	@keyframes frame-in {
		from {
			opacity: 0;
		}
	}
</style>
