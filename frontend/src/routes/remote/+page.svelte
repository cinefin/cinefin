<script lang="ts">
	// Remote — the operator / playout console. Reads mpv + playlist + playout stores
	// plus GET /commands/list?show_on_remote=true.
	import {
		Captions,
		Clapperboard,
		Cpu,
		Disc3,
		Gauge,
		Headphones,
		ListOrdered,
		Maximize,
		Pause,
		Play,
		RotateCcw,
		RotateCw,
		SkipBack,
		SkipForward,
		Square,
		SquareTerminal,
		Volume1,
		Volume2,
		VolumeX
	} from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { providerIcon } from '$lib/commands/providers';
	import { query } from '$lib/api/query.svelte';
	import { showToast as toast } from '$lib/toast.svelte';
	import { formatClock, formatTime } from '$lib/format';
	import { itemTypeDisplay } from '$lib/item-types';
	import { playout } from '$lib/stores/playout.svelte';
	import { mpv, playlist } from '$lib/stores/player.svelte';
	import type { PlayoutPlaylistItem } from '$lib/api/refinements';
	import type { components } from '$lib/api/types.gen';
	import Banner from '$lib/components/ui/Banner.svelte';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import Tally from '$lib/components/Tally.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	type Track = components['schemas']['TrackSchema'];

	// Schema collapses two CommandSchema backends; pin the fields the quick-fire panel needs.
	interface RemoteCommand {
		id: number;
		name: string;
		provider: string;
		provider_icon: string;
	}

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

	const st = $derived(mpv.status);
	const connected = $derived(!!st?.connected);
	const pb = $derived(st?.status ?? null);
	const mpvPos = $derived(st?.playlist_pos ?? null);
	const programme = $derived(st?.programme ?? null);
	const isRunning = $derived(!!programme?.running);
	const isPaused = $derived(!pb?.playing || !!pb?.paused);

	// Cued (loaded, not on air): the transport acts on the paused System Ident, not the
	// programme, so lock it until Start (Start, End, volume/mute and fullscreen stay live).
	const transportLocked = $derived(!!programme && !isRunning);

	const items = $derived((playlist.data?.playlist ?? []) as PlayoutPlaylistItem[]);
	const offset = $derived(playlist.data?.programme_offset ?? 0);
	// The trailing "system" item is the end-of-programme black sentinel — hide it.
	const visibleItems = $derived(items.filter((it) => it.type !== 'system'));
	const programmeItems = $derived(
		visibleItems
			.filter((it) => it.programme_position != null)
			.slice()
			.sort((a, b) => a.programme_position! - b.programme_position!)
	);
	const programmeCount = $derived(programmeItems.length);

	/** Elapsed seconds before each programme item + the whole-programme total. */
	const timing = $derived.by(() => {
		const before = new Map<number, number>();
		let running = 0;
		for (const it of programmeItems) {
			before.set(it.programme_position!, running);
			running += it.duration || 0;
		}
		return { before, total: playlist.data?.total_duration || running };
	});

	const current = $derived(items.find((it) => it.index === mpvPos));
	const programmePosition = $derived(mpvPos != null && mpvPos >= offset ? mpvPos - offset : null);

	// Hold-black command in progress: MPV's clock describes the looping black clip,
	// so playout status substitutes the command's own dwell.
	const holding = $derived(!!playout.status?.executing_command);

	// Prefer the playout SSE's 250 ms playback.position push over mpv's event-gated status;
	// mpv's pb is only a fallback until the first push.
	const live = $derived(playout.status?.playback ?? null);
	const itemTime = $derived(live?.position ?? pb?.time ?? 0);
	const itemDuration = $derived((live?.duration || pb?.duration || current?.duration) ?? 0);
	const itemPct = $derived(itemDuration > 0 ? Math.min(100, (itemTime / itemDuration) * 100) : 0);

	const programmeElapsed = $derived.by(() => {
		if (programmePosition == null || programmePosition < 0) return 0;
		return (timing.before.get(programmePosition) ?? 0) + (live?.position ?? pb?.time ?? 0);
	});
	const programmeRemaining = $derived(Math.max(0, timing.total - programmeElapsed));
	const programmePct = $derived(
		timing.total > 0 ? Math.min(100, (programmeElapsed / timing.total) * 100) : 0
	);

	// On air and Pre-show are the tally (the loud state); the rest are lamps.
	const stateBadge = $derived.by(
		(): { label: string; tally?: boolean; colour?: 'green' | 'amber' | 'neutral' } => {
			if (!programme) return { label: 'No programme', colour: 'neutral' };
			if (isRunning) {
				if (offset > 0 && mpvPos != null && mpvPos < offset)
					return { label: 'Pre-show', tally: true };
				if (pb?.paused) return { label: 'Paused', colour: 'amber' };
				return { label: 'On air', tally: true };
			}
			return { label: 'Cued', colour: 'green' };
		}
	);

	function fileName(path: string | null | undefined): string {
		if (!path) return '';
		// Stream URLs carry a ?t= token and a trailing slash — strip both.
		return path.split('?')[0].replace(/\/$/, '').split('/').pop() || path;
	}

	function openingItemLabel(item: { file?: string | null }): string {
		return (item.file || '').includes('/stream/title/') ? 'Title card' : 'System Ident';
	}

	const npMeta = $derived((current?.details?.metadata ?? {}) as ItemMeta);
	const npType = $derived(current?.type || 'item');
	const npTitle = $derived.by(() => {
		if (!current) return 'No media loaded';
		// A pre-show opening item is a stream URL (title/ident) — label it, not its file name.
		const fallback = programmePosition == null ? openingItemLabel(current) : fileName(current.file);
		return (
			current.title ||
			npMeta.movie_title ||
			npMeta.trailer_title ||
			npMeta.bumper_title ||
			fallback ||
			'Untitled'
		);
	});
	const npPosterUrl = $derived(
		npType === 'movie' || npType === 'feature' ? npMeta.thumbnail_url || '' : ''
	);

	const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];
	let volume = $state(100);
	let volDragging = $state(false);
	$effect(() => {
		if (!volDragging && pb?.volume != null) volume = Math.round(pb.volume);
	});
	const muted = $derived(!!pb?.muted);
	const currentSpeed = $derived(pb?.speed ?? 1);
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

	async function runProgramme(): Promise<void> {
		if (starting) return;
		starting = true;
		try {
			await unwrap(api.POST('/api/v2/playout/run'));
			toast('Playout started', 'success');
			void mpv.refresh();
			void playout.refresh();
			playlist.refresh();
		} catch (err) {
			toast(`Failed to start playout: ${(err as Error).message}`, 'error');
		} finally {
			starting = false;
		}
	}

	async function primaryAction(): Promise<void> {
		if (isRunning) return togglePlayPause();
		return runProgramme();
	}

	async function togglePlayPause(): Promise<void> {
		// Cued but not on air yet: start playout rather than poking MPV's pause state.
		if (!isRunning && programme) return runProgramme();
		try {
			await mpvCommand('cycle', ['pause']);
			void mpv.refresh();
		} catch (err) {
			toast(`Playback control failed: ${(err as Error).message}`, 'error');
		}
	}

	async function stop(): Promise<void> {
		if (
			!(await confirmDlg?.confirm(
				'End the programme? The running order is cleared and the System Ident returns.',
				{ confirmLabel: 'End programme' }
			))
		)
			return;
		try {
			await unwrap(api.POST('/api/v2/playout/stop', { body: { reset: true } }));
			toast('Playout stopped', 'info');
			void playout.refresh();
			void mpv.refresh();
			playlist.refresh();
		} catch (err) {
			toast(`Failed to stop playout: ${(err as Error).message}`, 'error');
		}
	}

	// Return the screen to the idle ident. Works whenever the player is
	// connected — a recovery for a stale or fiddled screen — and confirms first
	// only when it would clear a show that's on air.
	async function returnToIdent(): Promise<void> {
		if (programme) {
			if (
				!(await confirmDlg?.confirm(
					`"${programme.name}" is on the player. Return to the idle ident and clear it?`,
					{ confirmLabel: 'Return to ident' }
				))
			)
				return;
		}
		try {
			await mutate(api.POST('/api/v2/playout/reset'));
			toast('Player reset to the idle ident', 'info');
			void playout.refresh();
			void mpv.refresh();
			playlist.refresh();
		} catch (err) {
			toast(`Failed to reset the player: ${(err as Error).message}`, 'error');
		}
	}

	async function toggleFullscreen(): Promise<void> {
		try {
			await mpvCommand('cycle', ['fullscreen']);
		} catch (err) {
			toast(`Fullscreen toggle failed: ${(err as Error).message}`, 'error');
		}
	}

	async function seekRelative(seconds: number): Promise<void> {
		if (transportLocked) return;
		try {
			await mpvCommand('seek', [seconds, 'relative']);
			void mpv.refresh();
		} catch (err) {
			toast(`Seek failed: ${(err as Error).message}`, 'error');
		}
	}

	async function playlistNav(direction: 'previous' | 'next'): Promise<void> {
		if (transportLocked) return;
		try {
			await unwrap(api.POST('/api/v2/playout/control', { body: { action: direction } }));
			void mpv.refresh();
			playlist.refresh();
		} catch (err) {
			toast(`Navigation failed: ${(err as Error).message}`, 'error');
		}
	}

	async function jumpTo(mpvIndex: number): Promise<void> {
		try {
			await unwrap(api.POST('/api/v2/playout/playlist', { body: { index: mpvIndex } }));
			void mpv.refresh();
			playlist.refresh();
		} catch (err) {
			toast(`Jump failed: ${(err as Error).message}`, 'error');
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
		if (transportLocked) return;
		try {
			await setProperty('speed', speed);
			void mpv.refresh();
		} catch (err) {
			toast(`Speed change failed: ${(err as Error).message}`, 'error');
		}
	}

	async function selectTrack(type: 'audio' | 'sub', id: number | 'no'): Promise<void> {
		if (transportLocked) return;
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
		if (transportLocked || !itemTrackEl) return;
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
		try {
			await mpvCommand('seek', [pct, 'absolute-percent']);
			await mpv.refresh();
		} catch (err) {
			toast(`Seek failed: ${(err as Error).message}`, 'error');
		} finally {
			dragPct = null;
		}
	}

	async function seekFromProgrammeTrack(e: MouseEvent) {
		if (transportLocked || !timing.total) return;
		const el = e.currentTarget as HTMLElement;
		const rect = el.getBoundingClientRect();
		const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
		const targetTime = pct * timing.total;

		let target: PlayoutPlaylistItem | null = null;
		let timeWithinItem = 0;
		for (const item of programmeItems) {
			const before = timing.before.get(item.programme_position!) ?? 0;
			const end = before + (item.duration || 0);
			if (targetTime < end || item === programmeItems[programmeItems.length - 1]) {
				target = item;
				timeWithinItem = Math.max(0, targetTime - before);
				break;
			}
		}
		if (!target) return;

		try {
			await unwrap(api.POST('/api/v2/playout/playlist', { body: { index: target.index } }));
			void mpv.refresh();
			playlist.refresh();
			if (timeWithinItem > 1) {
				// Let MPV switch items before seeking within the new one.
				await new Promise((r) => setTimeout(r, 350));
				await mpvCommand('seek', [timeWithinItem, 'absolute']);
			}
		} catch (err) {
			toast(`Seek failed: ${(err as Error).message}`, 'error');
		}
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

	const commands = query(async () => {
		const data = await unwrap(
			api.GET('/api/v2/commands/list', { params: { query: { show_on_remote: true } } })
		);
		return (data?.commands ?? []) as unknown as RemoteCommand[];
	});
	let executingId = $state<number | null>(null);

	const preshowCues = query(async () => await unwrap(api.GET('/api/v2/playout/preshow')));
	let firingPreshow = $state(false);

	async function runPreshow(): Promise<void> {
		if (firingPreshow) return;
		firingPreshow = true;
		try {
			const data = await unwrap(api.POST('/api/v2/playout/preshow/run'));
			toast(`Fired ${data.fired} pre-show command${data.fired === 1 ? '' : 's'}`, 'success');
		} catch (err) {
			toast(`Pre-show failed: ${(err as Error).message}`, 'error');
		} finally {
			firingPreshow = false;
		}
	}

	async function executeCommand(cmd: RemoteCommand): Promise<void> {
		if (executingId != null) return;
		executingId = cmd.id;
		try {
			await unwrap(
				api.POST('/api/v2/commands/{command_id}/execute', {
					params: { path: { command_id: cmd.id } }
				})
			);
			toast('Command executed', 'success');
		} catch (err) {
			toast(`Command failed: ${(err as Error).message}`, 'error');
		} finally {
			executingId = null;
		}
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
		if (isRunning && mpvPos != null) {
			const cur = programmeItems.findIndex((it) => it.index === mpvPos);
			if (cur >= 0) {
				anchorAt = cur;
				projected = false;
			}
		}
		const anchorMs = projected ? Date.now() : Date.now() - (pb?.time ?? 0) * 1000;
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

	const primaryLabel = $derived(isRunning ? (pb?.paused ? 'Resume' : 'Pause') : 'Start playout');

	function hideBrokenImage(e: Event) {
		(e.currentTarget as HTMLImageElement).style.display = 'none';
	}
	function showLoadedImage(e: Event) {
		(e.currentTarget as HTMLImageElement).style.display = '';
	}
</script>

<svelte:head><title>Remote - Cinefin</title></svelte:head>

<ConfirmDialog bind:this={confirmDlg} title="End programme?" />

<div class="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
	<div class="min-w-0 space-y-4">
		<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
			<div class="min-w-0 flex-1">
				<div class="flex min-w-0 items-center gap-2.5">
					<h1 class="min-w-0 text-lg font-semibold sm:truncate sm:text-xl">
						{programme?.name || 'No programme cued'}
					</h1>
					{#if stateBadge.tally}
						<Tally label={stateBadge.label} />
					{:else}
						<span
							class="shrink-0 text-sm font-medium {stateBadge.colour === 'green'
								? 'text-success'
								: stateBadge.colour === 'amber'
									? 'text-warning'
									: 'text-faint'}"
						>
							{stateBadge.label}
						</span>
					{/if}
				</div>
				{#if !mpv.loaded}
					<p class="mt-0.5 font-mono text-xs text-faint">Connecting to the player…</p>
				{:else if !connected}
					<p class="mt-0.5 font-mono text-xs text-danger">Player disconnected</p>
				{/if}
			</div>
			<Button
				variant="primary"
				disabled={!programme || starting}
				title="Start playout when cued; pause/resume while on air"
				onclick={() => void primaryAction()}
			>
				{#if isRunning && !pb?.paused}
					<Pause size={14} />
				{:else}
					<Play size={14} />
				{/if}
				{starting ? 'Starting…' : primaryLabel}
			</Button>
		</div>

		{#if !connected && mpv.loaded}
			<Banner severity="danger">
				Player not connected - check the playout host under Settings → Playout.
			</Banner>
		{/if}

		<section class="panel panel-lifted p-4">
			<div class="flex gap-4">
				{#if current}
					{@const npTypeInfo = itemTypeDisplay(npType)}
					{@const TypeIcon = npTypeInfo.icon}
					<div
						class="film-grain aspect-[2/3] w-20 shrink-0 overflow-hidden border border-border bg-surface-3 sm:w-28"
					>
						{#if npPosterUrl}
							<img
								src={npPosterUrl}
								alt=""
								class="h-full w-full object-cover"
								onerror={hideBrokenImage}
								onload={showLoadedImage}
							/>
						{:else}
							<div class="flex h-full items-center justify-center">
								<TypeIcon size={30} class={npTypeInfo.classes.icon} aria-hidden="true" />
							</div>
						{/if}
					</div>
				{/if}
				<div class="flex min-w-0 flex-1 flex-col">
					<p class="flex items-center gap-1.5 font-mono text-xs">
						{#if current}
							{@const npTypeInfo = itemTypeDisplay(npType)}
							<span class="text-muted">{npTypeInfo.label}</span>
							<span class="text-faint">·</span>
							<span class="text-faint">
								{programmePosition != null && programmeCount > 0
									? `Item ${programmePosition + 1} of ${programmeCount}`
									: 'Pre-show'}
							</span>
						{:else}
							<span class="text-faint">Idle - no media loaded</span>
						{/if}
					</p>
					<h2 class="mt-1 text-xl leading-tight font-semibold sm:text-2xl">{npTitle}</h2>

					{#if current}
						<p class="mt-1.5 flex flex-wrap items-center gap-x-2 font-mono text-xs text-muted">
							{#each [npMeta.year, npMeta.certification, current.duration ? formatTime(current.duration) : null, npMeta.resolution].filter(Boolean) as fact, i (i)}
								{#if i > 0}<span class="text-faint">·</span>{/if}<span>{fact}</span>
							{/each}
						</p>
						{@const credits = [
							npMeta.director,
							Array.isArray(npMeta.genres) ? npMeta.genres.slice(0, 3).join(', ') : ''
						].filter(Boolean)}
						{#if credits.length}
							<p class="mt-0.5 truncate text-xs text-faint">{credits.join(' · ')}</p>
						{/if}
						{#if npType === 'command' && holding}
							<p class="mt-auto pt-2 text-xs text-live">
								Command running - <span class="font-medium">Next</span> ends the hold.
							</p>
						{/if}
					{/if}
				</div>
			</div>

			<div class="mt-4">
				<div class="flex items-baseline justify-between font-mono text-xs">
					<span class="text-muted">{formatTime(itemTime)}</span>
					<span class="text-faint">
						{holding ? 'Command hold' : 'Current item'}
					</span>
					<span class="text-muted">{formatTime(itemDuration)}</span>
				</div>
				<div
					bind:this={itemTrackEl}
					class="group relative mt-1 h-2.5 touch-none {transportLocked
						? 'cursor-not-allowed opacity-50'
						: 'cursor-pointer'}"
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
					<div
						class="absolute inset-0 bg-surface-3"
						style="-webkit-mask: repeating-linear-gradient(90deg, #000 0 6px, transparent 6px 9px); mask: repeating-linear-gradient(90deg, #000 0 6px, transparent 6px 9px);"
					>
						<div
							class="h-full {holding ? 'bg-live' : 'bg-text'} {dragPct == null
								? 'fill-smooth'
								: ''}"
							style="width: {(dragPct ?? itemPct).toFixed(2)}%"
						></div>
					</div>
					<div
						class="absolute top-1/2 h-3.5 w-1 -translate-x-1/2 -translate-y-1/2 bg-accent opacity-0 transition-opacity group-hover:opacity-100"
						style="left: {(dragPct ?? itemPct).toFixed(2)}%"
					></div>
				</div>
			</div>

			<div class="mt-3">
				<div class="flex items-baseline justify-between font-mono text-xs">
					<span class="text-muted">{formatTime(programmeElapsed)}</span>
					<span class="text-faint">Whole programme</span>
					<span class="text-muted"
						>{timing.total > 0 ? `-${formatTime(programmeRemaining)}` : '0:00'}</span
					>
				</div>
				<button
					type="button"
					class="mt-1 block h-1.5 w-full bg-surface-3 {transportLocked
						? 'cursor-not-allowed opacity-50'
						: 'cursor-pointer'}"
					style="-webkit-mask: repeating-linear-gradient(90deg, #000 0 6px, transparent 6px 9px); mask: repeating-linear-gradient(90deg, #000 0 6px, transparent 6px 9px);"
					aria-label="Seek within the programme"
					disabled={transportLocked}
					onclick={(e) => void seekFromProgrammeTrack(e)}
				>
					<div
						class="fill-smooth h-full bg-text/60"
						style="width: {programmePct.toFixed(2)}%"
					></div>
				</button>
			</div>
		</section>

		<section class="panel p-4">
			<div class="mx-auto grid max-w-md grid-cols-5 gap-2">
				<button
					type="button"
					class="tbtn"
					title="Previous item"
					aria-label="Previous item"
					disabled={transportLocked || !connected}
					onclick={() => void playlistNav('previous')}
				>
					<SkipBack size={20} />
				</button>
				<button
					type="button"
					class="tbtn"
					title="Back 10 seconds"
					aria-label="Back 10 seconds"
					disabled={transportLocked || !connected}
					onclick={() => void seekRelative(-10)}
				>
					<RotateCcw size={18} /><span class="tbtn-num">10s</span>
				</button>
				<button
					type="button"
					class="tbtn tbtn-primary"
					title="Pause / Resume (starts playout when cued)"
					aria-label="Pause or resume"
					disabled={transportLocked || !connected}
					onclick={() => void togglePlayPause()}
				>
					{#if isPaused}
						<Play size={24} />
					{:else}
						<Pause size={24} />
					{/if}
				</button>
				<button
					type="button"
					class="tbtn"
					title="Forward 10 seconds"
					aria-label="Forward 10 seconds"
					disabled={transportLocked || !connected}
					onclick={() => void seekRelative(10)}
				>
					<RotateCw size={18} /><span class="tbtn-num">10s</span>
				</button>
				<button
					type="button"
					class="tbtn"
					title="Next item"
					aria-label="Next item"
					disabled={transportLocked || !connected}
					onclick={() => void playlistNav('next')}
				>
					<SkipForward size={20} />
				</button>
			</div>
			{#if transportLocked}
				<p class="mt-3 text-center text-xs text-muted">
					Cued - start the programme to unlock the transport.
				</p>
			{/if}

			<div class="mt-4 flex flex-wrap items-center gap-x-4 gap-y-3 border-t border-border pt-4">
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

				<label class="flex items-center gap-1.5 text-xs text-muted" title="Playback speed">
					<Gauge size={14} class="shrink-0" />
					<span class="sr-only">Playback speed</span>
					<select
						class="speed-select"
						disabled={transportLocked || !connected}
						value={String(currentSpeed)}
						onchange={(e) =>
							void setSpeed(parseFloat((e.currentTarget as HTMLSelectElement).value))}
					>
						{#each SPEEDS as speed (speed)}
							<option value={String(speed)}>{speed}×</option>
						{/each}
					</select>
				</label>

				<div class="ml-auto flex items-center gap-2">
					<Button
						size="sm"
						title="Toggle fullscreen"
						disabled={!connected}
						onclick={() => void toggleFullscreen()}
					>
						<Maximize size={13} />
					</Button>
					<Button
						size="sm"
						title="Return the screen to the idle ident"
						disabled={!connected}
						onclick={() => void returnToIdent()}
					>
						<RotateCcw size={13} /> Return to ident
					</Button>
					<Button
						size="sm"
						variant="danger"
						title="End the programme - the running order is cleared and the System Ident returns"
						disabled={!programme}
						onclick={() => void stop()}
					>
						<Square size={12} /> End programme
					</Button>
				</div>
			</div>
		</section>

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
									disabled={transportLocked || !connected}
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
							disabled={transportLocked || !connected}
							onclick={() => void selectTrack('sub', 'no')}
						>
							Off
						</button>
						{#each subTracks as track, i (track.id)}
							<button
								type="button"
								class="seg seg-block {track.selected ? 'seg-on' : ''}"
								disabled={transportLocked || !connected}
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

		{#if commands.data?.length || preshowCues.data?.count}
			<details class="panel" bind:open={commandsOpen}>
				<summary class="phone-summary sm:hidden">
					<span class="inline-flex items-center gap-1.5">
						<SquareTerminal size={13} /> Commands
					</span>
				</summary>
				<div class="p-4">
					<p class="panel-label mb-2 hidden sm:flex"><SquareTerminal size={12} /> Commands</p>
					{#if preshowCues.data?.count}
						<div class="mb-3 flex items-center justify-between gap-2 border-b border-border pb-3">
							<span class="text-xs text-muted">
								{preshowCues.data.count} pre-show command{preshowCues.data.count === 1 ? '' : 's'}
							</span>
							<Button
								size="sm"
								disabled={firingPreshow}
								onclick={() => void runPreshow()}
							>
								<Clapperboard size={14} />
								{firingPreshow ? 'Running…' : 'Run pre-show'}
							</Button>
						</div>
					{/if}
					<div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
						{#each commands.data ?? [] as cmd (cmd.id)}
							{@const ProviderIcon = providerIcon(cmd.provider_icon)}
							<button
								type="button"
								class="flex items-center gap-2 border border-border bg-surface-2 px-3 py-2.5 text-left text-sm transition-colors hover:bg-surface-3 disabled:pointer-events-none disabled:opacity-50"
								disabled={executingId != null}
								onclick={() => void executeCommand(cmd)}
							>
								<ProviderIcon size={14} class="shrink-0 text-muted" />
								<!-- A busy button disables and says so (spec M4) — no spinner. -->
								<span class="truncate">{executingId === cmd.id ? 'Running…' : cmd.name}</span>
							</button>
						{/each}
					</div>
				</div>
			</details>
		{/if}

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

		<div bind:this={timelineEl} class="max-h-[70vh] overflow-y-auto xl:max-h-[calc(100dvh-10rem)]">
			{#if !mpv.loaded && !playlist.data}
				<Spinner label="Waiting for playlist…" />
			{:else if !visibleItems.length}
				<EmptyState icon={Disc3} title="No playlist loaded" compact />
			{:else}
				{#each visibleItems as item (item.index)}
					{@const rowType = item.programme_position == null ? 'ident' : item.type || 'item'}
					{@const rowTypeInfo = itemTypeDisplay(rowType)}
					{@const RowIcon = rowTypeInfo.icon}
					{@const meta = (item.details?.metadata ?? {}) as ItemMeta}
					{@const rowTitle =
						item.title ||
						meta.movie_title ||
						(rowType === 'ident' ? openingItemLabel(item) : fileName(item.file)) ||
						'Untitled'}
					{@const sub = [meta.year, meta.certification].filter(Boolean).join(' · ')}
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
						onclick={() => void jumpTo(item.index)}
						class="relative flex w-full items-center gap-2.5 border-b border-border px-3 py-2 text-left transition-colors last:border-b-0 hover:bg-surface-2
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
							<span class="block truncate text-sm {isCurrent ? 'text-accent' : ''}">{rowTitle}</span
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
