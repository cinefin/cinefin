<script lang="ts">
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
	import SectionTabs from './SectionTabs.svelte';
	import TabPanel from './TabPanel.svelte';
	import Toggle from '$lib/components/ui/Toggle.svelte';
	import StoreToggle from '$lib/settings/StoreToggle.svelte';
	import StoreField, { storeField } from '$lib/settings/StoreField.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	interface Props {
		store: SettingsStore;
		confirm: ConfirmDialog['confirm'];
	}
	let { store, confirm }: Props = $props();

	const TABS = [
		{ id: 'players', label: 'Players' },
		{ id: 'presentation', label: 'Presentation' }
	];
	let tab = $state('players');

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

	// Standby plays the saved ident (the button is off while the choice is unsaved).
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

{#snippet heading(title: string, text: string)}
	<div>
		<h3 class="text-sm font-medium">{title}</h3>
		<p class="mt-0.5 text-xs text-muted">{text}</p>
	</div>
{/snippet}

<div class="space-y-4">
	{#if hosts.loading}
		<Spinner label="Loading playout…" />
	{:else if hosts.error}
		<ErrorState error={hosts.error} retry={() => void hosts.load()} />
	{:else}
		<SectionTabs tabs={TABS} bind:value={tab} label="Playout settings" prefix="pt" />

		{#if tab === 'players'}
			<TabPanel prefix="pt" tab="players" class="mt-4">
				{#if !hosts.data?.length}
					<section class="max-w-2xl space-y-4">
						<div>
							<h3 class="text-base font-medium">Add your first player</h3>
							<p class="mt-1 text-sm text-muted">
								Cinefin plays through a player: the machine wired to your screen, running
								<code class="font-mono text-[0.8rem]">cinefin-playout</code>. Its screen shows a
								pairing code.
							</p>
						</div>
						<Button variant="primary" onclick={() => openWizard()}>
							<Plus size={14} /> Add a player
						</Button>
						<p class="border-t border-border pt-3 text-xs text-muted">
							Running mpv yourself? Add a player and choose a local mpv socket.
						</p>
					</section>
				{:else}
					<div class="grid gap-6 md:grid-cols-[13rem_minmax(0,1fr)]">
						<nav aria-label="Players" class="flex flex-col gap-1">
							{#each hosts.data as h (h.id)}
								{@const on = selected?.id === h.id}
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
									{#if h.needs_pairing_again}<span class="text-[0.7rem] text-warning"
											>Pair again</span
										>{:else if h.needs_update}<span class="text-[0.7rem] text-warning">Update</span
										>{:else if h.is_active}<span class="text-[0.7rem] text-success">Active</span
										>{/if}
								</button>
							{/each}
							<div class="my-2 h-px bg-border"></div>
							<button
								type="button"
								class="flex items-center gap-2 px-3 py-2 text-left text-sm text-muted hover:bg-surface-2"
								onclick={() => openWizard()}
							>
								<Plus size={14} /> Add a player
							</button>
						</nav>

						<div class="min-w-0">
							{#if selected}
								{@const isSocket = selected.kind === 'local_socket'}
								{@const isActive = selected.is_active}
								<div class="space-y-5">
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

										{#if selected.needs_pairing_again}
											<Banner severity="warning" title="Needs pairing again.">
												This player was paired by an older Cinefin. Pair it again with the code on
												its screen; its name and settings are kept.
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
												This player runs an older cinefin-playout, so it cannot hold standby or show
												the test card. Update it to the latest release, then refresh its status.
											</Banner>
										{/if}

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

									<section class="border border-border bg-surface-1">
										<div class="px-4 pt-4">
											{@render heading(
												'Screen and sound',
												isSocket
													? 'You run this mpv, so set its screen and sound with its own options when you launch it.'
													: 'Applies when the player restarts.'
											)}
										</div>
										{#if !isSocket}
											{#key selected.id}
												<HostConfigPanel hostId={selected.id} />
											{/key}
										{:else}
											<div class="pb-4"></div>
										{/if}
									</section>

									{#if !isSocket}
										<section class="border border-border bg-surface-1 p-4">
											<Toggle
												label="Show the status line on standby"
												checked={selected.show_status ?? true}
												hint="The cinema name, this player's name and its connection, over the ident."
												onchange={(e) =>
													void setShowStatus(selected.id, (e.target as HTMLInputElement).checked)}
											/>
										</section>
									{/if}

									<section class="flex items-center gap-3 border-t border-border pt-4">
										<div class="mr-auto">
											{@render heading(
												'Remove this player',
												isSocket
													? 'Cinefin stops using this mpv.'
													: 'It forgets this Cinefin and shows a pairing code again.'
											)}
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
			</TabPanel>
		{:else if tab === 'presentation'}
			<TabPanel prefix="pt" tab="presentation" class="mt-4 space-y-6">
				<p class="-mt-1 text-sm text-muted">These apply to every player.</p>

				<section class="space-y-3 border border-border bg-surface-1 p-4">
					{@render heading(
						'Idle screen',
						'Standby: played once, then held on screen whenever no programme is playing.'
					)}
					<Field label="Ident" forId="set-default-ident" {store} field="default_cinema_ident">
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
							<Button
								disabled={standbyPreviewing || store.isDirty('default_cinema_ident')}
								title={store.isDirty('default_cinema_ident')
									? 'Save to preview this ident'
									: undefined}
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
				</section>

				<section class="space-y-4 border border-border bg-surface-1 p-4">
					{@render heading('Subtitles', 'Applied live when you save, no restart.')}
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

				<section class="space-y-3 border border-border bg-surface-1 p-4">
					<div>
						<h3 class="text-sm font-medium">Streaming address</h3>
						<p class="mt-0.5 text-xs text-muted">
							Players stream everything from Cinefin at this address, so every player must reach it.
							Blank uses the <code class="font-mono">CINEFIN_SERVER_URL</code> default.
						</p>
					</div>
					<StoreField
						{store}
						field="playout_server_url"
						label="Address"
						id="set-server-url"
						placeholder="http://cinefin.local:8000"
						input="max-w-xl font-mono"
					/>
				</section>
			</TabPanel>
		{/if}
	{/if}
</div>

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
