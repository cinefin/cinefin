<script lang="ts">
	import { RotateCcw, SlidersHorizontal } from '@lucide/svelte';
	import type { KioskController } from './controller.svelte';

	let { kiosk, oncursor }: { kiosk: KioskController; oncursor: (visible: boolean) => void } =
		$props();

	const PICKER_REVEAL_MS = 4000;
	const PICKER_IDLE_CLOSE_MS = 30000;

	const layouts = [
		{ id: 'auto', label: 'Auto - picks by schedule', cells: 4 },
		{ id: 'wall', label: 'Poster wall', cells: 6 },
		{ id: 'spotlight', label: 'Spotlight', cells: 1 },
		{ id: 'split', label: 'Split', cells: 2 },
		{ id: 'board', label: 'Schedule board', cells: 4 },
		{ id: 'tonight', label: 'Tonight', cells: 1 }
	];

	let btnVisible = $state(false);
	let open = $state(false);
	let revealTimer: ReturnType<typeof setTimeout> | null = null;
	let idleTimer: ReturnType<typeof setTimeout> | null = null;

	function reveal(): void {
		btnVisible = true;
		oncursor(true);
		if (revealTimer) clearTimeout(revealTimer);
		revealTimer = setTimeout(() => {
			if (!open) {
				btnVisible = false;
				oncursor(false);
			}
		}, PICKER_REVEAL_MS);
	}

	function armIdleClose(): void {
		if (idleTimer) clearTimeout(idleTimer);
		idleTimer = setTimeout(close, PICKER_IDLE_CLOSE_MS);
	}

	function close(): void {
		open = false;
		btnVisible = false;
		oncursor(false);
		if (idleTimer) clearTimeout(idleTimer);
	}

	function toggleOpen(e: MouseEvent): void {
		e.stopPropagation();
		if (open) close();
		else {
			open = true;
			armIdleClose();
		}
	}

	function onKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') close();
		else reveal();
	}

	$effect(() => {
		const events = ['pointermove', 'pointerdown', 'touchstart'] as const;
		for (const ev of events) document.addEventListener(ev, reveal, { passive: true });
		document.addEventListener('keydown', onKeydown);
		return () => {
			for (const ev of events) document.removeEventListener(ev, reveal);
			document.removeEventListener('keydown', onKeydown);
			if (revealTimer) clearTimeout(revealTimer);
			if (idleTimer) clearTimeout(idleTimer);
		};
	});

	function pickLayout(id: string): void {
		kiosk.setLayout(id);
		armIdleClose();
	}

	function setNightTime(key: 'nightStart' | 'nightEnd', value: string): void {
		if (value) kiosk.setPref(key, value);
		armIdleClose();
	}

	function setDwell(key: 'spotlightSecs' | 'wallPageSecs', value: string): void {
		const n = parseInt(value, 10);
		if (!isNaN(n) && n >= 5) kiosk.setPref(key, n);
		armIdleClose();
	}
</script>

<button
	class="picker-btn"
	class:visible={btnVisible}
	type="button"
	aria-label="Display options"
	aria-haspopup="dialog"
	onclick={toggleOpen}
>
	<SlidersHorizontal size={17} />
</button>

{#snippet dwell(key: 'spotlightSecs' | 'wallPageSecs', label: string, aria: string)}
	<div class="picker-field">
		<span>{label}</span>
		<div class="picker-times">
			<input
				class="picker-num"
				type="number"
				min="5"
				inputmode="numeric"
				aria-label={aria}
				value={kiosk.prefs[key]}
				onchange={(e) => setDwell(key, e.currentTarget.value)}
			/>
			<span class="picker-unit">s</span>
		</div>
	</div>
{/snippet}

{#snippet toggle(key: 'takeover' | 'night', label: string)}
	<label class="picker-toggle">
		<input
			type="checkbox"
			checked={kiosk.prefs[key]}
			onchange={(e) => {
				kiosk.setPref(key, e.currentTarget.checked);
				armIdleClose();
			}}
		/>
		<span>{label}</span>
	</label>
{/snippet}

{#snippet time(key: 'nightStart' | 'nightEnd', aria: string)}
	<input
		type="time"
		aria-label={aria}
		value={kiosk.prefs[key]}
		onchange={(e) => setNightTime(key, e.currentTarget.value)}
	/>
{/snippet}

{#if open}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div
		class="picker-overlay"
		role="dialog"
		aria-label="Display options"
		tabindex="-1"
		onclick={(e) => {
			if (e.target === e.currentTarget) close();
			else armIdleClose();
		}}
	>
		<div class="picker-panel">
			<div class="picker-title">Display</div>
			<div class="picker-group">
				{#each layouts as l (l.id)}
					<button
						type="button"
						class="picker-choice"
						class:choice-auto={l.id === 'auto'}
						class:active={kiosk.layout === l.id}
						onclick={() => pickLayout(l.id)}
					>
						<span class="choice-glyph glyph-{l.id}" aria-hidden="true">
							{#each Array(l.cells), i (i)}<i></i>{/each}
						</span>
						<span class="choice-label">{l.label}</span>
					</button>
				{/each}
			</div>
			<div class="picker-divider"></div>
			{@render dwell('spotlightSecs', 'Spotlight dwell', 'Spotlight slide dwell in seconds')}
			{@render dwell('wallPageSecs', 'Poster-wall page', 'Poster-wall page dwell in seconds')}
			<div class="picker-divider"></div>
			{@render toggle('takeover', 'Now Showing takeover')}
			{@render toggle('night', 'Night hours')}
			<div class="picker-field">
				<span>Quiet</span>
				<div class="picker-times">
					{@render time('nightStart', 'Night hours start')}
					<span>&ndash;</span>
					{@render time('nightEnd', 'Night hours end')}
				</div>
			</div>
			<div class="picker-divider"></div>
			<button
				type="button"
				class="picker-server"
				title="Drop this screen's overrides and follow the Settings page"
				onclick={() => {
					kiosk.useServerDefaults();
					armIdleClose();
				}}
			>
				<RotateCcw size={13} /> Use Settings-page defaults
			</button>
		</div>
	</div>
{/if}
