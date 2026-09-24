<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		/**
		 * `type` carries no colour of its own — it is the item-type variant,
		 * whose tint comes from lib/item-types.ts (always via TypeBadge).
		 */
		variant?: 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'outline' | 'type';
		class?: string;
		children: Snippet;
	}

	let { variant = 'default', class: cls = '', children }: Props = $props();

	// Spec §06 (.badge / .b-q / .t-*): every chip has a hairline border; a coloured one is its
	// channel at 30% over a faint tint of it — the same recipe the item-type badges use.
	const variants: Record<string, string> = {
		default: 'border-border-strong bg-surface-2 text-muted',
		accent: 'border-accent/30 bg-accent/15 text-accent',
		success: 'border-success/30 bg-success/15 text-success',
		warning: 'border-warning/30 bg-warning/15 text-warning',
		danger: 'border-danger/30 bg-danger/15 text-danger',
		outline: 'border-border-strong text-muted',
		type: ''
	};
</script>

<span
	class="inline-flex items-center gap-1 rounded-sm border px-[0.5rem] py-[0.125rem] text-[0.71875rem] leading-4
		font-medium whitespace-nowrap {variants[variant]} {cls}"
>
	{@render children()}
</span>
