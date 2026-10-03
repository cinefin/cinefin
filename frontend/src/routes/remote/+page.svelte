<script lang="ts">
	import PageHeader from '$lib/components/shell/PageHeader.svelte';
	// Remote — the operator console. The status (phase, what is on screen, the allowed
	// actions) is the shared playout feed read through $lib/playout/phase; the mpv store
	// only adds the player's own settings (volume, speed, tracks, technical info), and the
	// playlist store the running order. Commands are the ones picked on this device.
	import { base } from '$app/paths';
	import {
		Captions,
		Cpu,
		Disc3,
		Gauge,
		Headphones,
		ListOrdered,
		Maximize,
		ScanSearch,
		Pause,
		Play,
		RotateCcw,
		RotateCw,
		Settings,
		SkipBack,
		SkipForward,
		Square,
		SquareTerminal,
		Volume1,
		Volume2,
		VolumeX
	} from '@lucide/svelte';
	import { api } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import CommandPad from '$lib/commands/CommandPad.svelte';
	import { showToast as toast } from '$lib/toast.svelte';
	import { formatClock, formatTime } from '$lib/format';
	import { itemTypeDisplay } from '$lib/item-types';
	import OnScreen from '$lib/playout/OnScreen.svelte';
	import RunningOrder from '$lib/playout/RunningOrder.svelte';
	import { can, primaryAction, started } from '$lib/playout/phase';
	import { playout, type ControlBody } from '$lib/stores/playout.svelte';
	import { mpv, playlist, type PlayoutPlaylistItem } from '$lib/stores/player.svelte';
	import { playoutReach } from '$lib/stores/playoutReach.svelte';
	import type { components } from '$lib/api/types.gen';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import Cued from '$lib/remote/Cued.svelte';
	import Standby from '$lib/remote/Standby.svelte';
	import ManualQueue from '$lib/remote/ManualQueue.svelte';
	import ManualSearch from '$lib/remote/ManualSearch.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	type Track = components['schemas']['TrackSchema'];

	/** PlaylistUtils.build_playlist_item_details metadata, per item type. */
	interface ItemMeta {
		year?: number | string;
		certification?: string;
		director?: string;
		resolution?: string;
		genres?: string[];
		thumbnail_url?: string;
		movie_title?: string;
		trailer_title?: string;
		bumper_title?: string;
	}

	$effect(() => playout.subscribe());
	$effect(() => mpv.subscribe());
	$effect(() => playlist.subscribe());
	$effect(() => playoutReach.subscribe()); // the player's address when it is offline

	// Pre-flight warnings stashed by the programme page's "Cue & open console".
	try {
		const raw = sessionStorage.getItem('playout:preflightWarnings');
		if (raw) {
			sessionStorage.removeItem('playout:preflightWarnings');
			const warnings: unknown = JSON.parse(raw);
			if (Array.isArray(warnings) && warnings.length) {
				toast(
					`${warnings.length} item${warnings.length === 1 ? ' is' : 's are'} unreachable and will be skipped: ` +
						warnings.slice(0, 3).join('; ') +
						(warnings.length > 3 ? '…' : ''),
					'warning'
				);
			}
		}
	} catch {
		// Stale/corrupt handoff — ignore.
	}

	const status = $derived(playout.status);
	const phase = $derived(status?.phase);
	const connected = $derived(!!status && phase !== 'offline');
	const programme = $derived(status?.programme ?? null);
	const primary = $derived(primaryAction(status));
	const holding = $derived(phase === 'hold');
	const st = $derived(mpv.status);
	const pb = $derived(st?.status ?? null);
	const mpvPos = $derived(status?.playlist?.mpv_position ?? null);

	// Manual mode: one-off items the player holds outside any programme (server-side queue).
	const manual = $derived(status?.manual ?? null);
	const manualCurrent = $derived(manual?.items[manual.position ?? -1] ?? null);
	/** Something plays under the operator's hand: the transport and tracks apply. */
	const playing = $derived(started(status) || !!manual);
	let mode = $state<'programme' | 'manual'>('programme');
	// Follow the player: manual play shows the manual tab, a (newly) loaded programme the programme tab.
	const programmeId = $derived(programme?.id ?? null);
	$effect(() => {
		if (manual) mode = 'manual';
	});
	$effect(() => {
		if (programmeId != null) mode = 'programme';
	});
	function refreshPlayer() {
		void mpv.refresh();
		void playout.refresh();
		playlist.refresh();
	}

	const items = $derived((playlist.data?.playlist ?? []) as PlayoutPlaylistItem[]);
	const offset = $derived(status?.playlist?.offset ?? 0);
	// The trailing "system" item is the end-of-programme black sentinel, and entry 0 is
	// standby, which the programme never replays: hide both.
	const visibleItems = $derived(
		items.filter((it) => it.type !== 'system' && (it.programme_position != null || it.index > 0))
	);
	const programmeItems = $derived(
		visibleItems
			.filter((it) => it.programme_position != null)
			.slice()
			.sort((a, b) => a.programme_position! - b.programme_position!)
	);
	const programmeCount = $derived(programmeItems.length);
	const current = $derived(items.find((it) => it.index === mpvPos));

	// The item's clock (a hold's own dwell during a hold) and the programme's, from the status.
	const live = $derived(status?.playback ?? null);
	const itemTime = $derived(live?.position ?? 0);
	const itemDuration = $derived((live?.duration || current?.duration) ?? 0);
	const itemPct = $derived(itemDuration > 0 ? Math.min(100, (itemTime / itemDuration) * 100) : 0);
	const programmeTotal = $derived(status?.playlist?.programme_total_duration ?? 0);
	const programmeRemaining = $derived(status?.playlist?.programme_remaining_time ?? 0);

	function fileName(path: string | null | undefined): string {
		if (!path) return '';
		// Stream URLs carry a ?t= token and a trailing slash — strip both.
		return path.split('?')[0].replace(/\/$/, '').split('/').pop() || path;
	}

	function itemTitle(item: PlayoutPlaylistItem): string {
		const meta = (item.details?.metadata ?? {}) as ItemMeta;
		// A pre-show entry (before the programme's first item) is the title card.
		if (item.programme_position == null) return 'Title card';
		return (
			item.title ||
			meta.movie_title ||
			meta.trailer_title ||
			meta.bumper_title ||
			fileName(item.file) ||
			'Untitled'
		);
	}

	const npMeta = $derived((current?.details?.metadata ?? {}) as ItemMeta);
	const npType = $derived(status?.current_item?.type || current?.type || 'item');
	const npTitle = $derived(status?.current_item?.title || status?.screen || '');
	const facts = $derived(
		[
			npMeta.year,
			npMeta.certification,
			current?.duration ? formatTime(current.duration) : null,
			npMeta.resolution
		].filter(Boolean)
	);

	const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];
	let volume = $state(100);
	let volDragging = $state(false);
	$effect(() => {
		if (!volDragging && pb?.volume != null) volume = Math.round(pb.volume);
	});
	const muted = $derived(!!pb?.muted);
	const currentSpeed = $derived(pb?.speed ?? 1);
	// Fill: mpv's panscan zooms a wider-than-16:9 film (DCI 1.9:1) until it fills
	// the screen, cropping a sliver off each side instead of showing thin bars.
	const filling = $derived((pb?.panscan ?? 0) > 0.5);
	const VolumeIcon = $derived(muted || volume === 0 ? VolumeX : volume < 50 ? Volume1 : Volume2);

	let starting = $state(false);
	let confirmDlg = $state<ConfirmDialog>();

	async function mpvCommand(command: string, args: (string | number)[] = []): Promise<void> {
		await mutate(api.POST('/api/v2/mpv/command', { body: { command, args } }));
	}

	async function setProperty(property: string, value: string | number): Promise<void> {
		await mutate(
			api.POST('/api/v2/mpv/property/{property_name}', {
				params: { path: { property_name: property } },
				body: { value }
			})
		);
	}

	// Every transport button: one server path, which refuses what the phase doesn't allow.
	async function act(body: ControlBody, failed: string): Promise<void> {
		try {
			await playout.control(body);
			playlist.refresh();
		} catch (err) {
			toast(`${failed}: ${(err as Error).message}`, 'error');
		}
	}

	async function runProgramme(): Promise<void> {
		if (starting) return;
		starting = true;
		await act({ action: 'start' }, 'Failed to start the programme');
		starting = false;
	}

	async function end(): Promise<void> {
		const question = manual
			? 'End manual play? The queue is cleared and the player goes to standby.'
			: 'End the programme? The running order is cleared and the player goes to standby.';
		if (!(await confirmDlg?.confirm(question, { confirmLabel: manual ? 'End' : 'End programme' })))
			return;
		await act({ action: 'end' }, 'Failed to end');
	}

	// Put the player on standby. Works whenever the player is
	// connected — a recovery for a stale or fiddled screen — and confirms first
	// only when it would clear a show that's on air.
	async function goToStandby(): Promise<void> {
		if (programme) {
			if (
				!(await confirmDlg?.confirm(
					`"${programme.name}" is on the player. Go to standby and clear it?`,
					{ confirmLabel: 'Go to standby' }
				))
			)
				return;
		}
		try {
			await mutate(api.POST('/api/v2/playout/reset'));
			toast('The player is on standby', 'info');
			refreshPlayer();
		} catch (err) {
			toast(`Failed to reset the player: ${(err as Error).message}`, 'error');
		}
	}

	async function toggleFill(): Promise<void> {
		try {
			await setProperty('panscan', filling ? 0 : 1);
			void mpv.refresh();
		} catch (err) {
			toast(`Fill toggle failed: ${(err as Error).message}`, 'error');
		}
	}

	async function toggleFullscreen(): Promise<void> {
		try {
			await mpvCommand('cycle', ['fullscreen']);
		} catch (err) {
			toast(`Fullscreen toggle failed: ${(err as Error).message}`, 'error');
		}
	}

	async function setVolume(value: number): Promise<void> {
		try {
			await setProperty('volume', value);
		} catch (err) {
			toast(`Volume change failed: ${(err as Error).message}`, 'error');
		}
	}

	async function toggleMute(): Promise<void> {
		try {
			await mpvCommand('cycle', ['mute']);
			void mpv.refresh();
		} catch (err) {
			toast(`Mute toggle failed: ${(err as Error).message}`, 'error');
		}
	}

	async function setSpeed(speed: number): Promise<void> {
		try {
			await setProperty('speed', speed);
			void mpv.refresh();
		} catch (err) {
			toast(`Speed change failed: ${(err as Error).message}`, 'error');
		}
	}

	async function selectTrack(type: 'audio' | 'sub', id: number | 'no'): Promise<void> {
		try {
			await setProperty(type === 'audio' ? 'aid' : 'sid', id);
			void mpv.refresh();
		} catch (err) {
			toast(`Track selection failed: ${(err as Error).message}`, 'error');
		}
	}

	let itemTrackEl = $state<HTMLDivElement>();
	let dragPct = $state<number | null>(null);

	function trackPct(e: PointerEvent, el: HTMLElement): number {
		const rect = el.getBoundingClientRect();
		return Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
	}

	function onItemTrackDown(e: PointerEvent) {
		if (!itemTrackEl || !can(status, 'seek')) return;
		itemTrackEl.setPointerCapture(e.pointerId);
		dragPct = trackPct(e, itemTrackEl);
	}

	function onItemTrackMove(e: PointerEvent) {
		if (dragPct == null || !itemTrackEl) return;
		dragPct = trackPct(e, itemTrackEl);
	}

	async function onItemTrackUp(e: PointerEvent) {
		if (dragPct == null || !itemTrackEl) return;
		const pct = trackPct(e, itemTrackEl);
		dragPct = pct;
		await act({ action: 'seek', seconds: (pct / 100) * itemDuration }, 'Seek failed');
		dragPct = null;
	}

	// Open state is seeded ONCE from the breakpoint, then user-controlled via bind:open.
	// It must NOT be a reactive `open={...}`: that re-asserts on every status re-render,
	// snapping shut a panel the operator just opened (the "resets every second" bug).
	const startCollapsed =
		typeof window !== 'undefined' && window.matchMedia('(max-width: 639px)').matches;
	let tracksOpen = $state(!startCollapsed);
	let commandsOpen = $state(!startCollapsed);
	let upNextOpen = $state(!startCollapsed);

	const audioTracks = $derived((st?.tracks?.audio_tracks ?? []) as Track[]);
	const subTracks = $derived((st?.tracks?.sub_tracks ?? []) as Track[]);
	const subOffActive = $derived(!subTracks.some((t) => t.selected));

	function trackLabel(t: Track, i: number, kind: 'Audio' | 'Subtitle'): string {
		return t.title || (t.language ? t.language.toUpperCase() : '') || `${kind} ${i + 1}`;
	}

	const video = $derived(st?.video ?? null);
	const audioTech = $derived(st?.audio ?? null);
	const hasTech = $derived(!!(video?.width && video?.height) || !!audioTech?.codec);
	const techRows = $derived.by((): { section: string; rows: [string, string][] }[] => [
		{
			section: 'Video',
			rows: [
				['Resolution', video?.width && video?.height ? `${video.width}×${video.height}` : '--'],
				['Frame rate', video?.fps != null ? `${Number(video.fps).toFixed(3)} fps` : '--'],
				['Codec', video?.codec || '--'],
				['Pixel format', video?.pixelformat || '--'],
				['Color space', video?.colormatrix || '--'],
				['Primaries', video?.primaries || '--'],
				['HW decode', video?.hw_decoding || 'none']
			]
		},
		{
			section: 'Audio',
			rows: [
				['Codec', audioTech?.codec || '--'],
				['Channels', audioTech?.channels || '--'],
				['Sample rate', audioTech?.samplerate ? `${audioTech.samplerate} Hz` : '--']
			]
		}
	]);

	// While a programme item is on air its start is `now − position` and later rows add
	// durations forward. When nothing is on air, starts project forward from "now" (~ marked).
	const startTimes = $derived.by(() => {
		let anchorAt = 0;
		let projected = true;
		if (started(status) && mpvPos != null) {
			const cur = programmeItems.findIndex((it) => it.index === mpvPos);
			if (cur >= 0) {
				anchorAt = cur;
				projected = false;
			}
		}
		const anchorMs = projected ? Date.now() : Date.now() - itemTime * 1000;
		const starts = new Map<number, number | null>();
		let t = anchorMs;
		programmeItems.forEach((it, i) => {
			if (i < anchorAt) {
				starts.set(it.index, null);
				return;
			}
			starts.set(it.index, t);
			t += (it.duration || 0) * 1000;
		});
		return { starts, projected };
	});

	let timelineEl = $state<HTMLDivElement>();
	let lastScrolled: number | null = null;
	$effect(() => {
		const pos = mpvPos;
		if (pos == null || !timelineEl || lastScrolled === pos) return;
		lastScrolled = pos;
		timelineEl
			.querySelector(`[data-index="${pos}"]`)
			?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
	});

	function hideBrokenImage(e: Event) {
		(e.currentTarget as HTMLImageElement).style.display = 'none';
	}
</script>

<PageHeader title="Remote" />

{#snippet itemBar()}
	<div>
		<div
			bind:this={itemTrackEl}
			class="group relative h-2.5 touch-none {can(status, 'seek') ? 'cursor-pointer' : ''}"
			role="slider"
			aria-label="Seek within the current item"
			aria-valuemin={0}
			aria-valuemax={100}
			aria-valuenow={Math.round(dragPct ?? itemPct)}
			tabindex="-1"
			onpointerdown={onItemTrackDown}
			onpointermove={onItemTrackMove}
			onpointerup={(e) => void onItemTrackUp(e)}
		>
			<div class="absolute inset-0 bg-surface-3">
				<div
					class="h-full {holding ? 'bg-live' : itemTypeDisplay(npType).classes.bar} {dragPct == null
						? 'fill-smooth'
						: ''}"
					style="width: {(dragPct ?? itemPct).toFixed(2)}%"
				></div>
			</div>
		</div>
		<div class="mt-1.5 flex items-baseline justify-between font-mono text-xs text-muted">
			<span>{formatTime(itemTime)}</span>
			<span class="text-faint">{holding ? 'Command hold' : ''}</span>
			<span>-{formatTime(Math.max(0, itemDuration - itemTime))}</span>
		</div>
	</div>
{/snippet}

{#snippet transport()}
	<div class="mx-auto grid max-w-md grid-cols-5 items-center gap-2">
		<button
			type="button"
			class="tbtn"
			title="Previous item"
			aria-label="Previous item"
			disabled={!can(status, 'previous')}
			onclick={() => void act({ action: 'previous' }, 'Navigation failed')}
		>
			<SkipBack size={20} />
		</button>
		<button
			type="button"
			class="tbtn"
			title="Back 10 seconds"
			aria-label="Back 10 seconds"
			disabled={!can(status, 'seek')}
			onclick={() => void act({ action: 'seek', offset: -10 }, 'Seek failed')}
		>
			<RotateCcw size={18} /><span class="tbtn-num">10s</span>
		</button>
		<button
			type="button"
			class="tbtn tbtn-primary h-16"
			title={primary.label}
			aria-label={primary.label}
			disabled={!primary.enabled}
			onclick={() => void act({ action: primary.action }, 'Playback control failed')}
		>
			{#if primary.action === 'pause'}<Pause size={24} />{:else}<Play size={24} />{/if}
		</button>
		<button
			type="button"
			class="tbtn"
			title="Forward 10 seconds"
			aria-label="Forward 10 seconds"
			disabled={!can(status, 'seek')}
			onclick={() => void act({ action: 'seek', offset: 10 }, 'Seek failed')}
		>
			<RotateCw size={18} /><span class="tbtn-num">10s</span>
		</button>
		{#if holding}
			<button
				type="button"
				class="tbtn text-xs"
				title="End the command's hold and move on"
				disabled={!can(status, 'end_hold')}
				onclick={() => void act({ action: 'end_hold' }, 'Navigation failed')}
			>
				End hold
			</button>
		{:else}
			<button
				type="button"
				class="tbtn"
				title="Next item"
				aria-label="Next item"
				disabled={!can(status, 'next')}
				onclick={() => void act({ action: 'next' }, 'Navigation failed')}
			>
				<SkipForward size={20} />
			</button>
		{/if}
	</div>
{/snippet}

{#snippet endButton()}
	<Button variant="danger" class="w-full" disabled={!can(status, 'end')} onclick={() => void end()}>
		<Square size={12} />
		{manual ? 'End manual play' : 'End programme'}
	</Button>
{/snippet}

<ConfirmDialog bind:this={confirmDlg} title="End programme?" />

<div class="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
	<div class="min-w-0 space-y-4">
		<Tabs
			tabs={[
				{ id: 'programme', label: 'Programme' },
				{ id: 'manual', label: 'Manual' }
			]}
			value={mode}
			onselect={(id) => (mode = id as typeof mode)}
			label="Playout mode"
		/>

		{#if !status}
			<Spinner label="Connecting to the player…" />
		{:else if phase === 'offline'}
			<section class="panel max-w-xl space-y-3 p-4">
				<p class="font-mono text-xs text-faint">{status.player?.name ?? 'Player'}</p>
				<p class="text-lg font-semibold">{status.label}</p>
				<p class="text-sm text-muted">
					{status.player
						? `Can't reach the player${playoutReach.hostUrl ? ` at ${playoutReach.hostUrl}` : ''}. Retrying every few seconds${status.player.kind === 'agent' ? '; the player shows its own standby meanwhile' : ''}.`
						: 'Add a player to put programmes on screen.'}
				</p>
				<Button href="{base}/settings?tab=playout" size="sm">
					<Settings size={13} /> Player settings
				</Button>
			</section>
		{:else if mode === 'manual'}
			{#if manual}
				<section class="panel panel-lifted max-w-xl space-y-4 p-4">
					<div>
						<p class="font-mono text-xs text-faint">
							Manual{manual.position != null
								? ` · ${manual.position + 1} of ${manual.items.length}`
								: ''}
						</p>
						<h2 class="mt-1 text-xl leading-tight font-semibold sm:text-2xl">
							{manualCurrent?.title ?? 'Starting…'}
						</h2>
					</div>
					{@render itemBar()}
					{@render transport()}
					{@render endButton()}
				</section>
			{/if}
		{:else if phase === 'standby'}
			<Standby {status} oncued={refreshPlayer} />
		{:else if phase === 'cued'}
			<Cued {status} {starting} onstart={() => void runProgramme()} onend={() => void end()} />
		{:else if programme}
			{@const typeInfo = itemTypeDisplay(npType)}
			<section class="panel panel-lifted max-w-xl space-y-4 p-4">
				<div>
					<p class="truncate text-sm text-muted">
						{programme.name} · {status.current_item && status.current_item.position >= 0
							? `${status.current_item.position + 1} of ${status.playlist?.total_items ?? 0}`
							: 'Pre-show'}
					</p>
					<h2
						class="mt-1 flex items-baseline gap-2 text-xl leading-tight font-semibold sm:text-2xl"
					>
						{#if npType !== 'title'}
							<span class="shrink-0 text-sm font-medium {typeInfo.classes.icon}">
								{holding ? 'Hold' : typeInfo.short}
							</span>
						{/if}
						<span class="min-w-0 truncate">{npTitle}</span>
					</h2>
					{#if facts.length}
						<p class="mt-1 font-mono text-xs text-faint">{facts.join(' · ')}</p>
					{/if}
				</div>

				<OnScreen {status} class="aspect-[12/5]" />
				{@render itemBar()}
				{@render transport()}

				<div class="space-y-2 border border-border bg-surface-1 p-3">
					<p class="font-mono text-xs text-faint">Whole programme</p>
					<RunningOrder
						{status}
						items={playlist.data?.playlist ?? []}
						onjump={(index) => void act({ action: 'jump', index }, 'Jump failed')}
					/>
					<p class="flex justify-between text-sm text-muted">
						<span>
							{#if phase === 'preshow'}
								Programme starts in <span class="font-mono">{formatTime(live?.remaining ?? 0)}</span
								>
							{:else if programmeTotal > 0}
								Ends <span class="font-mono"
									>{formatClock(new Date(Date.now() + programmeRemaining * 1000))}</span
								>
							{/if}
						</span>
						<span>Then standby</span>
					</p>
				</div>
				{@render endButton()}
			</section>
		{/if}

		{#if connected}
			<section class="panel p-4">
				<div class="flex flex-wrap items-center gap-x-4 gap-y-3">
					<div class="flex min-w-40 flex-1 items-center gap-2">
						<button
							type="button"
							class="rounded-sm p-1.5 text-muted hover:bg-surface-2 hover:text-text"
							title={muted ? 'Unmute' : 'Mute'}
							aria-label={muted ? 'Unmute' : 'Mute'}
							onclick={() => void toggleMute()}
						>
							<VolumeIcon size={16} />
						</button>
						<input
							type="range"
							class="min-w-24 flex-1 accent-(--color-accent)"
							min="0"
							max="100"
							bind:value={volume}
							oninput={() => {
								volDragging = true;
								void setVolume(volume);
							}}
							onchange={() => (volDragging = false)}
							aria-label="Volume"
						/>
						<span class="w-9 text-right font-mono text-xs text-muted">{volume}%</span>
					</div>

					{#if playing}
						<label class="flex items-center gap-1.5 text-xs text-muted" title="Playback speed">
							<Gauge size={14} class="shrink-0" />
							<span class="sr-only">Playback speed</span>
							<select
								class="speed-select"
								value={String(currentSpeed)}
								onchange={(e) =>
									void setSpeed(parseFloat((e.currentTarget as HTMLSelectElement).value))}
							>
								{#each SPEEDS as speed (speed)}
									<option value={String(speed)}>{speed}×</option>
								{/each}
							</select>
						</label>
					{/if}

					<div class="ml-auto flex items-center gap-2">
						<Button
							size="sm"
							variant={filling ? 'primary' : undefined}
							title={filling
								? 'Filling the screen: wide films are cropped at the sides. Click to show the whole picture'
								: 'Zoom to fill the screen, removing thin bars on wide (DCI) films'}
							onclick={() => void toggleFill()}
						>
							<ScanSearch size={13} /> Fill
						</Button>
						<Button size="sm" title="Toggle fullscreen" onclick={() => void toggleFullscreen()}>
							<Maximize size={13} />
						</Button>
						<Button size="sm" title="Put the player on standby" onclick={() => void goToStandby()}>
							<RotateCcw size={13} /> Standby
						</Button>
					</div>
				</div>
			</section>
		{/if}

		{#if mode === 'manual'}
			<ManualSearch
				onchanged={refreshPlayer}
				confirmEnd={(msg) =>
					confirmDlg!.confirm(`${msg}. End it and play this instead?`, {
						confirmLabel: 'End and play'
					})}
			/>
		{/if}

		{#if playing}
			<details class="panel" bind:open={tracksOpen}>
				<summary class="phone-summary sm:hidden">
					<span class="inline-flex items-center gap-1.5"><Headphones size={13} /> Tracks</span>
				</summary>
				<div class="grid grid-cols-2 gap-3 p-4">
					<div class="min-w-0">
						<p class="panel-label"><Headphones size={12} /> Audio</p>
						<div class="track-col mt-1.5">
							{#if !audioTracks.length}
								<span class="text-xs text-faint">No audio tracks</span>
							{:else}
								{#each audioTracks as track, i (track.id)}
									<button
										type="button"
										class="seg seg-block {track.selected ? 'seg-on' : ''}"
										disabled={!connected}
										onclick={() => void selectTrack('audio', track.id)}
										title={trackLabel(track, i, 'Audio')}
									>
										{trackLabel(track, i, 'Audio')}
									</button>
								{/each}
							{/if}
						</div>
					</div>
					<div class="min-w-0">
						<p class="panel-label"><Captions size={12} /> Subtitles</p>
						<div class="track-col mt-1.5">
							<button
								type="button"
								class="seg seg-block {subOffActive ? 'seg-on' : ''}"
								disabled={!connected}
								onclick={() => void selectTrack('sub', 'no')}
							>
								Off
							</button>
							{#each subTracks as track, i (track.id)}
								<button
									type="button"
									class="seg seg-block {track.selected ? 'seg-on' : ''}"
									disabled={!connected}
									onclick={() => void selectTrack('sub', track.id)}
									title={trackLabel(track, i, 'Subtitle')}
								>
									{trackLabel(track, i, 'Subtitle')}
								</button>
							{/each}
						</div>
					</div>
				</div>
			</details>
		{/if}

		<details class="panel" bind:open={commandsOpen}>
			<summary class="phone-summary sm:hidden">
				<span class="inline-flex items-center gap-1.5">
					<SquareTerminal size={13} /> Commands
				</span>
			</summary>
			<div class="p-4">
				<CommandPad surface="remote" variant="grid">
					{#snippet label()}
						<span class="panel-label hidden sm:flex"><SquareTerminal size={12} /> Commands</span>
					{/snippet}
				</CommandPad>
			</div>
		</details>

		{#if hasTech}
			<details class="panel">
				<summary
					class="cursor-pointer px-4 py-2.5 text-[0.8rem] font-medium text-muted select-none"
				>
					<span class="inline-flex items-center gap-1.5"><Cpu size={13} /> Technical info</span>
				</summary>
				<div class="grid gap-x-8 gap-y-4 border-t border-border p-4 sm:grid-cols-2">
					{#each techRows as group (group.section)}
						<div>
							<h4 class="mb-1.5 text-xs text-faint">{group.section}</h4>
							<dl class="space-y-1 text-sm">
								{#each group.rows as [label, value] (label)}
									<div class="flex justify-between gap-3">
										<dt class="text-muted">{label}</dt>
										<dd class="truncate font-mono text-xs leading-5">{value}</dd>
									</div>
								{/each}
							</dl>
						</div>
					{/each}
				</div>
			</details>
		{/if}
	</div>

	{#if mode === 'manual'}
		<div class="min-w-0 xl:sticky xl:top-[4.5rem]">
			<ManualQueue
				items={manual?.items ?? []}
				position={manual?.position ?? null}
				onchanged={refreshPlayer}
			/>
		</div>
	{:else if programme}
		<details class="panel min-w-0 xl:sticky xl:top-[4.5rem]" bind:open={upNextOpen}>
			<summary class="phone-summary sm:hidden">
				<span class="inline-flex items-center gap-1.5"><ListOrdered size={13} /> Rundown</span>
				<span class="ml-3 font-mono text-xs text-muted">
					{programmeCount} item{programmeCount === 1 ? '' : 's'}
				</span>
			</summary>
			<header
				class="hidden items-center justify-between gap-3 border-b border-border px-4 py-2.5 sm:flex"
			>
				<p class="panel-label"><ListOrdered size={13} /> Rundown</p>
				<span class="font-mono text-xs text-muted">
					{programmeCount} item{programmeCount === 1 ? '' : 's'}
				</span>
			</header>

			<div
				bind:this={timelineEl}
				class="max-h-[70vh] overflow-y-auto xl:max-h-[calc(100dvh-10rem)]"
			>
				{#if !visibleItems.length}
					<EmptyState icon={Disc3} title="No playlist loaded" compact />
				{:else}
					{#each visibleItems as item (item.index)}
						{@const preshow = item.programme_position == null}
						{@const rowType = preshow ? 'title' : item.type || 'item'}
						{@const rowTypeInfo = itemTypeDisplay(rowType)}
						{@const RowIcon = rowTypeInfo.icon}
						{@const meta = (item.details?.metadata ?? {}) as ItemMeta}
						{@const rowTitle = itemTitle(item)}
						{@const sub = preshow
							? 'Pre-show'
							: [meta.year, meta.certification].filter(Boolean).join(' · ')}
						{@const artUrl =
							rowType === 'movie' || rowType === 'feature' || rowType === 'trailer'
								? meta.thumbnail_url || ''
								: ''}
						{@const isCurrent = item.index === mpvPos}
						{@const played = mpvPos != null && item.index < mpvPos}
						{@const startMs = startTimes.starts.get(item.index)}
						<button
							type="button"
							data-index={item.index}
							title={item.file || ''}
							disabled={!can(status, 'jump')}
							onclick={() => void act({ action: 'jump', index: item.index }, 'Jump failed')}
							class="relative flex w-full items-center gap-2.5 border-b border-border px-3 py-2 text-left transition-colors last:border-b-0 enabled:hover:bg-surface-2
							{rowTypeInfo.classes.edge}
							{isCurrent ? 'bg-surface-2' : ''}
							{played ? 'opacity-45' : ''}"
						>
							{#if isCurrent}
								<span class="absolute inset-y-0 left-0 w-0.5 bg-accent"></span>
							{/if}
							<span class="w-5 shrink-0 text-center font-mono text-xs text-faint">
								{item.programme_position != null ? item.programme_position + 1 : '·'}
							</span>
							<span
								class="relative flex h-12 w-8 shrink-0 items-center justify-center overflow-hidden rounded-xs border border-border bg-surface-2"
							>
								<RowIcon size={13} class={rowTypeInfo.classes.icon} aria-hidden="true" />
								{#if artUrl}
									<img
										src={artUrl}
										alt=""
										loading="lazy"
										class="absolute inset-0 h-full w-full object-cover"
										onerror={hideBrokenImage}
									/>
								{/if}
							</span>
							<span class="min-w-0 flex-1">
								<span class="block truncate text-sm {isCurrent ? 'text-accent' : ''}"
									>{rowTitle}</span
								>
								<span class="mt-0.5 flex items-center gap-1.5">
									<TypeBadge type={rowType} short col class="!text-[0.6rem]" />
									{#if sub}
										<span class="truncate text-xs text-faint">{sub}</span>
									{/if}
								</span>
							</span>
							<span class="shrink-0 text-right">
								{#if startMs != null}
									<span
										class="block font-mono text-[0.68rem] {startTimes.projected
											? 'text-faint italic'
											: 'text-muted'}"
										title={startTimes.projected
											? 'Projected start if playout begins now'
											: 'Estimated start time'}
									>
										{startTimes.projected ? '~' : ''}{formatClock(new Date(startMs))}
									</span>
								{/if}
								<span class="block font-mono text-xs text-muted">
									{item.duration ? formatTime(item.duration) : ''}
								</span>
							</span>
							{#if isCurrent}
								<span
									class="absolute bottom-0 left-0 h-0.5 bg-accent"
									style="width: {(dragPct ?? itemPct).toFixed(1)}%"
								></span>
							{/if}
						</button>
					{/each}
				{/if}
			</div>
		</details>
	{/if}
</div>

<style>
	.panel {
		border: 1px solid var(--color-border);
		background: var(--color-surface-1);
	}
	.panel-lifted {
		background: var(--color-surface-2);
	}
	.phone-summary {
		cursor: pointer;
		user-select: none;
		padding: 0.75rem 1rem;
		font-size: 0.85rem;
		font-weight: 500;
		color: var(--color-muted);
	}
	.phone-summary:hover {
		color: var(--color-text);
	}
	.panel-label {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.8rem;
		font-weight: 500;
		color: var(--color-muted);
	}

	.tbtn {
		display: flex;
		height: 3.5rem;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.1rem;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-2);
		color: var(--color-text);
		transition: background-color 0.15s ease;
	}
	.tbtn:hover {
		background: var(--color-surface-3);
	}
	.tbtn:active {
		filter: brightness(0.9);
	}
	.tbtn:disabled {
		pointer-events: none;
		opacity: 0.4;
	}
	.tbtn-num {
		font-family: var(--font-mono);
		font-size: 0.6rem;
		color: var(--color-muted);
	}
	.tbtn-primary {
		border-color: transparent;
		background: var(--color-accent);
		color: var(--color-on-accent);
	}
	.tbtn-primary:hover {
		background: var(--color-accent-hover);
	}

	.seg {
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface-2);
		color: var(--color-muted);
		padding: 0.25rem 0.6rem;
		font-size: 0.75rem;
		transition:
			color 0.15s ease,
			border-color 0.15s ease,
			background-color 0.15s ease;
	}
	.seg:hover {
		color: var(--color-text);
		border-color: var(--color-border-strong);
	}
	.seg:disabled {
		pointer-events: none;
		opacity: 0.45;
	}
	.seg-on {
		border-color: var(--color-accent);
		background: color-mix(in srgb, var(--color-accent) 12%, transparent);
		color: var(--color-accent);
	}

	.track-col {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		max-height: 12rem;
		overflow-y: auto;
	}
	.seg-block {
		width: 100%;
		text-align: left;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.fill-smooth {
		transition: width 260ms linear;
	}
	@media (prefers-reduced-motion: reduce) {
		.fill-smooth {
			transition: none;
		}
	}

	.speed-select {
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface-2);
		color: var(--color-text);
		padding: 0.2rem 0.4rem;
		font-size: 0.75rem;
	}
	.speed-select:disabled {
		pointer-events: none;
		opacity: 0.45;
	}
</style>
