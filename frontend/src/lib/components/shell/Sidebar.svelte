<script lang="ts">
	import { page } from '$app/state';
	import { base } from '$app/paths';
	import { Info, LogOut, PanelLeftClose, PanelLeftOpen } from '@lucide/svelte';
	import Logo from '$lib/components/shell/Logo.svelte';
	import { display } from '$lib/display.svelte';
	import { session } from '$lib/stores/session.svelte';
	import { NAV_GROUPS, isActive as navActive } from '$lib/components/shell/nav';

	interface Props {
		/** Mobile: whether the drawer is open (bind from the layout). */
		open?: boolean;
	}
	let { open = $bindable(false) }: Props = $props();

	const isActive = (href: string) => navActive(href, page.url.pathname);

	// Version + "is there a session to log out of" — fetched once per boot.
	session.load();
	// Suffix the channel for non-release builds so an edge/dev image is obvious.
	const versionLabel = $derived(
		session.version
			? session.channel && session.channel !== 'release'
				? `${session.version} · ${session.channel}`
				: session.version
			: 'Version unknown'
	);
</script>

<!-- Mobile scrim -->
{#if open}
	<button
		type="button"
		class="fixed inset-0 z-20 bg-black/60 md:hidden"
		aria-label="Close navigation"
		onclick={() => (open = false)}
	></button>
{/if}

<!-- Desktop: sticky and viewport-height, so the footer stays on screen and the nav scrolls. -->
<aside
	class="fixed inset-y-0 left-0 z-30 flex flex-col border-r border-border bg-shell
		transition-transform md:sticky md:top-0 md:h-dvh md:translate-x-0 {display.rail ? 'w-14' : 'w-56'}
		{open ? 'translate-x-0' : '-translate-x-full'}"
>
	<div class="flex h-14 items-center {display.rail ? 'justify-center' : 'px-5'}">
		{#if display.rail}
			<Logo markClass="h-7" />
		{:else}
			<Logo wordmark />
		{/if}
	</div>

	<nav class="flex-1 overflow-y-auto p-2" aria-label="Main">
		{#each NAV_GROUPS as group, gi (group.label)}
			{#if gi > 0}
				<!-- Rail: a hairline between groups stands in for the label. -->
				<div
					class={display.rail ? 'mx-2 my-2 border-t border-border' : 'mt-3'}
					aria-hidden="true"
				></div>
			{/if}
			{#if !display.rail}
				<p id="nav-group-{gi}" class="px-3 pb-1 text-xs text-faint">{group.label}</p>
			{/if}
			<ul class="space-y-0.5" aria-labelledby={display.rail ? undefined : `nav-group-${gi}`}>
				{#each group.items as item (item.href)}
					{@const active = isActive(item.href)}
					<li>
						<a
							href="{base}{item.href}"
							aria-current={active ? 'page' : undefined}
							title={display.rail ? item.label : undefined}
							onclick={() => (open = false)}
							class="flex items-center gap-3 rounded-md py-1.5 text-sm transition-colors
								{display.rail ? 'justify-center px-0' : 'px-3'}
								{active ? 'bg-surface-2 font-medium text-text' : 'text-muted hover:bg-surface-1 hover:text-text'}"
						>
							<item.icon size={18} class={active ? 'text-accent' : ''} />
							{#if !display.rail}
								<span class="flex-1">{item.label}</span>
							{/if}
						</a>
					</li>
				{/each}
			</ul>
		{/each}
	</nav>

	<!-- Version, and Log out when auth is on (/logout/ is a Django view: a full navigation). -->
	<div
		class="flex border-t border-border text-xs {display.rail
			? 'flex-col items-stretch'
			: 'h-9 items-center gap-3 px-4'}"
	>
		<div
			class="flex items-center gap-1.5 text-faint {display.rail
				? 'h-9 justify-center'
				: 'min-w-0 flex-1'}"
			title={versionLabel}
		>
			{#if display.rail}
				<Info size={16} />
			{:else}
				<span class="truncate font-mono">{versionLabel}</span>
			{/if}
		</div>
		{#if session.authActive}
			<a
				href="/logout/"
				data-sveltekit-reload
				class="flex shrink-0 items-center gap-1.5 text-muted whitespace-nowrap hover:text-text {display.rail
					? 'h-9 justify-center'
					: ''}"
				title="Log out"
			>
				<LogOut size={display.rail ? 16 : 14} />
				{#if !display.rail}<span>Log out</span>{/if}
			</a>
		{/if}
	</div>

	<!-- Collapse to an icon rail (remembered per device, the legacy pref). -->
	<button
		type="button"
		class="hidden h-11 items-center gap-3 border-t border-border text-muted hover:bg-surface-1 hover:text-text md:flex
			{display.rail ? 'justify-center' : 'px-4'}"
		aria-label={display.rail ? 'Expand navigation' : 'Collapse navigation'}
		title={display.rail ? 'Expand navigation' : 'Collapse navigation'}
		onclick={() => display.toggleRail()}
	>
		{#if display.rail}<PanelLeftOpen size={16} />{:else}<PanelLeftClose size={16} /><span
				class="text-xs">Collapse</span
			>{/if}
	</button>
</aside>
