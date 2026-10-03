<script lang="ts">
	import type { LucideIcon } from '@lucide/svelte';

	interface Props {
		icon: LucideIcon;
		label: string;
		title?: string;
		disabled?: boolean;
		danger?: boolean;
		onclick: () => void;
	}
	let { icon: Icon, label, title, disabled = false, danger = false, onclick }: Props = $props();
</script>

<button
	type="button"
	class="rounded-sm p-1 text-muted hover:bg-surface-3 hover:text-text disabled:pointer-events-none disabled:opacity-30
		{danger ? 'hover:text-danger' : ''}"
	{title}
	aria-label={label}
	{disabled}
	{onclick}><Icon size={15} /></button
>
