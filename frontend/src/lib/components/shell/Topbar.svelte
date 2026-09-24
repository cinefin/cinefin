<script lang="ts">
	import { Menu } from '@lucide/svelte';
	import { base } from '$app/paths';
	import { api, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import { playout } from '$lib/stores/playout.svelte';
	import { syncActivity } from '$lib/stores/syncActivity.svelte';
	import { trailerActivity } from '$lib/stores/trailerActivity.svelte';
	import { display } from '$lib/display.svelte';
	import ChaseMark from '$lib/components/ChaseMark.svelte';
	import DisplayMenu from '$lib/components/shell/DisplayMenu.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Tally from '$lib/components/Tally.svelte';

	interface Props {
		onmenu: () => void;
	}
	let { onmenu }: Props = $props();

	// Cinema name — supplementary chrome: degrades quietly to "Theater".
	const settings = query(() => unwrap(api.GET('/api/v2/settings/')));
	const cinemaName = $derived(settings.data?.settings?.cinema_name || 'Theater');

	// Server accent (display.accent_color): apply once settings land; display
	// caches it so the next boot paints right.
	$effect(() => {
		if (settings.data) display.applyAccent(settings.data.settings?.accent_color ?? null);
	});

	// The booth lamp: live playout state in the chrome, fed by the shared poller.
	$effect(() => playout.subscribe());

	// Sync activity: the shared SSE-fed signal — a lamp appears in the chrome
	// while any library sync runs, from every page, and links to the sync modal.
	$effect(() => syncActivity.subscribe());
	$effect(() => trailerActivity.subscribe());

	// The booth lamp (spec §06): statuses are lamps beside words — steady when
	// settled, pulsing only in transition. On air is not a lamp at all: it is
	// the tally, a solid red block that never blinks.
	type LampState = {
		tally?: boolean;
		label: string;
		colour: 'blue' | 'red' | 'green' | 'amber' | 'neutral';
		pending?: boolean;
		quiet?: boolean;
	};
	const lamp = $derived.by((): LampState => {
		if (!playout.loaded)
			return { label: 'Connecting…', colour: 'neutral', pending: true, quiet: true };
		const state = playout.status?.programme?.state;
		if (state === 'running' || state === 'pre_show')
			return { tally: true, label: 'On air', colour: 'red' };
		if (state === 'paused') return { label: 'Paused', colour: 'amber' };
		if (state === 'loaded') return { label: 'Cued', colour: 'green' };
		if (playout.error && !playout.status)
			return { label: 'Status unavailable', colour: 'red', quiet: true };
		return { label: 'Idle', colour: 'neutral', quiet: true };
	});
</script>

<!-- The header's inner row shares the page gutter (same padding + max-width
     as <main>), so the cinema name sits exactly above the content's left edge. -->
<!-- h-14 WITH the border inside it: the sidebar's own header is h-14 with its
     border inside too, and without this the two rules meet 1px apart in the
     top-left corner (and the sticky selection strip below leaves a hairline
     gap under the topbar). -->
<header class="sticky top-0 z-10 h-14 border-b border-border bg-shell">
	<div class="flex h-full w-full items-center gap-3 px-4 md:px-6">
		<button
			type="button"
			class="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text md:hidden"
			aria-label="Open navigation"
			onclick={onmenu}
		>
			<Menu size={18} />
		</button>

		<!-- Tilt Warp is single-weight: no bolding, no tracking, sentence case. -->
		<h1 class="truncate text-[0.95rem] font-semibold">
			{cinemaName}
		</h1>

		<div class="ml-auto flex items-center gap-4">
			{#if syncActivity.busy}
				<!-- The job lamp: a 16px chase while a background job runs — the one
				     sanctioned ambient chase (it reports work, spec M4). -->
				<a
					href="{base}/settings?tab=library"
					class="flex items-center gap-2 text-xs font-medium text-muted hover:text-text"
					title="A library sync is running - open the sync panel"
				>
					<ChaseMark height={16} />
					<span>Syncing{syncActivity.percentage ? ` ${syncActivity.percentage}%` : ''}</span>
				</a>
			{/if}
			{#if trailerActivity.busy}
				<!-- Same ambient chase for a running trailer job; opens the fetch
				     modal on the trailers page, where the progress meter lives. -->
				<a
					href="{base}/trailers?fetch=open"
					class="flex items-center gap-2 text-xs font-medium text-muted hover:text-text"
					title="A trailer job is running - open the fetch panel"
				>
					<ChaseMark height={16} />
					<span
						>Fetching trailers{trailerActivity.percentage
							? ` ${trailerActivity.percentage}%`
							: ''}</span
					>
				</a>
			{/if}
			{#if lamp.tally}
				<Tally label={lamp.label} />
			{:else}
				<StatusLamp colour={lamp.colour} pending={lamp.pending} quiet={lamp.quiet}>
					{lamp.label}
				</StatusLamp>
			{/if}
		</div>

		<DisplayMenu />
	</div>
</header>
