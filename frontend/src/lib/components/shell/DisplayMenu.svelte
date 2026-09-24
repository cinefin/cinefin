<script lang="ts">
	import { Monitor } from '@lucide/svelte';
	import { display, DENSITIES, THEMES } from '$lib/display.svelte';

	/**
	 * The "Display" menu — per-device presentation preferences: density zoom
	 * and theme. Stored in localStorage, applied instantly.
	 */

	let open = $state(false);
	let root: HTMLDivElement | undefined = $state();

	function onWindowClick(e: MouseEvent) {
		if (open && root && !root.contains(e.target as Node)) open = false;
	}
	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') open = false;
	}

	const segBtn =
		'rounded-sm px-2 py-1 text-xs transition-colors data-[on=true]:bg-surface-3 data-[on=true]:text-text text-muted hover:text-text';
</script>

<svelte:window onclick={onWindowClick} onkeydown={onKeydown} />

<div class="relative" bind:this={root}>
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
				<div>
					<div class="mb-1 text-[0.65rem] text-faint">Density</div>
					<div class="flex gap-1 rounded-md bg-surface-2 p-0.5">
						{#each DENSITIES as d (d.value)}
							<button
								type="button"
								class="flex-1 {segBtn} font-mono"
								data-on={display.density === d.value}
								onclick={() => display.setDensity(d.value)}
							>
								{d.label}
							</button>
						{/each}
					</div>
				</div>

				<div>
					<div class="mb-1 text-[0.65rem] text-faint">Theme</div>
					<div class="flex gap-1 rounded-md bg-surface-2 p-0.5">
						{#each THEMES as t (t.value)}
							<button
								type="button"
								class="flex-1 {segBtn}"
								data-on={display.theme === t.value}
								onclick={() => display.setTheme(t.value)}
							>
								{t.label}
							</button>
						{/each}
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>
