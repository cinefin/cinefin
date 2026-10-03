<script lang="ts">
	import { Menu } from '@lucide/svelte';
	import { base } from '$app/paths';
	import { api, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import { lamp } from '$lib/playout/phase';
	import { playout } from '$lib/stores/playout.svelte';
	import { syncActivity } from '$lib/stores/syncActivity.svelte';
	import { trailerActivity } from '$lib/stores/trailerActivity.svelte';
	import { display } from '$lib/display.svelte';
	import { pageHeader } from '$lib/stores/pageHeader.svelte';
	import ChaseMark from '$lib/components/ChaseMark.svelte';
	import DisplayMenu from '$lib/components/shell/DisplayMenu.svelte';
	import HealthMenu from '$lib/components/shell/HealthMenu.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Tally from '$lib/components/Tally.svelte';

	interface Props {
		onmenu: () => void;
	}
	let { onmenu }: Props = $props();

	// Cinema name — supplementary chrome: degrades quietly to "Theater".
	const settings = query(() => unwrap(api.GET('/api/v2/settings/')));
	const cinemaName = $derived(settings.data?.settings?.cinema_name || 'Theater');

	const h = $derived(pageHeader.current);

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

	// The booth lamp (spec §06): the server's phase, drawn by the one helper. On air
	// is not a lamp at all: it is the tally, a solid red block that never blinks.
	const booth = $derived(lamp(playout.status, playout.loaded));
</script>

<!-- The header's inner row shares the page gutter, so the cinema name sits
     exactly above the content's left edge. The page's own title and actions
     (PageHeader) follow it. -->
<!-- h-14 WITH the border inside it: the sidebar's own header is h-14 with its
     border inside too, and without this the two rules meet 1px apart in the
     top-left corner (and the sticky selection strip below leaves a hairline
     gap under the topbar). -->
<header class="band sticky top-0 z-10 h-14 border-b border-border">
	<div class="flex h-full w-full items-center gap-3 px-4 md:px-6">
		<button
			type="button"
			class="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text md:hidden"
			aria-label="Open navigation"
			onclick={onmenu}
		>
			<Menu size={18} />
		</button>

		<a
			href="{base}/"
			class="shrink-0 truncate text-[0.95rem] {h
				? 'hidden text-muted hover:text-text sm:block'
				: 'font-semibold'}">{cinemaName}</a
		>
		{#if h}
			<span class="hidden text-faint sm:block">/</span>
			{#if h.back}
				<a href={h.back.href} class="shrink-0 text-[0.95rem] text-muted hover:text-text"
					>{h.back.label}</a
				>
				<span class="text-faint">/</span>
			{/if}
			<h1 class="min-w-0 truncate font-display text-xl font-normal">{h.title}</h1>
			{#if h.count}
				<span class="hidden shrink-0 font-mono text-xs text-faint sm:block">{h.count}</span>
			{/if}
		{/if}

		<div class="ml-auto flex shrink-0 items-center gap-4">
			{#if h?.actions}
				<div class="hidden items-center gap-2 lg:flex">{@render h.actions()}</div>
				<span class="hidden h-5 w-px bg-border lg:block"></span>
			{/if}
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
			{#if booth.tally}
				<Tally label={booth.label} />
			{:else}
				<StatusLamp colour={booth.colour} pending={booth.pending} quiet={booth.quiet}>
					{booth.label}
				</StatusLamp>
			{/if}
		</div>

		<HealthMenu />
		<DisplayMenu />
	</div>
</header>
