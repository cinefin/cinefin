<script lang="ts">
	import {
		Check,
		CircleCheck,
		MonitorPlay,
		Play,
		Plus,
		RefreshCw,
		RotateCcw,
		RotateCw,
		Pencil,
		Trash2,
		Square
	} from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { query } from '$lib/api/query.svelte';
	import { onInvalidate } from '$lib/invalidate';
	import { unwrapLoose } from '$lib/jobs';
	import { showToast } from '$lib/toast.svelte';
	import { playout } from '$lib/stores/playout.svelte';
	import { itemTypeLabel } from '$lib/item-types';
	import { attempt, errorText, type SettingsStore } from '$lib/settings/form.svelte';
	import type { CheckState } from '$lib/settings/types';
	import type { PlayoutStatus } from '$lib/playout/phase';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Banner from '$lib/components/ui/Banner.svelte';
	import AddPlayerWizard from '$lib/playout/AddPlayerWizard.svelte';
	import CheckResult from './CheckResult.svelte';
	import Field from '$lib/settings/Field.svelte';
	import HostConfigPanel from './HostConfigPanel.svelte';
	import SettingList from './SettingList.svelte';
	import SettingLists from './SettingLists.svelte';
	import SettingRow from './SettingRow.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import StoreToggle from '$lib/settings/StoreToggle.svelte';
	import StoreField, { storeField } from '$lib/settings/StoreField.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	interface Props {
		store: SettingsStore;
		confirm: ConfirmDialog['confirm'];
	}
	let { store, confirm }: Props = $props();

	const hosts = query(() => unwrap(api.GET('/api/v2/playout/hosts')));
	const activeHost = $derived(hosts.data?.find((h) => h.is_active) ?? null);

	$effect(() => playout.subscribe());
	const liveProg = $derived(playout.status?.programme ?? null);
	const idle = $derived(!liveProg);
	const nowOnPlayer = $derived.by(() => {
		if (idle) return { label: 'Standby', detail: 'showing the ident' };
		const item = playout.status?.current_item;
		const detail = item?.title
			? `${itemTypeLabel(item.type, { short: true })} · ${item.title}`
			: (playout.status?.label ?? '');
		return { label: liveProg?.name ?? 'On air', detail };
	});

	const fetchAgentStatus = () => unwrap(api.GET('/api/v2/playout/agent/status'));
	let agentStatus = $state<Awaited<ReturnType<typeof fetchAgentStatus>> | null>(null);
	let agentChecked = $state(false);

	async function loadAgentStatus() {
		// Supplementary: a failed probe just reads "Unreachable".
		agentStatus = activeHost ? await fetchAgentStatus().catch(() => null) : null;
		agentChecked = true;
	}

	interface HostState {
		colour: 'green' | 'red' | 'amber' | 'neutral';
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
			const { mpv_pid, mpv_mode } = agentStatus;
			const bits = [mpv_pid && `pid ${mpv_pid}`, mpv_mode].filter(Boolean).join(' · ');
			return { colour: 'green', label: 'Running', pending: false, detail: bits || undefined };
		}
		return { colour: 'amber', label: 'Stopped', pending: false };
	});

	// Re-probe when the active host changes (incl. the first load); until its own status arrives
	// its lamp reads "Checking", not the previous host's result.
	let lastActiveId = -1;
	$effect(() => {
		if (hosts.loading) return;
		const id = activeHost?.id ?? 0;
		if (id === lastActiveId) return;
		lastActiveId = id;
		agentChecked = false;
		void loadAgentStatus();
	});
	$effect(() => onInvalidate('agent', () => void loadAgentStatus()));

	async function reloadAll() {
		await hosts.refresh();
		void loadAgentStatus();
	}

	let mpvBusy = $state<string | null>(null);
	const MPV_ACTIONS = [
		{ action: 'restart', Icon: RotateCw, label: 'Restart' },
		{ action: 'stop', Icon: Square, label: 'Stop' }
	] as const;

	async function controlMpv(action: 'start' | 'stop' | 'restart') {
		mpvBusy = action;
		await attempt(async () => {
			await unwrap(api.POST(`/api/v2/playout/agent/${action}`));
			showToast(`Player ${action === 'stop' ? 'stopped' : `${action}ed`}`, 'success');
		}, `Could not ${action} the player`);
		mpvBusy = null;
		await loadAgentStatus();
	}

	// Clears any loaded programme, so it asks first when one is on air.
	async function goToStandby() {
		if (!idle) {
			const ok = await confirm(
				`"${liveProg?.name}" is on the player. Go to standby and clear it?`,
				{ confirmLabel: 'Go to standby' }
			);
			if (!ok) return;
		}
		mpvBusy = 'reset';
		await attempt(async () => {
			await mutate(api.POST('/api/v2/playout/reset'));
			showToast('The player is on standby', 'success');
			void playout.refresh();
		}, 'Could not reach the player');
		mpvBusy = null;
	}

	// Switching hosts stops whatever is on air, so it asks first when a programme is loaded.
	async function activateHost(id: number) {
		try {
			const status = await unwrapLoose<PlayoutStatus>(api.GET('/api/v2/playout/status'));
			const prog = status?.programme;
			if (prog) {
				const ok = await confirm(
					`"${prog.name}" is loaded on the current host. Switching hosts will stop it. Switch anyway?`,
					{ confirmLabel: 'Switch' }
				);
				if (!ok) return;
			}
		} catch {
			// Status unavailable — proceed; the backend still unloads on switch.
		}
		await attempt(async () => {
			await unwrap(
				api.POST('/api/v2/playout/hosts/{host_id}/activate', { params: { path: { host_id: id } } })
			);
			showToast('Playout host activated', 'success');
			await reloadAll();
		}, 'Could not activate host');
	}

	async function removeHost(id: number, name: string) {
		const ok = await confirm(
			`Remove "${name}"? Its player forgets this Cinefin and shows a pairing code again.`,
			{ confirmLabel: 'Remove' }
		);
		if (!ok) return;
		await attempt(async () => {
			await mutate(
				api.DELETE('/api/v2/playout/hosts/{host_id}', { params: { path: { host_id: id } } })
			);
			showToast('Playout host removed', 'success');
			await reloadAll();
		}, 'Could not remove host');
	}

	let refreshing = $state(false);

	async function refreshActiveHost() {
		if (!activeHost) return;
		const host_id = activeHost.id;
		refreshing = true;
		await attempt(async () => {
			await unwrap(
				api.POST('/api/v2/playout/hosts/{host_id}/refresh', { params: { path: { host_id } } })
			);
			await reloadAll();
		}, 'Host did not answer');
		refreshing = false;
	}

	// The player shown beside the list: by default the active one, else the first.
	let selectedId = $state<number | null>(null);
	let configSummary = $state('');
	const selected = $derived.by(() => {
		const list = hosts.data ?? [];
		return list.find((h) => h.id === selectedId) ?? activeHost ?? list[0] ?? null;
	});

	// The Add a player wizard, also used to pair a known player again (from its Pair step).
	let wizardOpen = $state(false);
	let wizardStart = $state<{ base_url: string; name: string } | undefined>();

	function openWizard(start?: { base_url: string; name: string }) {
		wizardStart = start;
		wizardOpen = true;
	}

	async function onWizardFinish(host: { id: number; name: string }) {
		wizardOpen = false;
		selectedId = host.id;
		showToast(`${host.name} is ready`, 'success');
		await reloadAll();
	}

	async function setShowStatus(id: number, on: boolean) {
		await attempt(
			() =>
				unwrap(
					api.PATCH('/api/v2/playout/hosts/{host_id}', {
						params: { path: { host_id: id } },
						body: { show_status: on }
					})
				),
			'Could not save'
		);
		await hosts.refresh();
	}

	// The edit dialog (players are added with the wizard).
	let hostOpen = $state(false);
	let editingHostId = $state<number | null>(null);
	let hKind = $state('local_socket');
	let hName = $state('');
	let hUrl = $state('');
	let hSocket = $state('');
	let hostSaveResult = $state<CheckState>(null);

	function openHostDialog(host: NonNullable<typeof selected>) {
		editingHostId = host.id;
		hKind = host.kind;
		hName = host.name;
		hUrl = host.base_url;
		hSocket = host.socket_path;
		hostSaveResult = null;
		hostOpen = true;
	}

	async function saveHost() {
		const name = hName.trim();
		const socket = hKind === 'local_socket';
		const target = (socket ? hSocket : hUrl).trim();
		const noTarget = socket ? 'Enter the mpv socket path' : "Enter the player's address";
		const missing = !name ? 'Enter a name' : !target ? noTarget : null;
		if (missing) {
			hostSaveResult = { state: 'error', message: missing };
			return;
		}
		const body = socket
			? { name, kind: 'local_socket', socket_path: target }
			: { name, base_url: target };
		if (editingHostId == null) return;
		try {
			await unwrap(
				api.PATCH('/api/v2/playout/hosts/{host_id}', {
					params: { path: { host_id: editingHostId } },
					body
				})
			);
			hostOpen = false;
			showToast('Host updated', 'success');
			await reloadAll();
		} catch (e) {
			hostSaveResult = { state: 'error', message: errorText(e, 'Could not save the host') };
		}
	}

	let standbyPreviewing = $state(false);

	// Your own ident freezes on its hold point (a property of the media item, saved at once).
	const ownIdent = $derived(
		store.bumpers.find((b) => String(b.id) === store.main.default_cinema_ident) ?? null
	);

	async function saveHoldPoint(raw: string) {
		if (!ownIdent) return;
		const value = raw.trim() === '' ? null : Number(raw);
		if (value !== null && (!Number.isFinite(value) || value < 0)) {
			showToast('Enter seconds from the start, or leave it empty for the last frame', 'error');
			return;
		}
		const bumper = ownIdent;
		await attempt(async () => {
			await unwrap(
				api.PUT('/api/v2/media/{media_id}', {
					params: { path: { media_id: bumper.id } },
					body: { hold_point: value }
				})
			);
			bumper.hold_point = value;
			showToast(
				value === null ? 'Standby holds the last frame' : `Standby holds at ${value}s`,
				'success'
			);
		}, 'Could not save the hold point');
	}

	// Standby plays the saved ident (the button is off for the moment a new choice takes to save).
	async function previewStandby() {
		standbyPreviewing = true;
		await attempt(async () => {
			await mutate(api.POST('/api/v2/settings/preview-standby/'));
			showToast('The player is on standby', 'success');
			void playout.refresh();
		}, 'Could not preview standby');
		standbyPreviewing = false;
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

	const subtitleSummary = $derived.by(() => {
		const m = store.main;
		const style = {
			'outline-and-shadow': 'outline and shadow',
			'opaque-box': 'opaque box',
			'background-box': 'background box'
		}[m.subtitle_border_style];
		return [
			`${m.subtitle_font_size || 55} px`,
			(m.subtitle_color || '#FFFFFF').toUpperCase(),
			style,
			m.subtitle_bold ? 'bold' : ''
		]
			.filter(Boolean)
			.join(' · ');
	});

	const SUBTITLE_NUMBERS = [
		storeField('subtitle_font_size', 'Size', 'set-subtitle-size'),
		storeField('subtitle_position', 'Position', 'set-subtitle-position'),
		storeField('subtitle_margin_y', 'Margin', 'set-subtitle-margin')
	];
	const SUBTITLE_BACKGROUND = storeField(
		'subtitle_border_style',
		'Background',
		'set-subtitle-border',
		{
			input: 'w-full',
			options: [
				['outline-and-shadow', 'Outline & shadow'],
				['opaque-box', 'Opaque box'],
				['background-box', 'Background box']
			]
		}
	);
	const SUBTITLE_COLOURS = [
		storeField('subtitle_color', 'Text', 'set-subtitle-color'),
		storeField('subtitle_back_color', 'Box / shadow', 'set-subtitle-back-color')
	];
</script>

{#snippet playerItem(h: NonNullable<typeof selected>)}
	{@const status = h.is_active
		? activeState.label === 'Running'
			? nowOnPlayer.label
			: activeState.label
		: 'Not in use'}
	<button
		type="button"
		aria-current={h.id === selected?.id ? 'true' : undefined}
		class="block w-full rounded-sm px-2.5 py-2 text-left text-sm transition-colors
			{h.id === selected?.id ? 'bg-surface-2' : 'hover:bg-surface-2/50'}"
		onclick={() => (selectedId = h.id)}
	>
		<span class="flex items-center gap-2">
			<StatusLamp
				colour={h.is_active ? activeState.colour : 'neutral'}
				pending={h.is_active && activeState.pending}
			>
				<span class="sr-only">{h.is_active ? activeState.label : 'Not in use'}</span>
			</StatusLamp>
			<span class="min-w-0 truncate font-medium">{h.name}</span>
		</span>
		<span class="mt-0.5 block truncate pl-4 text-xs text-muted">{status}</span>
		{#if h.needs_pairing_again}<span class="mt-0.5 block pl-4 text-[0.7rem] text-warning"
				>Pair again</span
			>{:else if h.needs_update}<span class="mt-0.5 block pl-4 text-[0.7rem] text-warning"
				>Update</span
			>{:else if h.needs_cinefin_update}<span class="mt-0.5 block pl-4 text-[0.7rem] text-warning"
				>Update Cinefin</span
			>{:else if h.is_active}<span class="mt-0.5 block pl-4 text-[0.7rem] text-success">In use</span
			>{/if}
	</button>
{/snippet}

<SettingLists>
	{#if hosts.loading}
		<Spinner label="Loading playout…" />
	{:else if hosts.error}
		<ErrorState error={hosts.error} retry={() => void hosts.load()} />
	{:else}
		<SettingList
			title={hosts.data?.length ? 'Players' : 'Player'}
			text="Cinefin plays through one player at a time"
		>
			{#snippet actions()}
				{#if !hosts.data?.length}
					<Button size="sm" variant="primary" onclick={() => openWizard()}>
						<Plus size={13} /> Add a player
					</Button>
				{/if}
			{/snippet}
			{#if !hosts.data?.length}
				<div class="space-y-2 px-4 py-5 text-sm">
					<p class="font-medium">No player yet</p>
					<p class="text-muted">
						Cinefin plays through a player: the machine wired to your screen, running
						<code class="font-mono text-[0.8rem]">cinefin-playout</code>, whose screen shows a
						pairing code. Running mpv yourself? Add a player and choose a local mpv socket.
					</p>
				</div>
			{:else if selected}
				{@const isSocket = selected.kind === 'local_socket'}
				{@const isActive = selected.is_active}
				<!-- The players down the left; the one picked, and its settings, on the right. -->
				<div class="grid sm:grid-cols-[13.5rem_minmax(0,1fr)]">
					<nav
						aria-label="Players"
						class="flex flex-col gap-0.5 border-b border-border p-1.5 sm:border-r sm:border-b-0"
					>
						{#each [...hosts.data].sort((a, b) => Number(b.is_active) - Number(a.is_active)) as h (h.id)}
							{@render playerItem(h)}
						{/each}
						<button
							type="button"
							class="mt-1 flex items-center gap-2 rounded-sm px-2.5 py-2 text-left text-[0.8125rem] text-muted
								hover:bg-surface-2/50 hover:text-text sm:mt-auto"
							onclick={() => openWizard()}
						>
							<Plus size={13} /> Add a player
						</button>
					</nav>
					<div class="min-w-0">
						<div class="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 px-4 py-3.5">
							<h3 class="text-base font-semibold">{selected.name}</h3>
							<span class="min-w-0 truncate font-mono text-xs text-faint">
								{isSocket
									? `local mpv · ${selected.socket_path || '(no socket path)'}`
									: `${selected.agent_version ? `agent ${selected.agent_version} · ` : ''}${selected.base_url}`}
							</span>
						</div>
						{#if selected.needs_pairing_again || selected.needs_update || selected.needs_cinefin_update}
							<div class="border-t border-border p-3">
								{#if selected.needs_pairing_again}
									<Banner severity="warning" title="Needs pairing again.">
										This player was paired by an older Cinefin. Pair it again with the code on its
										screen; its name and settings are kept.
										{#snippet actions()}
											<Button
												size="sm"
												variant="primary"
												onclick={() =>
													openWizard({ base_url: selected.base_url, name: selected.name })}
											>
												Pair again
											</Button>
										{/snippet}
									</Banner>
								{:else if selected.needs_update}
									<Banner severity="warning" title="Update needed.">
										This player runs an older cinefin-playout, so it cannot hold standby or show the
										test card. Update it to the latest release, then refresh its status.
									</Banner>
								{:else}
									<Banner severity="warning" title="This player is newer than Cinefin.">
										It runs cinefin-playout {selected.agent_version || ''}, which no longer works
										with this Cinefin. Update Cinefin to the latest release, or install an older
										cinefin-playout on the player.
									</Banner>
								{/if}
							</div>
						{/if}

						{#if isActive}
							<SettingRow label="Control" hint="What it is doing now" summary={nowOnPlayer.detail}>
								{#snippet control()}
									<Button
										size="sm"
										disabled={mpvBusy !== null}
										title="Clear any loaded programme and put the player on standby"
										onclick={() => void goToStandby()}
									>
										<RotateCcw size={13} /> Standby
									</Button>
									{#if !isSocket && agentStatus?.reachable}
										{#if agentStatus.mpv_running}
											{#each MPV_ACTIONS as b (b.action)}
												<Button
													size="sm"
													disabled={mpvBusy !== null}
													onclick={() => controlMpv(b.action)}
												>
													<b.Icon size={13} />
													{b.label}
												</Button>
											{/each}
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
									{#if !isSocket}
										<Button
											size="sm"
											variant="ghost"
											disabled={refreshing}
											title="Ask the player for its status again"
											onclick={refreshActiveHost}
										>
											<RefreshCw size={13} /><span class="sr-only">Refresh status</span>
										</Button>
									{/if}
								{/snippet}
							</SettingRow>
						{:else}
							<SettingRow label="Not in use" summary="Cinefin plays through one player at a time.">
								{#snippet control()}
									<Button size="sm" variant="primary" onclick={() => activateHost(selected.id)}>
										<CircleCheck size={13} /> Use this player
									</Button>
								{/snippet}
							</SettingRow>
						{/if}

						{#if isSocket}
							<SettingRow
								label="Screen and sound"
								hint="Your mpv's own options"
								summary="Set when you launch mpv"
							/>
						{:else}
							{#key selected.id}
								<SettingRow
									label="Screen and sound"
									hint="Applies when it restarts"
									summary={configSummary}
								>
									<HostConfigPanel
										hostId={selected.id}
										hostName={selected.name}
										bind:summary={configSummary}
									/>
								</SettingRow>
							{/key}
							<SettingRow label="Status line on standby" hint="Name and connection, over the ident">
								{#snippet control()}
									<Switch
										label=""
										ariaLabel="Status line on standby"
										checked={selected.show_status ?? true}
										onchange={(on) => void setShowStatus(selected.id, on)}
									/>
								{/snippet}
							</SettingRow>
						{/if}

						<SettingRow
							label="Name and address"
							summary={!isSocket && !selected.has_token
								? 'Not paired: remove it and pair again'
								: 'Rename it, change its address, or remove it'}
						>
							{#snippet control()}
								<Button size="sm" variant="ghost" onclick={() => openHostDialog(selected)}>
									<Pencil size={13} /> Edit
								</Button>
								<Button
									size="sm"
									variant="danger"
									onclick={() => void removeHost(selected.id, selected.name)}
								>
									<Trash2 size={13} /> Remove
								</Button>
							{/snippet}
						</SettingRow>
					</div>
				</div>
			{/if}
		</SettingList>

		<SettingList title="Global" text="Around a programme, on whichever player is active">
			<SettingRow
				label="Standby ident"
				summary={`${ownIdent ? ownIdent.title : 'Built-in System Ident'}${ownIdent?.hold_point != null ? ` · held at ${ownIdent.hold_point}s` : ''}`}
			>
				<div class="max-w-xl space-y-4">
					<Field
						label="Ident"
						forId="set-default-ident"
						{store}
						field="default_cinema_ident"
						hint="Played once, then held on screen whenever no programme is playing."
					>
						<div class="flex gap-2">
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
							<Button
								disabled={standbyPreviewing || store.isDirty('default_cinema_ident')}
								title={store.isDirty('default_cinema_ident') ? 'Saving the new ident…' : undefined}
								onclick={previewStandby}
							>
								<MonitorPlay size={14} /> Preview standby
							</Button>
						</div>
					</Field>
					{#if ownIdent}
						{#key ownIdent.id}
							<Field
								label="Hold at"
								forId="set-ident-hold"
								hint="Seconds into {ownIdent.title} where standby freezes. Empty holds its last frame."
							>
								<div class="w-40">
									<Input
										id="set-ident-hold"
										type="number"
										value={ownIdent.hold_point == null ? '' : String(ownIdent.hold_point)}
										placeholder="Last frame"
										class="font-mono"
										onchange={(e) => void saveHoldPoint((e.target as HTMLInputElement).value)}
									/>
								</div>
							</Field>
						{/key}
					{/if}
				</div>
			</SettingRow>

			<SettingRow label="Subtitles" hint="Applied live" summary={subtitleSummary}>
				<div class="grid gap-6 lg:grid-cols-2">
					<div class="space-y-4">
						<div class="grid grid-cols-3 gap-3">
							{#each SUBTITLE_NUMBERS as f (f.id)}
								<StoreField {store} {...f} type="number" />
							{/each}
						</div>
						<StoreField {store} {...SUBTITLE_BACKGROUND} />
						<div class="grid grid-cols-2 gap-3">
							{#each SUBTITLE_COLOURS as f (f.id)}
								<StoreField
									{store}
									{...f}
									type="color"
									input="h-9 w-full rounded-md border border-border-strong bg-surface-2 px-1.5 text-sm text-text focus:border-accent-dim"
								/>
							{/each}
						</div>
						<div class="space-y-2.5">
							<StoreToggle {store} field="subtitle_use_margins" label="Keep inside the picture" />
							<StoreToggle {store} field="subtitle_bold" label="Bold" />
						</div>
					</div>
					<div>
						<p class="mb-1.5 text-xs font-medium text-muted">How they look</p>
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
			</SettingRow>

			<SettingRow
				label="Streaming address"
				mono={!!store.main.playout_server_url}
				summary={store.main.playout_server_url || "Cinefin's own address (CINEFIN_SERVER_URL)"}
			>
				<div class="max-w-xl">
					<StoreField
						{store}
						field="playout_server_url"
						label="Address"
						id="set-server-url"
						placeholder="http://cinefin.local:8000"
						input="font-mono"
						hint="Players stream everything from Cinefin at this address, so every player must reach it. Blank uses the CINEFIN_SERVER_URL default."
					/>
				</div>
			</SettingRow>
		</SettingList>
	{/if}
</SettingLists>

<Dialog bind:open={hostOpen} title={`Edit ${hName || 'host'}`}>
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

<Dialog
	bind:open={wizardOpen}
	title={wizardStart ? `Pair ${wizardStart.name} again` : 'Add a player'}
	size="4xl"
	flush
>
	{#if wizardOpen}
		<AddPlayerWizard
			start={wizardStart}
			onpaired={() => void reloadAll()}
			onfinish={onWizardFinish}
			oncancel={() => (wizardOpen = false)}
			compact
		/>
	{/if}
</Dialog>

<style>
	.subtitle-frame {
		container-type: size;
	}
</style>
