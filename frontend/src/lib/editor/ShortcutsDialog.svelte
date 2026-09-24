<script lang="ts">
	import Dialog from '$lib/components/ui/Dialog.svelte';

	let open = $state(false);

	export function toggle(): void {
		open = !open;
	}

	const mod = /Mac|iP(hone|ad|od)/.test(navigator.platform || '') ? 'Cmd' : 'Ctrl';
	const rows = [
		{ keys: `${mod} + S`, label: 'Save' },
		{ keys: `${mod} + Z`, label: 'Undo' },
		{ keys: `${mod} + Shift + Z`, label: 'Redo' },
		{ keys: 'Click', label: 'Select a block' },
		{ keys: 'Alt + ↑ / ↓', label: 'Move the selected block' },
		{ keys: '?', label: 'Show this reference' },
		{ keys: 'Esc', label: 'Close dialogs' }
	];
</script>

<Dialog bind:open title="Keyboard shortcuts">
	<ul class="divide-y divide-border text-sm">
		{#each rows as row (row.label)}
			<li class="flex items-center justify-between py-2">
				<span>{row.label}</span>
				<kbd
					class="rounded-sm border border-border-strong bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-muted"
				>
					{row.keys}
				</kbd>
			</li>
		{/each}
	</ul>
</Dialog>
