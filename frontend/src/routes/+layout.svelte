<script lang="ts">
	import '../app.css';
	import type { Snippet } from 'svelte';
	import { Settings } from '@lucide/svelte';
	import { page } from '$app/state';
	import { base } from '$app/paths';
	import Banner from '$lib/components/ui/Banner.svelte';
	import PlayoutBar from '$lib/components/shell/PlayoutBar.svelte';
	import Sidebar from '$lib/components/shell/Sidebar.svelte';
	import Toasts from '$lib/components/Toasts.svelte';
	import Topbar from '$lib/components/shell/Topbar.svelte';
	import { display } from '$lib/display.svelte';
	import { playoutReach } from '$lib/stores/playoutReach.svelte';
	import { startInvalidateBridge } from '$lib/realtime-invalidate';

	interface Props {
		children: Snippet;
	}
	let { children }: Props = $props();

	let navOpen = $state(false);

	// Display prefs go on before first paint of the app content.
	display.boot();

	$effect(() => playoutReach.subscribe());

	$effect(() => startInvalidateBridge());

	// The docked detail drawer (ui/SidePanel) ends where the playout bar begins; the bar only
	// exists while a programme is loaded, so its height is measured, not assumed.
	let playoutH = $state(0);
	$effect(() => {
		document.documentElement.style.setProperty('--playout-h', `${playoutH}px`);
	});

	// Suppressed where a page owns the live player state (remote) or stays chromeless (kiosk, setup).
	const path = $derived(page.url.pathname);
	const ownsNotice = $derived(
		path === `${base}/remote` ||
			path.startsWith(`${base}/kiosk`) ||
			path.startsWith(`${base}/setup`)
	);
	const hostDown = $derived(playoutReach.state === 'unreachable' && !ownsNotice);
	const hostLabel = $derived(
		[playoutReach.hostName, playoutReach.hostUrl].filter(Boolean).join(' · ')
	);
</script>

<div class="flex min-h-dvh">
	<Sidebar bind:open={navOpen} />
	<div class="flex min-w-0 flex-1 flex-col">
		<Topbar onmenu={() => (navOpen = true)} />
		<main class="w-full flex-1 p-4 md:p-6">
			{#if hostDown}
				<Banner severity="warning" align="start" class="mb-4" title="Playout host unreachable.">
					Playback is unavailable until the playout host is running and reachable.
					{#if hostLabel}
						<span class="mt-0.5 block font-mono text-xs text-muted">{hostLabel}</span>
					{/if}
					{#snippet actions()}
						<a
							href="{base}/settings?tab=playout"
							class="inline-flex items-center gap-1 font-medium text-warning hover:underline"
						>
							<Settings size={13} /> Playout settings
						</a>
					{/snippet}
				</Banner>
			{/if}
			{@render children()}
		</main>
		<div class="sticky bottom-0 z-10" bind:clientHeight={playoutH}>
			<PlayoutBar />
		</div>
	</div>
</div>

<Toasts />
