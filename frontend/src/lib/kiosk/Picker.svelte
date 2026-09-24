<script lang="ts">
	import { RotateCcw, SlidersHorizontal } from '@lucide/svelte';
	import type { KioskController } from './controller.svelte';

	interface Props {
		kiosk: KioskController;
		oncursor: (visible: boolean) => void;
	}
	let { kiosk, oncursor }: Props = $props();

	const PICKER_REVEAL_MS = 4000;
	const PICKER_IDLE_CLOSE_MS = 30000;

	const layouts = [
		{ id: 'auto', label: 'Auto - picks by schedule', glyph: 'glyph-auto', cells: 4, wide: true },
		{ id: 'wall', label: 'Poster wall', glyph: 'glyph-wall', cells: 6, wide: false },
		{ id: 'spotlight', label: 'Spotlight', glyph: 'glyph-spotlight', cells: 1, wide: false },
		{ id: 'split', label: 'Split', glyph: 'glyph-split', cells: 2, wide: false },
		{ id: 'board', label: 'Schedule board', glyph: 'glyph-board', cells: 4, wide: false },
		{ id: 'tonight', label: 'Tonight', glyph: 'glyph-tonight', cells: 1, wide: false }
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
		const opts = { passive: true } as const;
		document.addEventListener('pointermove', reveal, opts);
		document.addEventListener('pointerdown', reveal, opts);
		document.addEventListener('touchstart', reveal, opts);
		document.addEventListener('keydown', onKeydown);
		return () => {
			document.removeEventListener('pointermove', reveal);
			document.removeEventListener('pointerdown', reveal);
			document.removeEventListener('touchstart', reveal);
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
						class:choice-auto={l.wide}
						class:active={kiosk.layout === l.id}
						onclick={() => pickLayout(l.id)}
					>
						<span class="choice-glyph {l.glyph}" aria-hidden="true">
							{#each Array(l.cells), i (i)}<i></i>{/each}
						</span>
						<span class="choice-label">{l.label}</span>
					</button>
				{/each}
			</div>
			<div class="picker-divider"></div>
			<div class="picker-field">
				<span>Spotlight dwell</span>
				<div class="picker-times">
					<input
						class="picker-num"
						type="number"
						min="5"
						inputmode="numeric"
						aria-label="Spotlight slide dwell in seconds"
						value={kiosk.prefs.spotlightSecs}
						onchange={(e) => setDwell('spotlightSecs', e.currentTarget.value)}
					/>
					<span class="picker-unit">s</span>
				</div>
			</div>
			<div class="picker-field">
				<span>Poster-wall page</span>
				<div class="picker-times">
					<input
						class="picker-num"
						type="number"
						min="5"
						inputmode="numeric"
						aria-label="Poster-wall page dwell in seconds"
						value={kiosk.prefs.wallPageSecs}
						onchange={(e) => setDwell('wallPageSecs', e.currentTarget.value)}
					/>
					<span class="picker-unit">s</span>
				</div>
			</div>
			<div class="picker-divider"></div>
			<label class="picker-toggle">
				<input
					type="checkbox"
					checked={kiosk.prefs.takeover}
					onchange={(e) => {
						kiosk.setPref('takeover', e.currentTarget.checked);
						armIdleClose();
					}}
				/>
				<span>Now Showing takeover</span>
			</label>
			<label class="picker-toggle">
				<input
					type="checkbox"
					checked={kiosk.prefs.night}
					onchange={(e) => {
						kiosk.setPref('night', e.currentTarget.checked);
						armIdleClose();
					}}
				/>
				<span>Night hours</span>
			</label>
			<div class="picker-field">
				<span>Quiet</span>
				<div class="picker-times">
					<input
						type="time"
						aria-label="Night hours start"
						value={kiosk.prefs.nightStart}
						onchange={(e) => setNightTime('nightStart', e.currentTarget.value)}
					/>
					<span>&ndash;</span>
					<input
						type="time"
						aria-label="Night hours end"
						value={kiosk.prefs.nightEnd}
						onchange={(e) => setNightTime('nightEnd', e.currentTarget.value)}
					/>
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
