<script lang="ts">
	/**
	 * What the screen is doing, in two tiers: a strip for the programme (lamp, its features, its
	 * name, where it is) over a row for what plays now (poster, title, clock, the item's bar). The
	 * dashboard and the remote both draw it; every phase has a reading, offline and standby too.
	 * `children` go under it (the remote's controls), `actions` at the end of the strip; with
	 * `onseek` the item's bar seeks. A programme the player lost (it restarted) is offered back.
	 */
	import type { Snippet } from 'svelte';
	import { base } from '$app/paths';
	import { CalendarClock, MonitorOff, MonitorPlay, RotateCcw } from '@lucide/svelte';
	import FeatureStack from '$lib/components/FeatureStack.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import PhaseLamp from '$lib/components/shell/PhaseLamp.svelte';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import ArtBackdrop from '$lib/dashboard/ArtBackdrop.svelte';
	import { untilLabel } from '$lib/dashboard/data.svelte';
	import { dayLabel, formatClock, formatTime } from '$lib/format';
	import { itemTypeDisplay } from '$lib/item-types';
	import { can, cuedBy, lamp, UNREACHABLE, type PlayoutStatus } from '$lib/playout/phase';
	import { realtime } from '$lib/realtime.svelte';
	import { playout } from '$lib/stores/playout.svelte';
	import { toastFailure } from '$lib/toast.svelte';

	interface Props {
		status: PlayoutStatus;
		/** The player's address, for the offline line (the status never carries it). */
		address?: string;
		onseek?: (seconds: number) => void;
		actions?: Snippet;
		children?: Snippet;
		class?: string;
	}
	let { status, address = '', onseek, actions, children, class: cls = '' }: Props = $props();

	interface Meta {
		content_id?: number;
		metadata?: { thumbnail_url?: string; year?: number | string; certification?: string };
	}

	interface View {
		/** The strip: the programme's name (linked when there is one), else the player's. */
		name: string;
		where: string;
		/** The row: an item type for its badge, else a kicker line. */
		type?: string;
		kicker?: string;
		icon?: typeof MonitorOff;
		art?: string | null;
		title: string;
		detail?: string;
		clock?: string;
		clockSub?: string;
		bar?: boolean;
	}

	const phase = $derived(status.phase);
	const prog = $derived(status.programme ?? null);
	const films = $derived(prog?.features ?? []);
	const item = $derived(status.current_item ?? null);
	const meta = $derived((item?.details ?? {}) as Meta);
	const pb = $derived(status.playback ?? null);
	const player = $derived(status.player?.name ?? 'Player');

	const playingFeature = $derived(item?.type === 'movie' ? (meta.content_id ?? null) : null);
	const art = (type: string | undefined, m: Meta) =>
		type && ['movie', 'feature', 'trailer'].includes(type) ? m.metadata?.thumbnail_url : null;
	const firstArt = $derived(films.find((f) => f.thumbnail_url)?.thumbnail_url ?? null);

	// The backdrop follows the feature, not the item: it changes when a feature starts and holds
	// through the trailers between them. Artwork only ever means a programme is loaded.
	let featureArt = $state<{ programme: number; src: string } | null>(null);
	$effect(() => {
		const src = art(item?.type, meta);
		if (prog && item?.type === 'movie' && src) featureArt = { programme: prog.id, src };
	});
	const backdrop = $derived(
		prog ? (featureArt?.programme === prog.id ? featureArt.src : firstArt) : null
	);

	const clock = $derived({
		clock: formatTime(pb?.position ?? 0),
		clockSub: pb ? `-${formatTime(pb.remaining)} / ${formatTime(pb.duration)}` : ''
	});
	const endsAt = $derived.by(() => {
		const remaining = status.playlist?.programme_remaining_time;
		return remaining ? formatClock(new Date(Date.now() + remaining * 1000)) : '';
	});

	const view = $derived.by((): View => {
		switch (phase) {
			case 'offline':
				return {
					name: status.player ? player : 'No player',
					where: '',
					icon: MonitorOff,
					title: status.label,
					detail: status.player
						? `Can't reach the player${address ? ` at ${address}` : ''}. Retrying every few seconds${status.player.kind === 'agent' ? '; the player shows its own standby meanwhile' : ''}.`
						: 'Add a player to put programmes on screen.'
				};
			case 'standby': {
				const next = status.next_screening;
				const strip = { name: player, where: `On screen · ${status.screen}, held` };
				if (!next)
					return {
						...strip,
						icon: MonitorPlay,
						title: 'Nothing cued',
						detail: 'Nothing is scheduled either.'
					};
				const plays = new Date(next.start_time);
				const cues = new Date(next.cue_time);
				return {
					...strip,
					icon: CalendarClock,
					kicker: 'Next screening',
					title: next.programme_name,
					detail: `${dayLabel(plays)} ${formatClock(plays)}${cues < plays ? ` · the lead-in cues it at ${formatClock(cues)}` : ''}`,
					clock: formatClock(plays),
					clockSub: untilLabel(plays)
				};
			}
			case 'cued': {
				const total = status.playlist?.programme_total_duration ?? 0;
				const count = status.playlist?.total_items ?? 0;
				const screening = cuedBy(status);
				const plays = screening ? new Date(screening.start_time) : null;
				return {
					name: prog?.name ?? player,
					where: `${count} item${count === 1 ? '' : 's'}${total ? ` · ${formatTime(total)}` : ''}`,
					type: status.screen === 'Title card' ? 'title' : undefined,
					kicker: 'On screen',
					art: firstArt,
					title: status.screen,
					detail: 'Held until Start',
					clock: plays ? formatClock(plays) : total ? formatTime(total) : undefined,
					clockSub: plays
						? `starts ${untilLabel(plays)}`
						: total
							? `ends ~${formatClock(new Date(Date.now() + total * 1000))} if started now`
							: undefined
				};
			}
			case 'manual':
			case 'paused':
				if (status.manual) {
					const m = status.manual;
					const now = m.items[m.position ?? -1];
					return {
						name: 'Manual',
						where: m.position != null ? `${m.position + 1} of ${m.items.length}` : '',
						type: now?.kind,
						title: now?.title ?? status.screen,
						...clock,
						bar: true
					};
				}
				break;
		}
		const position = item?.position ?? -1;
		const total = status.playlist?.total_items ?? 0;
		const hold = phase === 'hold';
		const type = position < 0 ? 'title' : hold ? 'command' : (item?.type ?? undefined);
		return {
			name: prog?.name ?? player,
			where: `${position < 0 ? 'Pre-show' : `${position + 1} of ${total}`}${endsAt ? ` · ends ${endsAt}` : ''}`,
			type,
			art: art(item?.type, meta),
			title: position < 0 ? 'Title card' : item?.title || status.screen,
			detail: hold
				? 'Command hold · moves on when it finishes'
				: [meta.metadata?.year, meta.metadata?.certification].filter(Boolean).join(' · '),
			...clock,
			bar: true
		};
	});

	const lit = $derived(realtime.down ? UNREACHABLE : lamp(status));
	// Cinefin out of reach: what plays is the last thing heard, dimmed and dated.
	const seen = $derived(
		realtime.down ? (realtime.lastSeen ? formatClock(new Date(realtime.lastSeen)) : '?') : null
	);
	const typeInfo = $derived(itemTypeDisplay(view.type ?? 'system'));
	const Icon = $derived(view.icon ?? typeInfo.icon);
	let broken = $state(false);
	$effect(() => {
		void view.art;
		broken = false;
	});
	const poster = $derived(view.art && !broken ? view.art : null);

	// The item's bar; with `onseek`, drag or click to seek.
	const seekable = $derived(!!onseek && can(status, 'seek') && !!pb?.duration);
	const pct = $derived(
		pb?.duration ? Math.min(100, ((pb.position ?? 0) / pb.duration) * 100) : (pb?.percentage ?? 0)
	);
	let track = $state<HTMLDivElement>();
	let drag = $state<number | null>(null);
	const at = (e: PointerEvent) => {
		const r = track!.getBoundingClientRect();
		return Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100));
	};
	function down(e: PointerEvent) {
		if (!seekable || !track) return;
		track.setPointerCapture(e.pointerId);
		drag = at(e);
	}
	function up(e: PointerEvent) {
		if (drag == null || !track) return;
		onseek?.((at(e) / 100) * (pb?.duration ?? 0));
		drag = null;
	}

	const lost = $derived(status.interrupted ?? null);
	let recovering = $state(false);
	async function recover(action: 'recover' | 'dismiss') {
		recovering = true;
		try {
			await playout.control({ action });
		} catch (e) {
			toastFailure(action === 'recover' ? "Couldn't resume" : "Couldn't dismiss", e);
		} finally {
			recovering = false;
		}
	}
</script>

<section class="relative isolate overflow-hidden border border-border bg-surface-2 {cls}">
	<ArtBackdrop src={backdrop} from="right" />

	<!-- The programme. -->
	<div
		class="relative z-10 flex min-h-12 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-4 py-2"
	>
		<PhaseLamp lamp={lit} />
		<span class="h-4 w-px bg-border" aria-hidden="true"></span>
		{#if films.length}
			<FeatureStack {films} currentId={playingFeature} size="xs" class="shrink-0" />
		{/if}
		{#if prog && !status.manual}
			<a
				href="{base}/programmes/{prog.id}"
				class="min-w-0 truncate font-display text-lg hover:text-accent">{view.name}</a
			>
		{:else}
			<span class="min-w-0 truncate font-display text-lg">{view.name}</span>
		{/if}
		{#if seen}
			<span class="ml-auto shrink-0 font-mono text-xs text-warning">Last seen {seen}</span>
		{:else if view.where}
			<span class="ml-auto shrink-0 font-mono text-xs text-faint">{view.where}</span>
		{/if}
		{#if actions}
			<div class="flex shrink-0 gap-2 {view.where || seen ? '' : 'ml-auto'}">
				{@render actions()}
			</div>
		{/if}
	</div>

	{#if lost}
		<!-- The player restarted mid-programme: offer it back where it was lost. -->
		<div
			class="relative z-10 flex flex-wrap items-center gap-3 border-b border-warning/40 bg-warning/10 px-4 py-3"
		>
			<RotateCcw size={16} class="shrink-0 text-warning" aria-hidden="true" />
			<p class="min-w-0 flex-1 text-sm">
				<span class="font-medium">{player} restarted during {lost.programme_name}.</span>
				<span class="block text-muted">
					It was on {lost.item_title ?? `item ${lost.position + 1}`}{lost.seconds
						? `, ${formatTime(lost.seconds)} in`
						: ''}.
				</span>
			</p>
			<div class="flex shrink-0 gap-2">
				<Button
					size="sm"
					variant="primary"
					disabled={recovering || !can(status, 'recover')}
					onclick={() => void recover('recover')}
				>
					Resume{lost.seconds ? ` from ${formatTime(lost.seconds)}` : ''}
				</Button>
				<Button
					size="sm"
					disabled={recovering || !can(status, 'dismiss')}
					onclick={() => void recover('dismiss')}>Leave on standby</Button
				>
			</div>
		</div>
	{/if}

	<!-- What plays now. -->
	<div class="relative z-10 flex items-center gap-4 p-4 {seen ? 'opacity-50' : ''}">
		<span
			class="relative flex aspect-[2/3] w-14 shrink-0 items-center justify-center overflow-hidden border border-border bg-surface-3"
		>
			<Icon size={22} class={view.icon ? 'text-faint' : typeInfo.classes.icon} aria-hidden="true" />
			{#if poster}
				<img
					src={poster}
					alt=""
					class="absolute inset-0 h-full w-full object-cover"
					onerror={() => (broken = true)}
				/>
			{/if}
		</span>
		<div class="min-w-0 flex-1">
			{#if view.type}
				<TypeBadge type={view.type} short />
			{:else if view.kicker}
				<p class="text-xs font-medium text-muted">{view.kicker}</p>
			{/if}
			<h2 class="mt-1.5 line-clamp-2 text-2xl leading-tight font-semibold text-balance">
				{view.title}
			</h2>
			{#if view.detail}
				<p class="mt-1 text-sm text-muted">{view.detail}</p>
			{/if}
		</div>
		{#if view.clock}
			<div class="shrink-0 text-right">
				<p class="font-mono text-3xl leading-none">{view.clock}</p>
				{#if view.clockSub}
					<p class="mt-1.5 font-mono text-xs text-faint">{view.clockSub}</p>
				{/if}
			</div>
		{/if}
	</div>

	{#if view.bar}
		<div class="relative z-10 px-4 pb-4 {seen ? 'opacity-50' : ''}">
			<div
				bind:this={track}
				class="relative touch-none {seekable ? 'h-2.5 cursor-pointer' : 'h-1.5'}"
				role="slider"
				aria-label="Seek within the current item"
				aria-valuemin={0}
				aria-valuemax={100}
				aria-valuenow={Math.round(drag ?? pct)}
				aria-disabled={!seekable}
				tabindex="-1"
				onpointerdown={down}
				onpointermove={(e) => drag != null && (drag = at(e))}
				onpointerup={up}
			>
				<div class="absolute inset-0 bg-surface-3">
					<div
						class="h-full {phase === 'hold' ? 'bg-live' : typeInfo.classes.bar} {drag == null
							? 'transition-[width] duration-[260ms] ease-linear motion-reduce:transition-none'
							: ''}"
						style="width: {(drag ?? pct).toFixed(2)}%"
					></div>
				</div>
			</div>
		</div>
	{/if}

	{#if children}
		<div class="relative z-10 border-t border-border bg-surface-2 p-4">{@render children()}</div>
	{/if}
</section>
