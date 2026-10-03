<script lang="ts">
	import { base } from '$app/paths';
	import { CalendarPlus, Clapperboard, ListPlus } from '@lucide/svelte';
	import CommandPad from '$lib/commands/CommandPad.svelte';

	const SHORTCUTS = [
		{ label: 'Fetch trailers', icon: Clapperboard, href: `${base}/trailers?fetch=open` },
		{ label: 'New programme', icon: ListPlus, href: `${base}/programmes/create` },
		{ label: 'Schedule a screening', icon: CalendarPlus, href: `${base}/schedules` }
	];
</script>

<!-- One column in the rail; side by side (each button-width) when it drops below the bands. -->
<div class="@container">
	<div class="grid max-w-3xl grid-cols-1 items-start gap-5 @xl:grid-cols-2">
		<div>
			<CommandPad surface="dashboard" max={6}>
				{#snippet label()}<span>Commands</span>{/snippet}
			</CommandPad>
		</div>

		<div>
			<div class="flex h-6 items-center text-xs text-muted">Shortcuts</div>
			<div class="mt-1.5 flex flex-col gap-1.5">
				{#each SHORTCUTS as s (s.label)}
					<a
						class="flex w-full items-center gap-2 border border-border bg-surface-1 px-2.5 py-1.5 text-xs transition-colors hover:bg-surface-2"
						href={s.href}
					>
						<s.icon size={13} class="shrink-0 text-muted" />
						{s.label}
					</a>
				{/each}
			</div>
		</div>
	</div>
</div>
