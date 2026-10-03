<script lang="ts">
	import { fade } from 'svelte/transition';
	import {
		Check,
		CircleCheck,
		MonitorPlay,
		Pencil,
		Play,
		Plus,
		RefreshCw,
		RotateCcw,
		RotateCw,
		Square,
		Trash2
	} from '@lucide/svelte';
	import { base } from '$app/paths';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { query } from '$lib/api/query.svelte';
	import { onInvalidate } from '$lib/invalidate';
	import { unwrapLoose } from '$lib/jobs';
	import { showToast } from '$lib/toast.svelte';
	import { playout } from '$lib/stores/playout.svelte';
	import { itemTypeLabel } from '$lib/item-types';
	import { type SettingsStore } from '$lib/settings/form.svelte';
	import type { CheckState } from '$lib/settings/types';
	import type { PlayoutStatus } from '$lib/api/refinements';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import PlayerPairing from '$lib/components/PlayerPairing.svelte';
	import CheckResult from './CheckResult.svelte';
	import Field from './Field.svelte';
	import HostConfigPanel from './HostConfigPanel.svelte';
	import Toggle from '$lib/components/ui/Toggle.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	interface Props {
		store: SettingsStore;
		confirm: ConfirmDialog['confirm'];
	}
	let { store, confirm }: Props = $props();

	// Players: each paired machine and its own screen and sound. Presentation:
	// what every player shows (idle ident, subtitles) and where it streams from.
	const TABS = [
		{ id: 'players', label: 'Players' },
		{ id: 'presentation', label: 'Presentation' }
	];
	let tab = $state('players');

	const hosts = query(() => unwrap(api.GET('/api/v2/playout/hosts')));
	const activeHost = $derived(hosts.data?.find((h) => h.is_active) ?? null);
	const isAgent = $derived(activeHost?.kind !== 'local_socket');

	// Live "what's on the player right now", from the shared playout feed.
	$effect(() => playout.subscribe());
	const liveProg = $derived(playout.status?.programme ?? null);
	const idle = $derived(
		!liveProg || liveProg.state === 'not_loaded' || liveProg.state === 'stopped'
	);
	const nowOnPlayer = $derived.by(() => {
		if (idle) return { label: 'Idle', detail: 'showing the idle ident' };
		const item = playout.status?.current_item;
		const detail = item?.title
			? `${itemTypeLabel(item.type, { short: true })} · ${item.title}`
			: (liveProg?.state ?? '');
		return { label: liveProg?.name ?? 'On air', detail };
	});

	type AgentStatus = Awaited<ReturnType<typeof loadAgentStatusRaw>>;
	let agentStatus = $state<AgentStatus | null>(null);
	let agentChecked = $state(false);

	function loadAgentStatusRaw() {
		return unwrap(api.GET('/api/v2/playout/agent/status'));
	}

	async function loadAgentStatus() {
		if (!activeHost) {
			agentStatus = null;
			agentChecked = true;
			return;
		}
		try {
			agentStatus = await loadAgentStatusRaw();
		} catch {
			// Supplementary — the status lamp just reads "unreachable".
			agentStatus = null;
		}
		agentChecked = true;
	}

	type LampColour = 'green' | 'red' | 'amber' | 'neutral';
	interface HostState {
		colour: LampColour;
		label: string;
		pending: boolean;
		detail?: string;
	}
	const activeState = $derived.by<HostState>(() => {
		if (!agentChecked) return { colour: 'neutral', label: 'Checking player…', pending: true };
		if (!agentStatus || !agentStatus.reachable) {
			return {
				colour: 'red',
				label: 'Unreachable',
				pending: false,
				detail: agentStatus?.error ?? 'The agent did not answer.'
			};
		}
		if (agentStatus.mpv_running) {
			const bits = [
				agentStatus.mpv_pid ? `pid ${agentStatus.mpv_pid}` : null,
				agentStatus.mpv_mode || null
			]
				.filter(Boolean)
				.join(' · ');
			return { colour: 'green', label: 'Running', pending: false, detail: bits || undefined };
		}
		return { colour: 'amber', label: 'Stopped', pending: false };
	});

	// Re-probe when the active host (by id) changes, incl. the initial load.
	let lastActiveId = -1;
	$effect(() => {
		if (hosts.loading) return;
		const id = activeHost?.id ?? 0;
		if (id === lastActiveId) return;
		lastActiveId = id;
		// A different host: its lamp reads "Checking" until its own status arrives,
		// not the previous host's result (or "Unreachable" for none).
		agentChecked = false;
		void loadAgentStatus();
	});

	// Re-probe on the real-time `invalidate` channel rather than polling.
	$effect(() => onInvalidate('agent', () => void loadAgentStatus()));

	async function reloadAll() {
		await hosts.refresh();
		void loadAgentStatus();
	}

	let mpvBusy = $state<string | null>(null);

	async function controlMpv(action: 'start' | 'stop' | 'restart') {
		mpvBusy = action;
		try {
			if (action === 'start') await unwrap(api.POST('/api/v2/playout/agent/start'));
			else if (action === 'stop') await unwrap(api.POST('/api/v2/playout/agent/stop'));
			else await unwrap(api.POST('/api/v2/playout/agent/restart'));
			showToast(
				`Player ${action === 'stop' ? 'stopped' : action === 'start' ? 'started' : 'restarted'}`,
				'success'
			);
		} catch (e) {
			showToast(e instanceof Error ? e.message : `Could not ${action} the player`, 'error');
		} finally {
			mpvBusy = null;
		}
		await loadAgentStatus();
	}

	// Soft reset: clear any loaded programme and drop back to the paused ident.
	// Destructive when a show is on air, so it asks first.
	async function returnToIdent() {
		if (!idle) {
			const ok = await confirm(
				`"${liveProg?.name}" is on the player. Return to the idle ident and clear it?`,
				{ confirmLabel: 'Return to ident' }
			);
			if (!ok) return;
		}
		mpvBusy = 'reset';
		try {
			await mutate(api.POST('/api/v2/playout/reset'));
			showToast('Player reset to the idle ident', 'success');
			void playout.refresh();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not reach the player', 'error');
		} finally {
			mpvBusy = null;
		}
	}

	async function activateHost(id: number) {
		// Switching hosts stops whatever is on air — confirm first if a
		// programme is loaded/running.
		try {
			const status = await unwrapLoose<PlayoutStatus>(api.GET('/api/v2/playout/status'));
			const prog = status?.programme;
			if (prog && prog.state && prog.state !== 'stopped' && prog.state !== 'not_loaded') {
				const ok = await confirm(
					`"${prog.name}" is loaded on the current host. Switching hosts will stop it. Switch anyway?`,
					{ confirmLabel: 'Switch' }
				);
				if (!ok) return;
			}
		} catch {
			// Status unavailable — proceed; the backend still unloads on switch.
		}
		try {
			await unwrap(
				api.POST('/api/v2/playout/hosts/{host_id}/activate', {
					params: { path: { host_id: id } }
				})
			);
			showToast('Playout host activated', 'success');
			await reloadAll();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not activate host', 'error');
		}
	}

	async function removeHost(id: number, name: string) {
		if (
			!(await confirm(
				`Remove "${name}"? Its player forgets this Cinefin and shows a pairing code again.`,
				{ confirmLabel: 'Remove' }
			))
		)
			return;
		try {
			await mutate(
				api.DELETE('/api/v2/playout/hosts/{host_id}', { params: { path: { host_id: id } } })
			);
			showToast('Playout host removed', 'success');
			await reloadAll();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not remove host', 'error');
		}
	}

	let refreshing = $state(false);

	async function refreshActiveHost() {
		if (!activeHost) return;
		refreshing = true;
		try {
			await unwrap(
				api.POST('/api/v2/playout/hosts/{host_id}/refresh', {
					params: { path: { host_id: activeHost.id } }
				})
			);
			await hosts.refresh();
			void loadAgentStatus();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Host did not answer', 'error');
		} finally {
			refreshing = false;
		}
	}

	// The player shown on the right of the Players tab: a host id, or 'add' for
	// the pairing panel. Defaults to the active host (else the first).
	let selectedId = $state<number | 'add' | null>(null);
	const selected = $derived.by(() => {
		if (selectedId === 'add') return null;
		const list = hosts.data ?? [];
		return list.find((h) => h.id === selectedId) ?? activeHost ?? list[0] ?? null;
	});
	const addingPlayer = $derived(selectedId === 'add' || !(hosts.data ?? []).length);

	// Adding a playout agent is pairing (PlayerPairing); this dialog edits a
	// host, or adds a local mpv the operator runs themselves.
	let hostOpen = $state(false);
	let editingHostId = $state<number | null>(null);
	let hKind = $state('local_socket');
	let hName = $state('');
	let hUrl = $state('');
	let hSocket = $state('');
	let hostSaveResult = $state<CheckState>(null);

	function openHostDialog(
		host: {
			id: number;
			name: string;
			kind: string;
			base_url: string;
			socket_path: string;
		} | null
	) {
		editingHostId = host?.id ?? null;
		hKind = host?.kind ?? 'local_socket';
		hName = host?.name ?? '';
		hUrl = host?.base_url ?? '';
		hSocket = host?.socket_path ?? '';
		hostSaveResult = null;
		hostOpen = true;
	}

	async function onPaired(host: { id: number; name: string }) {
		selectedId = host.id;
		showToast(`Paired with ${host.name}`, 'success');
		await reloadAll();
	}

	async function saveHost() {
		const name = hName.trim();
		if (!name) {
			hostSaveResult = { state: 'error', message: 'Enter a name' };
			return;
		}
		let body: Record<string, unknown>;
		if (hKind === 'local_socket') {
			const socket_path = hSocket.trim();
			if (!socket_path) {
				hostSaveResult = { state: 'error', message: 'Enter the mpv socket path' };
				return;
			}
			body = { name, kind: 'local_socket', socket_path };
		} else {
			const base_url = hUrl.trim();
			if (!base_url) {
				hostSaveResult = { state: 'error', message: "Enter the player's address" };
				return;
			}
			body = { name, base_url };
		}
		try {
			if (editingHostId != null) {
				await unwrap(
					api.PATCH('/api/v2/playout/hosts/{host_id}', {
						params: { path: { host_id: editingHostId } },
						body
					})
				);
			} else {
				await unwrap(api.POST('/api/v2/playout/hosts', { body }));
			}
			hostOpen = false;
			showToast(editingHostId != null ? 'Host updated' : 'Local mpv added', 'success');
			await reloadAll();
		} catch (e) {
			hostSaveResult = {
				state: 'error',
				message: e instanceof Error ? e.message : 'Could not save the host'
			};
		}
	}

	let identTesting = $state(false);

	async function playIdentNow() {
		identTesting = true;
		try {
			// No selection means the bundled System Ident — the backend derives it.
			await mutate(
				api.POST('/api/v2/settings/test-ident/', {
					body: store.main.default_cinema_ident
						? { bumper_id: parseInt(store.main.default_cinema_ident, 10) }
						: {}
				})
			);
			showToast('Ident playing on the player', 'success');
			void playout.refresh();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to play ident', 'error');
		} finally {
			identTesting = false;
		}
	}

	// The subtitle preview: a 16:9 frame drawn from the current (unsaved) values.
	// mpv sizes subtitles against a 720-line frame, so the font scales with the
	// frame's height (cqh); position 0 is the top, 100 the bottom.
	const subtitlePreviewStyle = $derived.by(() => {
		const m = store.main;
		const size = Number(m.subtitle_font_size) || 52;
		const pos = Math.min(100, Math.max(0, Number(m.subtitle_position) || 0));
		const margin = m.subtitle_use_margins ? Number(m.subtitle_margin_y) || 0 : 0;
		const back = m.subtitle_back_color || '#000000';
		const boxed = m.subtitle_border_style !== 'outline-and-shadow';
		return [
			`font-size: ${(size / 7.2).toFixed(2)}cqh`,
			`top: calc(${pos}% - ${(margin / 7.2).toFixed(2)}cqh)`,
			`color: ${m.subtitle_color || '#ffffff'}`,
			`font-weight: ${m.subtitle_bold ? 700 : 400}`,
			boxed ? `background: ${back}` : `text-shadow: 0 0 0.12em ${back}, 0 0 0.12em ${back}`
		].join('; ');
	});

	const subtitleInputCls =
		'h-9 w-full rounded-md border border-border-strong bg-surface-2 px-1.5 text-sm text-text focus:border-accent-dim';
</script>

<div class="space-y-4">
	{#if hosts.loading}
		<Spinner label="Loading playout…" />
	{:else if hosts.error}
		<ErrorState error={hosts.error} retry={() => void hosts.load()} />
	{:else}
		<Tabs
			tabs={TABS}
			value={tab}
			label="Playout settings"
			onselect={(id) => (tab = id)}
			panelId={(id) => `pt-${id}`}
		/>

		{#if tab === 'players'}
			<div
				role="tabpanel"
				id="pt-players"
				aria-labelledby="tab-players"
				class="mt-4"
				in:fade={{ duration: 120 }}
			>
				{#if !hosts.data?.length}
					<!-- ── First run: no players yet ──────────────────────────────── -->
					<section class="max-w-2xl space-y-5">
						<div>
							<h3 class="text-base font-medium">Add your first player</h3>
							<p class="mt-1 text-sm text-muted">
								Cinefin plays through a player: the machine wired to your screen.
							</p>
						</div>
						<div class="flex gap-3">
							<span class="step">1</span>
							<div>
								<p class="text-sm">
									Run <code class="font-mono text-[0.8rem]">cinefin-playout</code> on that machine.
								</p>
								<p class="mt-0.5 text-xs text-muted">Its screen shows a pairing code.</p>
							</div>
						</div>
						<div class="flex gap-3">
							<span class="step">2</span>
							<div class="min-w-0 flex-1">
								<p class="mb-3 text-sm">Choose it and type the code.</p>
								<PlayerPairing onpaired={onPaired} />
							</div>
						</div>
						<p class="border-t border-border pt-3 text-xs text-muted">
							Running mpv yourself?
							<button
								type="button"
								class="underline hover:text-text"
								onclick={() => openHostDialog(null)}>Add a local mpv</button
							>
						</p>
					</section>
				{:else}
					<div class="grid gap-6 md:grid-cols-[13rem_minmax(0,1fr)]">
						<!-- ── The players ───────────────────────────────────────────── -->
						<nav aria-label="Players" class="flex flex-col gap-1">
							{#each hosts.data as h (h.id)}
								{@const on = selectedId !== 'add' && selected?.id === h.id}
								<button
									type="button"
									aria-current={on ? 'true' : undefined}
									class="flex items-center gap-2.5 px-3 py-2 text-left text-sm font-medium hover:bg-surface-2
										{on ? 'bg-surface-2 text-text' : 'text-muted'}"
									onclick={() => (selectedId = h.id)}
								>
									<StatusLamp
										colour={h.is_active ? activeState.colour : 'neutral'}
										pending={h.is_active && activeState.pending}
									>
										<span class="sr-only">{h.is_active ? activeState.label : 'Not in use'}</span>
									</StatusLamp>
									<span class="min-w-0 flex-1 truncate">{h.name}</span>
									{#if h.is_active}<span class="text-[0.7rem] text-success">Active</span>{/if}
								</button>
							{/each}
							<div class="my-2 h-px bg-border"></div>
							<button
								type="button"
								aria-current={selectedId === 'add' ? 'true' : undefined}
								class="flex items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-2
									{selectedId === 'add' ? 'bg-surface-2 text-text' : 'text-muted'}"
								onclick={() => (selectedId = 'add')}
							>
								<Plus size={14} /> Add a player
							</button>
						</nav>

						<div class="min-w-0">
							{#if addingPlayer}
								<!-- ── Pairing another player ──────────────────────────────── -->
								<section class="space-y-4">
									<div>
										<h3 class="text-base font-medium">Add a player</h3>
										<p class="mt-1 text-sm text-muted">
											Run <code class="font-mono text-[0.8rem]">cinefin-playout</code> on the machine,
											then choose it and type the code on its screen.
										</p>
									</div>
									<PlayerPairing onpaired={onPaired} />
									<p class="border-t border-border pt-3 text-xs text-muted">
										Running mpv yourself?
										<button
											type="button"
											class="underline hover:text-text"
											onclick={() => openHostDialog(null)}>Add a local mpv</button
										>
									</p>
								</section>
							{:else if selected}
								{@const isSocket = selected.kind === 'local_socket'}
								{@const isActive = selected.is_active}
								<div class="space-y-5">
									<!-- ── The player ────────────────────────────────────────── -->
									<section class="space-y-2">
										<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
											<h3 class="text-lg font-medium">{selected.name}</h3>
											{#if isActive}
												<span title={activeState.detail}>
													<StatusLamp colour={activeState.colour} pending={activeState.pending}>
														{activeState.label}
													</StatusLamp>
												</span>
											{:else}
												<StatusLamp colour="neutral">Not in use</StatusLamp>
											{/if}
											{#if isActive && !isSocket}
												<Button
													size="sm"
													variant="ghost"
													class="ml-auto"
													disabled={refreshing}
													title="Ask the player for its status again"
													onclick={refreshActiveHost}
												>
													<RefreshCw size={13} /><span class="sr-only">Refresh status</span>
												</Button>
											{/if}
											<Button
												size="sm"
												variant="ghost"
												class={isActive && !isSocket ? '' : 'ml-auto'}
												onclick={() => openHostDialog(selected)}
											>
												<Pencil size={13} /> Edit
											</Button>
										</div>
										<p class="font-mono text-xs break-all text-muted">
											{#if isSocket}
												{selected.socket_path || '(no socket path)'} · local mpv
											{:else}
												{selected.base_url}{selected.agent_version
													? ` · agent ${selected.agent_version} · ${selected.os}/${selected.arch}`
													: ''}{selected.has_token ? '' : ' · not paired: remove it and pair again'}
											{/if}
										</p>

										{#if isActive}
											<div
												class="flex flex-wrap items-center gap-1.5 border border-border bg-surface-1 px-3 py-2.5"
											>
												<p class="mr-auto text-sm">
													<span class="text-muted">Now</span>
													<span class="ml-1 font-medium">{nowOnPlayer.label}</span>
													{#if nowOnPlayer.detail}<span class="text-muted">
															· {nowOnPlayer.detail}</span
														>{/if}
												</p>
												<Button
													size="sm"
													disabled={mpvBusy !== null}
													title="Clear any loaded programme and show the paused idle ident"
													onclick={() => void returnToIdent()}
												>
													<RotateCcw size={13} /> Return to ident
												</Button>
												{#if !isSocket && agentStatus?.reachable}
													{#if agentStatus.mpv_running}
														<Button
															size="sm"
															disabled={mpvBusy !== null}
															onclick={() => controlMpv('restart')}
														>
															<RotateCw size={13} /> Restart
														</Button>
														<Button
															size="sm"
															disabled={mpvBusy !== null}
															onclick={() => controlMpv('stop')}
														>
															<Square size={13} /> Stop
														</Button>
													{:else}
														<Button
															size="sm"
															variant="primary"
															disabled={mpvBusy !== null}
															onclick={() => controlMpv('start')}
														>
															<Play size={13} /> Start player
														</Button>
													{/if}
												{/if}
											</div>
										{:else}
											<div
												class="flex flex-wrap items-center gap-3 border border-border bg-surface-1 px-3 py-2.5"
											>
												<p class="mr-auto text-sm text-muted">
													Cinefin plays through one player at a time.
												</p>
												<Button
													size="sm"
													variant="primary"
													onclick={() => activateHost(selected.id)}
												>
													<CircleCheck size={13} /> Use this player
												</Button>
											</div>
										{/if}
									</section>

									<!-- ── Screen and sound ──────────────────────────────────── -->
									<section class="border border-border bg-surface-1">
										<div class="px-4 pt-4">
											<h3 class="text-sm font-medium">Screen and sound</h3>
											<p class="mt-0.5 text-xs text-muted">
												{isSocket
													? 'You run this mpv, so set its screen and sound with its own options when you launch it.'
													: 'Applies when the player restarts.'}
											</p>
										</div>
										{#if !isSocket}
											{#key selected.id}
												<HostConfigPanel hostId={selected.id} kind={selected.kind} />
											{/key}
										{:else}
											<div class="pb-4"></div>
										{/if}
									</section>

									<!-- ── Remove ────────────────────────────────────────────── -->
									<section class="flex items-center gap-3 border-t border-border pt-4">
										<div class="mr-auto">
											<h3 class="text-sm font-medium">Remove this player</h3>
											<p class="mt-0.5 text-xs text-muted">
												{isSocket
													? 'Cinefin stops using this mpv.'
													: 'It forgets this Cinefin and shows a pairing code again.'}
											</p>
										</div>
										<Button variant="danger" onclick={() => removeHost(selected.id, selected.name)}>
											<Trash2 size={13} /> Remove
										</Button>
									</section>
								</div>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		{:else if tab === 'presentation'}
			<div
				role="tabpanel"
				id="pt-presentation"
				aria-labelledby="tab-presentation"
				class="mt-4 space-y-6"
				in:fade={{ duration: 120 }}
			>
				<p class="-mt-1 text-sm text-muted">These apply to every player.</p>

				<!-- ── Idle screen ───────────────────────────────────────────────── -->
				<section class="space-y-3 border border-border bg-surface-1 p-4">
					<div>
						<h3 class="text-sm font-medium">Idle screen</h3>
						<p class="mt-0.5 text-xs text-muted">
							Shown paused when nothing plays, and first in every programme.
						</p>
					</div>
					<Field
						label="Ident"
						forId="set-default-ident"
						dirty={store.isDirty('default_cinema_ident')}
						error={store.errorFor('default_cinema_ident')}
					>
						<div class="flex max-w-xl gap-2">
							<Select
								id="set-default-ident"
								bind:value={store.main.default_cinema_ident}
								class="w-full"
							>
								<option value="">Built-in System Ident</option>
								{#each store.bumpers as b (b.id)}
									<option value={String(b.id)}>{b.title} ({b.duration}s)</option>
								{/each}
							</Select>
							<Button disabled={identTesting} onclick={playIdentNow}>
								<MonitorPlay size={14} /> Show on player
							</Button>
						</div>
					</Field>
				</section>

				<!-- ── Subtitles ─────────────────────────────────────────────────── -->
				<section class="space-y-4 border border-border bg-surface-1 p-4">
					<div>
						<h3 class="text-sm font-medium">Subtitles</h3>
						<p class="mt-0.5 text-xs text-muted">Applied live when you save, no restart.</p>
					</div>
					<div class="grid gap-6 lg:grid-cols-2">
						<div class="space-y-4">
							<div class="grid grid-cols-3 gap-3">
								<Field
									label="Size"
									forId="set-subtitle-size"
									dirty={store.isDirty('subtitle_font_size')}
									error={store.errorFor('subtitle_font_size')}
								>
									<Input
										id="set-subtitle-size"
										type="number"
										bind:value={store.main.subtitle_font_size}
									/>
								</Field>
								<Field
									label="Position"
									forId="set-subtitle-position"
									dirty={store.isDirty('subtitle_position')}
									error={store.errorFor('subtitle_position')}
								>
									<Input
										id="set-subtitle-position"
										type="number"
										bind:value={store.main.subtitle_position}
									/>
								</Field>
								<Field
									label="Margin"
									forId="set-subtitle-margin"
									dirty={store.isDirty('subtitle_margin_y')}
									error={store.errorFor('subtitle_margin_y')}
								>
									<Input
										id="set-subtitle-margin"
										type="number"
										bind:value={store.main.subtitle_margin_y}
									/>
								</Field>
							</div>
							<Field
								label="Background"
								forId="set-subtitle-border"
								dirty={store.isDirty('subtitle_border_style')}
								error={store.errorFor('subtitle_border_style')}
							>
								<Select
									id="set-subtitle-border"
									bind:value={store.main.subtitle_border_style}
									class="w-full"
								>
									<option value="outline-and-shadow">Outline &amp; shadow</option>
									<option value="opaque-box">Opaque box</option>
									<option value="background-box">Background box</option>
								</Select>
							</Field>
							<div class="grid grid-cols-2 gap-3">
								<Field
									label="Text"
									forId="set-subtitle-color"
									dirty={store.isDirty('subtitle_color')}
									error={store.errorFor('subtitle_color')}
								>
									<input
										id="set-subtitle-color"
										type="color"
										bind:value={store.main.subtitle_color}
										class={subtitleInputCls}
									/>
								</Field>
								<Field
									label="Box / shadow"
									forId="set-subtitle-back-color"
									dirty={store.isDirty('subtitle_back_color')}
									error={store.errorFor('subtitle_back_color')}
								>
									<input
										id="set-subtitle-back-color"
										type="color"
										bind:value={store.main.subtitle_back_color}
										class={subtitleInputCls}
									/>
								</Field>
							</div>
							<div class="space-y-2.5">
								<Toggle
									label="Keep inside the picture"
									bind:checked={store.main.subtitle_use_margins}
									dirty={store.isDirty('subtitle_use_margins')}
								/>
								<Toggle
									label="Bold"
									bind:checked={store.main.subtitle_bold}
									dirty={store.isDirty('subtitle_bold')}
								/>
							</div>
						</div>
						<div>
							<p class="mb-1.5 text-xs font-medium text-muted">Preview</p>
							<div
								class="subtitle-frame relative aspect-video overflow-hidden border border-border bg-[#1a1f24]"
								aria-hidden="true"
							>
								<span
									class="absolute left-1/2 -translate-x-1/2 -translate-y-full px-[0.3em] leading-snug whitespace-nowrap"
									style={subtitlePreviewStyle}>Where are you taking me?</span
								>
							</div>
						</div>
					</div>
				</section>

				<!-- ── Streaming address ─────────────────────────────────────────── -->
				<section class="space-y-3 border border-border bg-surface-1 p-4">
					<div>
						<h3 class="text-sm font-medium">Streaming address</h3>
						<p class="mt-0.5 text-xs text-muted">
							Players stream everything from Cinefin at this address, so every player must reach it.
							Blank uses the <code class="font-mono">CINEFIN_SERVER_URL</code> default.
						</p>
					</div>
					<Field
						label="Address"
						forId="set-server-url"
						dirty={store.isDirty('playout_server_url')}
						error={store.errorFor('playout_server_url')}
					>
						<Input
							id="set-server-url"
							bind:value={store.main.playout_server_url}
							placeholder="http://cinefin.local:8000"
							class="max-w-xl font-mono"
						/>
					</Field>
				</section>
			</div>
		{/if}
	{/if}
</div>

<Dialog
	bind:open={hostOpen}
	title={editingHostId != null ? `Edit ${hName || 'host'}` : 'Add a local mpv'}
>
	<div class="space-y-3">
		<Field label="Name" forId="set-host-name">
			<Input id="set-host-name" bind:value={hName} placeholder="Booth PC" />
		</Field>
		{#if hKind === 'local_socket'}
			<Field
				label="mpv socket path"
				forId="set-host-socket"
				hint="The path you passed to mpv's --input-ipc-server, e.g. /tmp/mpvsocket."
			>
				<Input id="set-host-socket" bind:value={hSocket} placeholder="/tmp/mpvsocket" />
			</Field>
		{:else}
			<Field
				label="Address"
				forId="set-host-url"
				hint="Change it if the player's address changed. The pairing is kept."
			>
				<Input id="set-host-url" bind:value={hUrl} placeholder="http://10.0.0.5:8089" />
			</Field>
		{/if}
		<CheckResult result={hostSaveResult} />
	</div>
	{#snippet footer()}
		<Button onclick={() => (hostOpen = false)}>Cancel</Button>
		<Button variant="primary" onclick={saveHost}><Check size={14} /> Save</Button>
	{/snippet}
</Dialog>

<style>
	.step {
		display: flex;
		flex: none;
		align-items: center;
		justify-content: center;
		width: 1.5rem;
		height: 1.5rem;
		border: 1px solid var(--color-border-strong);
		font: 500 0.75rem var(--font-mono);
		color: var(--color-muted);
	}
	.subtitle-frame {
		container-type: size;
	}
</style>
