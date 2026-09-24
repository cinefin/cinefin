<script lang="ts">
	/**
	 * Global playout bar — the SPA port of the legacy footer
	 * (footer-controller.ts + components/footer.html), rendered by the layout
	 * under every page. Compact now-playing + transport + programme progress +
	 * a link to the operator console. Hidden entirely while nothing is loaded.
	 *
	 * State comes from the shared playout poller plus the playlist feed (for
	 * the block segments); this component only renders and issues actions.
	 * Action failures degrade quietly (console.error) — a background surface
	 * shouldn't stack toasts over whatever page is open.
	 */
	import { base } from '$app/paths';
	import { Pause, Play, SkipBack, SkipForward, SlidersVertical, Square } from '@lucide/svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import { api, unwrap } from '$lib/api/client';
	import { formatTime } from '$lib/format';
	import { playout } from '$lib/stores/playout.svelte';
	import { playlist } from '$lib/stores/player.svelte';
	import { itemTypeClasses, itemTypeLabel } from '$lib/item-types';

	$effect(() => playout.subscribe());
	$effect(() => playlist.subscribe());

	const status = $derived(playout.status);
	const prog = $derived(status?.programme ?? null);
	const progState = $derived(prog?.state);
	const pbState = $derived(status?.playback?.state);

	// Cued = loaded but not started. NB: MPV holds the System Ident/title paused while
	// cued, so playback.state reads 'paused' here — programme.state is the
	// reliable signal (same guard as the legacy footer).
	const isCued = $derived(progState === 'loaded');
	// Pre-show is a PROGRAMME state; playback.state only ever says what the
	// player is doing. Reading pre-show off playback made a paused pre-show
	// look like a playing one, so the primary button offered Pause again and
	// the programme could not be resumed.
	const preShow = $derived(progState === 'pre_show');
	const isPlaying = $derived(pbState === 'playing');
	const isPaused = $derived(!isCued && pbState === 'paused');
	// On air covers paused too — pausing must not disable stepping between items.
	const canCtrl = $derived(
		progState === 'running' || progState === 'pre_show' || progState === 'paused'
	);

	// During the pre-show the programme clock hasn't started; show the pre-show
	// item's own position so the display isn't frozen at 0:00.
	const elapsed = $derived(
		preShow
			? (status?.playback?.position ?? 0)
			: (status?.playlist?.programme_elapsed_time ?? playlist.data?.elapsed_time ?? 0)
	);
	const total = $derived(
		status?.playlist?.programme_total_duration ?? playlist.data?.total_duration ?? 0
	);

	const itemLine = $derived.by(() => {
		if (isCued) return { type: 'Cued', title: 'Cued - press Start playout' };
		if (preShow) {
			// The opening item is the programme's title card when it has one, else
			// the System Ident; the backend names whichever is on screen.
			const opening = status?.current_item;
			return {
				type: itemTypeLabel(opening?.type ?? 'ident', { short: true }),
				title: opening?.title ?? 'System Ident'
			};
		}
		const item = status?.current_item;
		if (item) {
			if (item.type === 'command' && status?.executing_command) {
				// Hold-black command in progress; Next releases the hold early.
				return { type: 'Running', title: `Command: ${item.title ?? ''}` };
			}
			return { type: itemTypeLabel(item.type, { short: true }), title: item.title ?? '' };
		}
		return { type: itemTypeLabel('system'), title: 'System ready' };
	});

	// ── Block segments (the footer's programme timeline) ─────────────────────
	// Width proportions: duration when available, type ratios as fallback.
	// Segment colours are the shared item-type families ($lib/item-types), so
	// the bar reads the same as the rundown, the editor and every type badge.
	const TYPE_RATIO: Record<string, number> = {
		command: 0.25,
		bumper: 0.5,
		trailer: 1,
		trailer_rule: 1,
		movie: 3,
		certification: 0.25
	};
	const segItems = $derived(
		(playlist.data?.playlist ?? []).filter(
			(it) => it.programme_position != null && it.programme_position >= 0 && it.type !== 'system'
		)
	);

	const segments = $derived.by(() => {
		if (!segItems.length) return [];
		const ratio = (t: string | undefined) => TYPE_RATIO[t ?? 'command'] ?? 1;
		const totalRatio = segItems.reduce((s, it) => s + ratio(it.type), 0);
		// Per-tick numbers come from the playout status; the playlist feed only
		// refreshes when the programme/position changes.
		const curPos = status?.current_item?.position ?? status?.playlist?.current_position ?? -1;

		let timeAccum = 0;
		return segItems.map((it) => {
			const isCurrent = it.programme_position === curPos;
			let progress = 0;
			if (isCurrent && (it.duration ?? 0) > 0) {
				progress = Math.min(Math.max(((elapsed - timeAccum) / it.duration!) * 100, 0), 100);
			}
			timeAccum += it.duration || 0;
			return {
				position: it.programme_position!,
				width: (ratio(it.type) / totalRatio) * 100,
				color: itemTypeClasses(it.type).bar,
				isCurrent,
				progress,
				label: `${itemTypeLabel(it.type)} · ${it.title || 'Unknown'} · ${formatTime(it.duration || 0)}`
			};
		});
	});

	// ── Actions ───────────────────────────────────────────────────────────────
	async function act(fn: () => Promise<unknown>) {
		try {
			await fn();
		} catch (err) {
			console.error('Playout bar: action failed:', err);
		}
		void playout.refresh();
	}

	// One state-driven primary: Start playout (cued) / Pause / Resume.
	function primary() {
		void act(async () => {
			if (isCued) await unwrap(api.POST('/api/v2/playout/run'));
			else if (isPaused)
				await unwrap(api.POST('/api/v2/playout/control', { body: { action: 'play' } }));
			else if (isPlaying)
				await unwrap(api.POST('/api/v2/playout/control', { body: { action: 'pause' } }));
		});
	}

	function nav(action: 'previous' | 'next') {
		void act(async () => {
			await unwrap(api.POST('/api/v2/playout/control', { body: { action } }));
			playlist.refresh();
		});
	}

	// Ending the programme is destructive and this bar follows you onto every
	// page, so it asks first — the same wording the remote uses.
	let confirmDlg = $state<ConfirmDialog | undefined>();

	async function endProgramme() {
		const ok = await confirmDlg?.confirm(
			'End the programme? The running order is cleared and the System Ident returns.',
			{ confirmLabel: 'End programme' }
		);
		if (!ok) return;
		void act(async () => {
			await unwrap(api.POST('/api/v2/playout/stop', { body: { reset: true } }));
			playlist.refresh();
		});
	}

	function jumpTo(position: number) {
		void act(async () => {
			await unwrap(
				api.POST('/api/v2/playout/playlist', { body: { programme_position: position } })
			);
			playlist.refresh();
		});
	}

	const primaryLabel = $derived(isPaused ? 'Resume' : isPlaying ? 'Pause' : 'Start playout');
</script>

{#if prog}
	<ConfirmDialog bind:this={confirmDlg} title="End programme?" />
	<div class="border-t border-border bg-surface-1">
		<div class="flex h-14 items-center gap-3 px-3 md:gap-4 md:px-4">
			<!-- Identity: programme + current item -->
			<div class="w-40 min-w-0 shrink-0 md:w-56">
				<a
					href="{base}/programmes/{prog.id}"
					class="block truncate text-sm font-medium hover:text-accent"
					title="Open programme"
				>
					{prog.name}
				</a>
				<p class="flex items-center gap-1.5 truncate text-xs text-muted">
					<span
						class="shrink-0 text-[0.65rem] {status?.executing_command
							? 'text-danger'
							: 'text-faint'}"
					>
						{itemLine.type}
					</span>
					<span class="truncate">{itemLine.title}</span>
				</p>
			</div>

			<!-- Transport -->
			<div class="flex items-center gap-1">
				<button
					type="button"
					class="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text disabled:pointer-events-none disabled:opacity-40"
					title="Previous item"
					aria-label="Previous item"
					disabled={!canCtrl}
					onclick={() => nav('previous')}
				>
					<SkipBack size={15} />
				</button>
				<button
					type="button"
					class="rounded-md bg-accent p-2 text-on-accent hover:bg-accent-hover disabled:pointer-events-none disabled:opacity-40"
					title={primaryLabel}
					aria-label={primaryLabel}
					disabled={!isCued && !isPaused && !isPlaying}
					onclick={primary}
				>
					{#if isPlaying}
						<Pause size={15} />
					{:else}
						<Play size={15} />
					{/if}
				</button>
				<button
					type="button"
					class="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text disabled:pointer-events-none disabled:opacity-40"
					title="Next item"
					aria-label="Next item"
					disabled={!canCtrl}
					onclick={() => nav('next')}
				>
					<SkipForward size={15} />
				</button>
			</div>

			<!-- Programme timeline: elapsed + block segments + total -->
			<div class="hidden min-w-0 flex-1 items-center gap-2.5 sm:flex">
				<span class="shrink-0 font-mono text-xs text-muted">{formatTime(elapsed)}</span>
				<!-- A cued programme shows its shape too: the running order is known
				     the moment it loads, and seeing what is about to play is most of
				     the point of cueing. Jumping stays locked until Start, matching
				     the remote's transport lock. -->
				<div class="flex h-1.5 min-w-0 flex-1 gap-px overflow-hidden rounded-xs bg-surface-3">
					{#each segments as seg (seg.position)}
						<button
							type="button"
							class="group relative h-full {seg.color} {seg.isCurrent
								? ''
								: 'opacity-55'} transition-opacity enabled:hover:opacity-100 disabled:cursor-default"
							style="width: {seg.width.toFixed(3)}%"
							title={isCued ? seg.label : `Jump to ${seg.label}`}
							aria-label={isCued ? seg.label : `Jump to ${seg.label}`}
							disabled={isCued}
							onclick={() => jumpTo(seg.position)}
						>
							{#if seg.isCurrent}
								<span
									class="absolute inset-y-0 left-0 bg-text/40"
									style="width: {seg.progress.toFixed(1)}%"
								></span>
							{/if}
						</button>
					{/each}
				</div>
				<span class="shrink-0 font-mono text-xs text-muted">{formatTime(total)}</span>
			</div>

			<!-- End programme: destructive, so it sits apart from the transport and
			     confirms. Only ever on screen while a programme is loaded, because
			     the whole bar is. -->
			<button
				type="button"
				class="ml-auto flex shrink-0 items-center gap-1.5 rounded-md border border-danger/40 px-2.5 py-1.5 text-xs text-danger hover:bg-danger/10 sm:ml-0"
				title="End the programme - the running order is cleared and the System Ident returns"
				onclick={() => void endProgramme()}
			>
				<Square size={13} />
				<span class="hidden md:inline">End programme</span>
			</button>

			<!-- The console link -->
			<a
				href="{base}/remote"
				class="flex shrink-0 items-center gap-1.5 rounded-md border border-border-strong px-2.5 py-1.5 text-xs text-muted hover:bg-surface-2 hover:text-text"
				title="Open the operator console"
			>
				<SlidersVertical size={13} />
				<span class="hidden md:inline">Remote</span>
			</a>
		</div>
	</div>
{/if}
