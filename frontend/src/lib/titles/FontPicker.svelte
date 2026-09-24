<script lang="ts">
	import { ChevronDown } from '@lucide/svelte';

	// Bundled fonts are true WYSIWYG (the browser previews the same files PIL renders with).

	export interface FontOption {
		name: string;
		bundled: boolean;
	}

	interface Props {
		fonts: FontOption[];
		value: string;
		onpick: (font: string) => void;
	}

	let { fonts, value, onpick }: Props = $props();

	let open = $state(false);
	let root: HTMLDivElement | undefined = $state();

	function onDocumentClick(e: MouseEvent) {
		if (open && root && !root.contains(e.target as Node)) open = false;
	}

	function pick(name: string) {
		open = false;
		onpick(name);
	}
</script>

<svelte:document onclick={onDocumentClick} />

<div class="relative" bind:this={root}>
	<button
		type="button"
		class="flex h-9 w-full items-center justify-between gap-2 rounded-md border border-border-strong
			bg-surface-2 px-2.5 text-sm text-text hover:bg-surface-3"
		onclick={() => (open = !open)}
	>
		<span class="truncate" style="font-family: '{value}'">{value}</span>
		<ChevronDown size={14} class="shrink-0 text-muted" />
	</button>

	{#if open}
		<div
			class="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-md border border-border-strong
				bg-surface-2"
		>
			{#each fonts as f (f.name)}
				<button
					type="button"
					class="flex w-full items-center justify-between gap-2 px-2.5 py-2 text-left text-sm
						hover:bg-surface-3 {f.name === value ? 'text-accent' : 'text-text'}"
					style="font-family: '{f.name}'"
					onclick={() => pick(f.name)}
				>
					<span class="truncate">{f.name}</span>
					{#if !f.bundled}
						<span class="shrink-0 font-sans text-[10px] text-faint">system</span>
					{/if}
				</button>
			{/each}
		</div>
	{/if}
</div>
