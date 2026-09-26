<script lang="ts">
	import { page } from '$app/state';
	import { base } from '$app/paths';
	import {
		LayoutDashboard,
		Film,
		MonitorPlay,
		ListVideo,
		PaintbrushVertical,
		Layers,
		CalendarClock,
		Clapperboard,
		FolderOpen,
		SquareTerminal,
		Settings,
		Info,
		LogOut,
		PanelLeftClose,
		PanelLeftOpen,
		type LucideIcon
	} from '@lucide/svelte';
	import type { Component } from 'svelte';
	import Logo from '$lib/components/shell/Logo.svelte';
	import { display } from '$lib/display.svelte';
	import { session } from '$lib/stores/session.svelte';

	interface Props {
		/** Mobile: whether the drawer is open (bind from the layout). */
		open?: boolean;
	}
	let { open = $bindable(false) }: Props = $props();

	interface NavItem {
		href: string;
		label: string;
		icon: LucideIcon;
	}

	interface NavGroup {
		/** Sentence-case group label; shown only in the expanded sidebar. */
		label: string;
		items: NavItem[];
	}

	// Grouped by what you are doing, not by where the code lives. Labels stay
	// quiet (small, muted, sentence case) — the grouping is the signal, not
	// the heading.
	const groups: NavGroup[] = [
		{
			label: 'Operate',
			items: [
				{ href: '/', label: 'Dashboard', icon: LayoutDashboard },
				{ href: '/remote', label: 'Remote', icon: MonitorPlay }
			]
		},
		{
			label: 'Content',
			items: [
				{ href: '/library', label: 'Library', icon: Film },
				{ href: '/trailers', label: 'Trailers', icon: Clapperboard },
				{ href: '/media', label: 'Media', icon: FolderOpen },
				{ href: '/schedules', label: 'Schedules', icon: CalendarClock }
			]
		},
		{
			label: 'Programme',
			items: [
				{ href: '/programmes', label: 'Programmes', icon: ListVideo },
				{ href: '/templates', label: 'Templates', icon: Layers },
				{ href: '/titles', label: 'Titles', icon: PaintbrushVertical }
			]
		},
		{
			label: 'System',
			items: [
				{ href: '/commands', label: 'Commands', icon: SquareTerminal },
				{ href: '/settings', label: 'Settings', icon: Settings }
			]
		}
	];

	const allHrefs = groups.flatMap((g) => g.items.map((i) => i.href));

	function matches(href: string, path: string): boolean {
		const target = `${base}${href}`.replace(/\/$/, '') || '/';
		if (href === '/') return path === target;
		return path === target || path.startsWith(`${target}/`);
	}

	/**
	 * The most specific nav entry wins: /programmes/create is a child of
	 * /programmes, and only the deeper one should light up.
	 */
	function isActive(href: string): boolean {
		const path = page.url.pathname.replace(/\/$/, '') || '/';
		if (!matches(href, path)) return false;
		return !allHrefs.some(
			(other) => other !== href && other.startsWith(href) && matches(other, path)
		);
	}

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

<!-- Desktop: sticky and viewport-height, so the footer (version, log out,
     collapse) is always on screen and the nav scrolls internally — static
     would stretch the rail to the page's full height on long pages and
     push the footer below the fold. -->
<aside
	class="fixed inset-y-0 left-0 z-30 flex flex-col border-r border-border bg-shell
		transition-transform md:sticky md:top-0 md:h-dvh md:translate-x-0 {display.rail ? 'w-14' : 'w-56'}
		{open ? 'translate-x-0' : '-translate-x-full'}"
>
	<div
		class="flex h-14 items-center border-b border-border {display.rail ? 'justify-center' : 'px-5'}"
	>
		{#if display.rail}
			<Logo markClass="h-7" />
		{:else}
			<Logo wordmark />
		{/if}
	</div>

	<nav class="flex-1 overflow-y-auto p-2" aria-label="Main">
		{#each groups as group, gi (group.label)}
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

	<!-- Footer: running version, and — when the auth gate is on — Log out.
	     /logout/ is a plain Django view outside the SPA's base, so the link is a
	     full navigation that lands on /login/. -->
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
