<script lang="ts">
	import { Menu } from '@lucide/svelte';
	import { base } from '$app/paths';
	import { api, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import { lamp, UNREACHABLE } from '$lib/playout/phase';
	import { playout } from '$lib/stores/playout.svelte';
	import { syncActivity } from '$lib/stores/syncActivity.svelte';
	import { trailerActivity } from '$lib/stores/trailerActivity.svelte';
	import { display } from '$lib/display.svelte';
	import { pageHeader } from '$lib/stores/pageHeader.svelte';
	import ChaseMark from '$lib/components/ChaseMark.svelte';
	import DisplayMenu from '$lib/components/shell/DisplayMenu.svelte';
	import HealthMenu from '$lib/components/shell/HealthMenu.svelte';
	import PhaseLamp from '$lib/components/shell/PhaseLamp.svelte';

	interface Props {
		onmenu: () => void;
	}
	let { onmenu }: Props = $props();

	// Cinema name — supplementary chrome: degrades quietly to "Theater".
	const settings = query(() => unwrap(api.GET('/api/v2/settings/')));
	const cinemaName = $derived(settings.data?.settings?.cinema_name || 'Theater');

	const h = $derived(pageHeader.current);

	// Server accent: apply once settings land (display caches it for the next boot).
	$effect(() => {
		if (settings.data) display.applyAccent(settings.data.settings?.accent_color ?? null);
	});

	$effect(() => playout.subscribe());
	$effect(() => syncActivity.subscribe());
	$effect(() => trailerActivity.subscribe());

	// The booth lamp; on air it is the tally, a solid red block that never blinks.
	const booth = $derived(playout.stale ? UNREACHABLE : lamp(playout.status, playout.loaded));
</script>

{#snippet jobLamp(href: string, title: string, text: string, pct: number)}
	<!-- The one sanctioned ambient chase: it reports background work. -->
	<a {href} class="flex items-center gap-2 text-xs font-medium text-muted hover:text-text" {title}>
		<ChaseMark height={16} />
		<span>{text}{pct ? ` ${pct}%` : ''}</span>
	</a>
{/snippet}

<!-- h-14 with the border inside, matching the sidebar's header so the rules meet. -->
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
				{@render jobLamp(
					`${base}/settings?tab=library`,
					'A library sync is running - open the sync panel',
					'Syncing',
					syncActivity.percentage
				)}
			{/if}
			{#if trailerActivity.busy}
				{@render jobLamp(
					`${base}/trailers?fetch=open`,
					'A trailer job is running - open the fetch panel',
					'Fetching trailers',
					trailerActivity.percentage
				)}
			{/if}
			<PhaseLamp lamp={booth} />
		</div>

		<HealthMenu />
		<DisplayMenu />
	</div>
</header>
