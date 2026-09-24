<script lang="ts">
	/**
	 * The detail drawer: one library item (a film, a trailer, a media clip) beside the list it came
	 * from. Mount it only while an item is open; the host owns which item that is.
	 *
	 * - xl and up: docked to the right edge between the top bar and the playout bar, and NOT modal —
	 *   the page's <main> gives up the width (html.side-panel-open, app.css) so the list reflows and
	 *   stays clickable; clicking another item swaps the drawer's contents in place.
	 * - Below xl: slides over the page on a scrim, full width on a phone; the page behind stops
	 *   scrolling and focus stays inside.
	 * - `history` (default on): opening pushes a history entry, so Back — the phone's back button or
	 *   swipe — closes the drawer instead of leaving the page. Hosts that keep the open item in their
	 *   own shallow-routing state (the library) pass `history={false}`.
	 * - The item open in the host's list carries `data-panel-item={id}` and, when it's this one,
	 *   `data-panel-current`: the drawer keeps it scrolled into view as you step through.
	 */
	import type { Snippet } from 'svelte';
	import { onMount } from 'svelte';
	import { cubicOut } from 'svelte/easing';
	import { fade } from 'svelte/transition';
	import { MediaQuery } from 'svelte/reactivity';
	import { ChevronLeft, ChevronRight, X } from '@lucide/svelte';
	import { pushState } from '$app/navigation';
	import { navigating, page } from '$app/state';

	interface Props {
		/** Accessible name — the item's title (the content carries the visible heading). */
		label: string;
		/** Ids the host is listing, in order — powers prev/next and ←/→. */
		ids?: number[];
		currentId?: number | null;
		onstep?: (id: number) => void;
		onclose: () => void;
		history?: boolean;
		/** false = always overlay, never dock — for pages that aren't a list to browse (the dashboard). */
		dock?: boolean;
		/** Pinned action row at the foot of the drawer. */
		footer?: Snippet;
		children: Snippet;
	}

	let {
		label,
		ids = [],
		currentId = null,
		onstep,
		onclose,
		history = true,
		dock = true,
		footer,
		children
	}: Props = $props();

	const wide = new MediaQuery('min-width: 80rem');
	const docked = $derived(dock && wide.current);
	let el: HTMLElement | undefined = $state();

	const position = $derived(currentId != null ? ids.indexOf(currentId) : -1);
	const prevId = $derived(position > 0 ? ids[position - 1] : null);
	const nextId = $derived(position !== -1 && position < ids.length - 1 ? ids[position + 1] : null);

	// ── History: Back closes ────────────────────────────────────────────────
	let pushed = false;
	// A drawer opened while a navigation is still landing (a deep link followed from another page —
	// the film drawer's "Trailer in library") must wait for it: pushing mid-navigation gets our entry
	// overwritten by the arriving one, which the watcher below would read as Back and close us.
	let wantPush = history;
	$effect(() => {
		if (!wantPush || navigating.to) return;
		wantPush = false;
		pushState('', { ...page.state, sidePanel: true });
		pushed = true;
	});
	onMount(() => () => {
		// Closed by the host (a delete, a filter click) while our entry is still current: pop it.
		if (pushed && page.state.sidePanel) history_back();
	});
	// Close once our entry has been seen and then popped (Back / swipe).
	let armed = false;
	$effect(() => {
		if (page.state.sidePanel) armed = true;
		else if (armed) {
			armed = pushed = false;
			onclose();
		}
	});
	function history_back() {
		pushed = false;
		window.history.back();
	}
	function close() {
		if (pushed) history_back();
		else onclose();
	}

	// ── Layout: docked reflows the page; overlay locks it ───────────────────
	onMount(() => {
		const root = document.documentElement;
		const opener = document.activeElement as HTMLElement | null;
		if (dock) root.classList.add('side-panel-open');
		el?.focus({ preventScroll: true });
		return () => {
			root.classList.remove('side-panel-open');
			if (opener?.isConnected) opener.focus({ preventScroll: true });
		};
	});
	$effect(() => {
		if (docked) return;
		const prev = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		return () => {
			document.body.style.overflow = prev;
		};
	});

	// Keep the open item in view in the host's list as you step (docked only — overlaid, it's covered).
	$effect(() => {
		if (!docked || currentId == null) return;
		document
			.querySelector(`[data-panel-item="${currentId}"]`)
			?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
	});

	// ── Keys and focus ──────────────────────────────────────────────────────
	const dialogOpen = () => document.querySelector('dialog[open]') !== null;

	function onkeydown(e: KeyboardEvent) {
		if (e.defaultPrevented || dialogOpen()) return;
		if (e.key === 'Escape') {
			e.preventDefault();
			close();
			return;
		}
		const tag = (e.target as HTMLElement | null)?.tagName;
		if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || e.metaKey || e.ctrlKey) return;
		if (e.key === 'ArrowLeft' && prevId !== null) onstep?.(prevId);
		else if (e.key === 'ArrowRight' && nextId !== null) onstep?.(nextId);
	}

	// Overlaid, the page behind is covered: don't let focus wander into it.
	function onfocusin(e: FocusEvent) {
		if (docked || !el || dialogOpen()) return;
		const target = e.target as Node | null;
		if (target && !el.contains(target)) el.focus({ preventScroll: true });
	}

	/** The drawer's travel: in from the right edge, out the same way (spec §07). */
	function slide(_node: Element) {
		return {
			duration: 340,
			easing: cubicOut,
			css: (t: number) => `transform: translateX(${(1 - t) * 100}%)`
		};
	}
</script>

<svelte:window {onkeydown} />
<svelte:document {onfocusin} />

<div>
	{#if !docked}
		<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -- Escape and the close button are the keyboard paths -->
		<div
			class="fixed inset-0 z-40 bg-black/60"
			transition:fade|global={{ duration: 220 }}
			onclick={close}
		></div>
	{/if}

	<aside
		bind:this={el}
		aria-label={label}
		aria-modal={docked ? undefined : 'true'}
		role={docked ? 'complementary' : 'dialog'}
		tabindex="-1"
		transition:slide|global
		class="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-border bg-surface-1 outline-none
			sm:w-[var(--panel-w)] sm:border-l
			{dock ? 'xl:top-14 xl:bottom-[var(--playout-h,0px)] xl:z-[5]' : ''}"
	>
		<header class="flex h-12 shrink-0 items-center gap-1 border-b border-border px-2">
			{#if ids.length > 1}
				<button
					type="button"
					class="rounded-sm p-2 text-muted hover:bg-surface-2 hover:text-text disabled:pointer-events-none disabled:opacity-30"
					title="Previous (←)"
					aria-label="Previous"
					disabled={prevId === null}
					onclick={() => prevId !== null && onstep?.(prevId)}
				>
					<ChevronLeft size={16} />
				</button>
				<button
					type="button"
					class="rounded-sm p-2 text-muted hover:bg-surface-2 hover:text-text disabled:pointer-events-none disabled:opacity-30"
					title="Next (→)"
					aria-label="Next"
					disabled={nextId === null}
					onclick={() => nextId !== null && onstep?.(nextId)}
				>
					<ChevronRight size={16} />
				</button>
				{#if position !== -1}
					<span class="ml-1 font-mono text-xs text-faint">{position + 1} of {ids.length}</span>
				{/if}
			{/if}
			<button
				type="button"
				class="ml-auto rounded-sm p-2 text-muted hover:bg-surface-2 hover:text-text"
				title="Close (Esc)"
				aria-label="Close"
				onclick={close}
			>
				<X size={16} />
			</button>
		</header>

		<!-- overflow-x-hidden: the drawer never scrolls sideways; long values wrap or truncate. -->
		<div class="@container min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain p-4">
			{@render children()}
		</div>

		{#if footer}
			<footer
				class="flex shrink-0 flex-wrap justify-end gap-2 border-t border-border px-4 pt-3
					pb-[max(0.75rem,env(safe-area-inset-bottom))]"
			>
				{@render footer()}
			</footer>
		{/if}
	</aside>
</div>
