<script lang="ts">
	import { fade } from 'svelte/transition';
	import {
		Check,
		CircleCheck,
		Info,
		MonitorPlay,
		Pencil,
		Play,
		Plus,
		RefreshCw,
		RotateCcw,
		RotateCw,
		Server,
		Square,
		Terminal,
		Trash2,
		X
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
	import { formatDateTime, type SettingsStore } from '$lib/settings/form.svelte';
	import type { CheckState } from '$lib/settings/types';
	import type { PlayoutStatus } from '$lib/api/refinements';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import CheckResult from './CheckResult.svelte';
	import Disclosure from './Disclosure.svelte';
	import Field from './Field.svelte';
	import HostConfigPanel from './HostConfigPanel.svelte';
	import Toggle from '$lib/components/ui/Toggle.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	interface Props {
		store: SettingsStore;
		confirm: ConfirmDialog['confirm'];
	}
	let { store, confirm }: Props = $props();

	const TABS = [
		{ id: 'player', label: 'Player' },
		{ id: 'show', label: 'Show' }
	];
	let tab = $state('player');

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
		if (!(await confirm(`Remove "${name}"?`, { confirmLabel: 'Remove' }))) return;
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

	let hostOpen = $state(false);
	let editingHostId = $state<number | null>(null);
	let hostHasToken = $state(false);
	let hKind = $state('agent');
	let hName = $state('');
	let hUrl = $state('');
	let hSocket = $state('');
	let hToken = $state('');
	let hostSaveResult = $state<CheckState>(null);

	function openHostDialog(
		host: {
			id: number;
			name: string;
			kind: string;
			base_url: string;
			socket_path: string;
			has_token: boolean;
		} | null
	) {
		editingHostId = host?.id ?? null;
		hostHasToken = host?.has_token ?? false;
		hKind = host?.kind ?? 'agent';
		hName = host?.name ?? '';
		hUrl = host?.base_url ?? '';
		hSocket = host?.socket_path ?? '';
		hToken = '';
		hostSaveResult = null;
		hostOpen = true;
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
				hostSaveResult = { state: 'error', message: 'Enter a name and agent URL' };
				return;
			}
			const token = hToken.trim();
			body = token ? { name, kind: 'agent', base_url, token } : { name, kind: 'agent', base_url };
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
			showToast(editingHostId != null ? 'Host updated' : 'Playout host added', 'success');
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

	let preshowPick = $state('');

	function addPreshow() {
		const id = parseInt(preshowPick, 10);
		preshowPick = '';
		if (!id || store.main.preshow_commands.some((c) => c.command === id)) return;
		store.main.preshow_commands = [...store.main.preshow_commands, { command: id, lead: 0 }];
	}

	function removePreshow(id: number) {
		store.main.preshow_commands = store.main.preshow_commands.filter((c) => c.command !== id);
	}

	function setPreshowLead(id: number, value: string) {
		const lead = Math.max(0, Math.round(Number(value) || 0));
		store.main.preshow_commands = store.main.preshow_commands.map((c) =>
			c.command === id ? { ...c, lead } : c
		);
	}

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

		{#if tab === 'player'}
			<div
				role="tabpanel"
				id="pt-player"
				aria-labelledby="tab-player"
				class="mt-4 space-y-6"
				in:fade={{ duration: 120 }}
			>
				<!-- ── The active player ─────────────────────────────────────────── -->
				{#if !hosts.data?.length}
					<EmptyState
						compact
						icon={Server}
						title="No playout host configured yet"
						message="Add the machine Cinefin plays through — a playout agent, or a local mpv you run yourself."
					/>
					<div class="mt-3">
						<Button variant="primary" onclick={() => openHostDialog(null)}>
							<Plus size={14} /> Add host
						</Button>
					</div>
				{:else if activeHost}
					{@const isSocket = activeHost.kind === 'local_socket'}
					<section class="border border-border bg-surface-2">
						<div class="space-y-3 p-4">
							<div class="flex flex-col gap-3 sm:flex-row sm:items-start">
								<div class="min-w-0 flex-1 space-y-1.5">
									<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
										<span class="font-medium">{activeHost.name}</span>
										<span class="font-mono text-[0.7rem] text-faint"
											>{isSocket ? 'local mpv' : 'agent'}</span
										>
										<span title={activeState.detail}>
											<StatusLamp colour={activeState.colour} pending={activeState.pending}>
												{activeState.label}
											</StatusLamp>
										</span>
									</div>
									<!-- What is on the screen right now, in plain words. -->
									<p class="text-sm">
										<span class="text-faint">Now on player</span>
										<span class="ml-1.5 font-medium">{nowOnPlayer.label}</span>
										{#if nowOnPlayer.detail}
											<span class="text-muted"> — {nowOnPlayer.detail}</span>
										{/if}
									</p>
									<code class="block font-mono text-xs break-all text-muted">
										{isSocket ? activeHost.socket_path || '(no socket path)' : activeHost.base_url}
									</code>
									{#if isSocket}
										<p class="text-xs text-faint">
											You run this mpv — start it with <code class="font-mono"
												>--input-ipc-server</code
											>.
										</p>
									{:else}
										<p class="text-xs text-faint">
											{activeHost.agent_version
												? `agent ${activeHost.agent_version} · ${activeHost.os}/${activeHost.arch} · `
												: ''}last seen
											{activeHost.last_seen_at
												? formatDateTime(activeHost.last_seen_at)
												: 'never'}{activeHost.has_token ? '' : ' · no token'}
										</p>
									{/if}
								</div>
							</div>

							<!-- Controls. Return to ident always works; process control is agent-only. -->
							<div class="flex flex-wrap items-center gap-1.5 border-t border-border pt-3">
								<Button
									size="sm"
									disabled={mpvBusy !== null}
									title="Clear any loaded programme and show the paused idle ident"
									onclick={() => void returnToIdent()}
								>
									<RotateCcw size={13} /> Return to ident
								</Button>
								{#if !isSocket}
									{#if agentStatus?.reachable}
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
									<Button size="sm" disabled={refreshing} onclick={refreshActiveHost}>
										<RefreshCw size={13} /> Refresh
									</Button>
								{/if}
								<Button size="sm" class="ml-auto" onclick={() => openHostDialog(activeHost)}>
									<Pencil size={13} /> Edit
								</Button>
							</div>
						</div>
					</section>
				{:else}
					<p class="flex items-center gap-2 text-sm text-muted">
						<Info size={14} /> No active host — pick one under
						<strong class="text-text">Manage hosts</strong> below.
					</p>
				{/if}

				{#if hosts.data?.length}
					<Disclosure
						title="Manage hosts"
						note={hosts.data.length > 1 ? `${hosts.data.length} hosts` : undefined}
					>
						<div class="space-y-2">
							{#each hosts.data as h (h.id)}
								{@const isSocket = h.kind === 'local_socket'}
								<div
									class="flex flex-col gap-2 rounded-md border p-2.5 sm:flex-row sm:items-center
								{h.is_active ? 'border-accent-dim bg-surface-2' : 'border-border'}"
								>
									<div class="min-w-0 flex-1">
										<div class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
											<span class="text-sm font-medium">{h.name}</span>
											<span class="font-mono text-[0.7rem] text-faint"
												>{isSocket ? 'local mpv' : 'agent'}</span
											>
											{#if h.is_active}<StatusLamp colour="green">Active</StatusLamp>{/if}
										</div>
										<code class="font-mono text-xs break-all text-muted">
											{isSocket ? h.socket_path || '(no socket path)' : h.base_url}
										</code>
									</div>
									<div class="flex shrink-0 items-center gap-1.5">
										{#if !h.is_active}
											<Button size="sm" variant="primary" onclick={() => activateHost(h.id)}>
												<CircleCheck size={13} /> Use
											</Button>
										{/if}
										<Button size="sm" onclick={() => openHostDialog(h)}>
											<Pencil size={13} /> Edit
										</Button>
										<Button
											size="sm"
											variant="danger"
											title="Remove host"
											onclick={() => removeHost(h.id, h.name)}
										>
											<Trash2 size={13} />
										</Button>
									</div>
								</div>
							{/each}
						</div>

						<div class="mt-3">
							<Button onclick={() => openHostDialog(null)}><Plus size={14} /> Add host</Button>
						</div>
						<p class="mt-2 text-xs text-faint">
							The active host is the one Cinefin plays through. Switching hosts stops anything
							currently on air. Tokens are stored write-only - never shown again.
						</p>

						<div class="mt-4">
							<Field
								label="Streaming base URL"
								forId="set-server-url"
								dirty={store.isDirty('playout_server_url')}
								error={store.errorFor('playout_server_url')}
							>
								<Input
									id="set-server-url"
									bind:value={store.main.playout_server_url}
									placeholder="http://cinefin.local:8000"
									class="max-w-xl"
								/>
								{#snippet hintSnippet()}
									Everything the player shows is streamed from Cinefin at this URL - idents, movies,
									trailers, user media, title cards.
									<strong class="text-muted">The playout host must be able to reach it.</strong>
									Leave blank to use the <code class="font-mono">CINEFIN_SERVER_URL</code> environment
									default (fine when Cinefin and the player are on the same machine).
								{/snippet}
							</Field>
						</div>
					</Disclosure>
				{/if}

				<!-- ── Idle & ident ──────────────────────────────────────────────── -->
				<section class="space-y-2">
					<div>
						<h3 class="text-sm font-medium">Idle &amp; ident</h3>
						<p class="mt-0.5 max-w-2xl text-xs text-muted">
							The ident is your cinema's stand-in clip. It does three jobs: it's the
							<strong class="text-text">idle screen</strong> (shown paused when nothing is playing),
							the <strong class="text-text">opening item</strong> of every programme, and what the player
							returns to on reset or when a show finishes.
						</p>
					</div>
					<Field
						label="System Ident"
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
								<option value="">- Built-in System Ident -</option>
								{#each store.bumpers as b (b.id)}
									<option value={String(b.id)}>{b.title} ({b.duration}s)</option>
								{/each}
							</Select>
							<Button disabled={identTesting} onclick={playIdentNow}>
								<MonitorPlay size={14} /> Play on player now
							</Button>
						</div>
						{#snippet hintSnippet()}
							Cinefin ships one; pick an uploaded media item to use your own. Either way it is
							<strong class="text-muted">streamed</strong> to the host - no local file needed there.
							<strong class="text-muted">Play on player now</strong> plays it on the live screen straight
							away. Part of "Save changes"; restart the player to apply a change to the idle screen.
						{/snippet}
					</Field>
				</section>

				<!-- ── Display & audio (agent hosts only) ────────────────────────── -->
				{#if activeHost && isAgent}
					<Disclosure title="Display & audio">
						<HostConfigPanel hostId={activeHost.id} kind={activeHost.kind} />
					</Disclosure>
				{/if}
			</div>
		{:else if tab === 'show'}
			<div
				role="tabpanel"
				id="pt-show"
				aria-labelledby="tab-show"
				class="mt-4 space-y-6"
				in:fade={{ duration: 120 }}
			>
				<!-- ── Subtitles ─────────────────────────────────────────────────── -->
				<section class="space-y-2">
					<div>
						<h3 class="text-sm font-medium">Subtitles</h3>
						<p class="mt-0.5 max-w-2xl text-xs text-muted">
							One subtitle style for the room, applied to the live player the moment you save - no
							restart. Per-block subtitle track selection is separate.
						</p>
					</div>
					<div class="grid max-w-2xl gap-4 sm:grid-cols-3">
						<Field
							label="Font size"
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
							label="Position (0 top - 100 bottom)"
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
						<Field
							label="Border style"
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
						<Field
							label="Text colour"
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
							label="Box / shadow colour"
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
					<div class="mt-4 space-y-2.5">
						<Toggle
							label="Keep inside the video margins"
							bind:checked={store.main.subtitle_use_margins}
							dirty={store.isDirty('subtitle_use_margins')}
						/>
						<Toggle
							label="Bold"
							bind:checked={store.main.subtitle_bold}
							dirty={store.isDirty('subtitle_bold')}
						/>
					</div>
				</section>

				<!-- ── Pre-show commands ─────────────────────────────────────────── -->
				<section class="space-y-2">
					<div>
						<h3 class="text-sm font-medium">
							Pre-show commands
							<span class="ml-1 font-mono text-xs text-faint"
								>{store.main.preshow_commands.length}</span
							>
						</h3>
						<p class="mt-0.5 max-w-2xl text-xs text-muted">
							Commands run for every <strong class="text-text">scheduled</strong> screening - dimming
							lights, waking the projector. Each fires its set number of seconds before the start
							(0 = at the start). Manual starts skip them; run the sequence by hand from the
							<a href="{base}/remote" class="text-accent hover:underline">remote</a>.
						</p>
					</div>
					<Field
						label="Commands"
						dirty={store.isDirty('preshow_commands')}
						error={store.errorFor('preshow_commands')}
					>
						{#if store.main.preshow_commands.length}
							<div class="mb-3 max-w-xl divide-y divide-border rounded-md border border-border">
								{#each store.main.preshow_commands as cue (cue.command)}
									<div class="flex items-center gap-2 px-3 py-1.5 text-sm">
										<Terminal size={13} class="shrink-0 text-muted" />
										<span class="min-w-0 flex-1 truncate">{store.commandName(cue.command)}</span>
										<label class="flex shrink-0 items-center gap-1.5 text-xs text-muted">
											<input
												type="number"
												min="0"
												step="1"
												class="w-16 rounded-sm border border-border bg-surface-2 px-1.5 py-0.5 text-right font-mono text-xs"
												value={cue.lead}
												oninput={(e) => setPreshowLead(cue.command, e.currentTarget.value)}
											/>
											s before
										</label>
										<button
											type="button"
											class="shrink-0 rounded-sm p-0.5 text-muted hover:bg-surface-3 hover:text-danger"
											title="Remove command"
											aria-label="Remove command"
											onclick={() => removePreshow(cue.command)}
										>
											<X size={14} />
										</button>
									</div>
								{/each}
							</div>
						{:else}
							<p class="mb-3 text-sm text-muted">No pre-show commands yet</p>
						{/if}
						<div class="flex max-w-xl gap-2">
							<Select bind:value={preshowPick} class="w-full">
								<option value="">Select a command…</option>
								{#each store.commands as cmd (cmd.id)}
									<option value={String(cmd.id)}>{cmd.name}</option>
								{/each}
							</Select>
							<Button onclick={addPreshow}><Plus size={14} /> Add</Button>
						</div>
						{#snippet hintSnippet()}
							Pick from your configured
							<a href="{base}/commands" class="text-accent hover:underline">commands</a>.
							Best-effort - a command that fails is logged and skipped, the show still starts.
						{/snippet}
					</Field>
				</section>
			</div>
		{/if}
	{/if}
</div>

<Dialog
	bind:open={hostOpen}
	title={editingHostId != null ? `Edit ${hName || 'host'}` : 'Add playout host'}
>
	<div class="space-y-3">
		<Field label="Name" forId="set-host-name">
			<Input id="set-host-name" bind:value={hName} placeholder="Booth PC" />
		</Field>
		<Field
			label="Type"
			forId="set-host-kind"
			hint={hKind === 'local_socket'
				? 'A plain mpv you run yourself with --input-ipc-server. No start/stop from here.'
				: 'The Cinefin playout agent - a WebSocket, and it can start/stop the player.'}
		>
			<Select id="set-host-kind" bind:value={hKind} class="w-full">
				<option value="agent">Playout agent (WebSocket)</option>
				<option value="local_socket">Local mpv (JSON-IPC socket)</option>
			</Select>
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
			<Field label="Agent URL" forId="set-host-url">
				<Input id="set-host-url" bind:value={hUrl} placeholder="http://127.0.0.1:8089" />
			</Field>
			<Field
				label="Agent token"
				forId="set-host-token"
				hint="The server.token from the agent's config.toml. Stored write-only."
			>
				<Input
					id="set-host-token"
					type="password"
					bind:value={hToken}
					placeholder={editingHostId != null && hostHasToken
						? 'leave blank to keep the current token'
						: 'shared secret (server.token in config.toml)'}
				/>
			</Field>
		{/if}
		<CheckResult result={hostSaveResult} />
	</div>
	{#snippet footer()}
		<Button onclick={() => (hostOpen = false)}>Cancel</Button>
		<Button variant="primary" onclick={saveHost}><Check size={14} /> Save</Button>
	{/snippet}
</Dialog>
