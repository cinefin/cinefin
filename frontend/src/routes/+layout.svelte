<script lang="ts">
	import '../app.css';
	import type { Snippet } from 'svelte';
	import { page } from '$app/state';
	import { base } from '$app/paths';
	import PlayoutBar from '$lib/components/shell/PlayoutBar.svelte';
	import Sidebar from '$lib/components/shell/Sidebar.svelte';
	import Toasts from '$lib/components/Toasts.svelte';
	import Banner from '$lib/components/ui/Banner.svelte';
	import { formatClock } from '$lib/format';
	import { realtime } from '$lib/realtime.svelte';
	import Topbar from '$lib/components/shell/Topbar.svelte';
	import { display } from '$lib/display.svelte';
	import { startInvalidateBridge } from '$lib/realtime-invalidate';

	interface Props {
		children: Snippet;
	}
	let { children }: Props = $props();

	let navOpen = $state(false);

	// Display prefs go on before first paint of the app content.
	display.boot();

	$effect(() => startInvalidateBridge());

	// The docked detail drawer (ui/SidePanel) ends where the playout bar begins; the bar only
	// exists while a player is active, so its height is measured, not assumed.
	let playoutH = $state(0);
	$effect(() => {
		document.documentElement.style.setProperty('--playout-h', `${playoutH}px`);
	});

	const path = $derived(page.url.pathname);
</script>

<div class="flex min-h-dvh">
	<Sidebar bind:open={navOpen} />
	<div class="flex min-w-0 flex-1 flex-col">
		<Topbar onmenu={() => (navOpen = true)} />
		<main class="w-full flex-1 p-4 md:p-6">
			{#if realtime.down}
				<Banner severity="warning" title="Can't reach Cinefin." class="mb-4">
					Reconnecting… What's shown is from {realtime.lastSeen
						? formatClock(new Date(realtime.lastSeen))
						: 'before it went away'}, and the controls are off until it's back.
				</Banner>
			{/if}
			{@render children()}
		</main>
		<!-- The remote is the player; its own page doesn't repeat it in the bar. -->
		<div class="sticky bottom-0 z-10" bind:clientHeight={playoutH}>
			{#if path !== `${base}/remote`}<PlayoutBar />{/if}
		</div>
	</div>
</div>

<Toasts />
