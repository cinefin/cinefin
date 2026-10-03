<script lang="ts">
	import { Monitor } from '@lucide/svelte';
	import { display, DENSITIES, THEMES, type Density, type Theme } from '$lib/display.svelte';
	import { dismiss } from '$lib/components/dismiss';

	// The "Display" menu: per-device density zoom and theme (localStorage).
	let open = $state(false);

	const segBtn =
		'rounded-sm px-2 py-1 text-xs transition-colors data-[on=true]:bg-surface-3 data-[on=true]:text-text text-muted hover:text-text';
</script>

{#snippet seg(
	heading: string,
	options: { value: string; label: string }[],
	current: string,
	pick: (value: string) => void,
	cls = ''
)}
	<div>
		<div class="mb-1 text-[0.65rem] text-faint">{heading}</div>
		<div class="flex gap-1 rounded-md bg-surface-2 p-0.5">
			{#each options as o (o.value)}
				<button
					type="button"
					class="flex-1 {segBtn} {cls}"
					data-on={current === o.value}
					onclick={() => pick(o.value)}
				>
					{o.label}
				</button>
			{/each}
		</div>
	</div>
{/snippet}

<div class="relative" {@attach dismiss(() => (open = false))}>
	<button
		type="button"
		class="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text"
		aria-label="Display preferences"
		aria-expanded={open}
		onclick={() => (open = !open)}
	>
		<Monitor size={16} />
	</button>

	{#if open}
		<div
			class="absolute right-0 z-20 mt-2 w-56 rounded-md border border-border-strong bg-surface-1 p-3"
		>
			<div class="space-y-3">
				{@render seg(
					'Density',
					DENSITIES,
					display.density,
					(v) => display.setDensity(v as Density),
					'font-mono'
				)}
				{@render seg('Theme', THEMES, display.theme, (v) => display.setTheme(v as Theme))}
			</div>
		</div>
	{/if}
</div>
