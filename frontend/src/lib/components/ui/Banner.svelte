<script lang="ts">
	/**
	 * A persistent, page-level notice bar — the standard surface for a state
	 * the operator needs to keep seeing (playout host unreachable, a stale
	 * playlist, missing media). NOT for transient action feedback: that is a
	 * toast (lib/toast + components/Toasts). One look for all of them, by
	 * severity, so a warning reads the same on every page.
	 *
	 * Body text is the default children; `title` is rendered bold inline before
	 * it. Trailing links/buttons go in the `actions` snippet. The severity
	 * colours only the icon (and border/tint) — the body stays readable text.
	 */
	import { Info, TriangleAlert, CircleCheck } from '@lucide/svelte';
	import type { Snippet } from 'svelte';

	type Severity = 'info' | 'warning' | 'danger' | 'success';

	interface Props {
		severity?: Severity;
		/** Override the default per-severity icon. */
		icon?: typeof Info;
		/** Bold lead-in, rendered inline before the body. */
		title?: string;
		/** Top-align icon + text for multi-line notices (default centres). */
		align?: 'center' | 'start';
		class?: string;
		children?: Snippet;
		actions?: Snippet;
	}

	let {
		severity = 'info',
		icon,
		title,
		align = 'center',
		class: cls = '',
		children,
		actions
	}: Props = $props();

	const tone: Record<Severity, string> = {
		info: 'border-accent-dim bg-accent/10',
		warning: 'border-warning/40 bg-warning/10',
		danger: 'border-danger/40 bg-danger/10',
		success: 'border-success/40 bg-success/10'
	};
	const iconTone: Record<Severity, string> = {
		info: 'text-accent',
		warning: 'text-warning',
		danger: 'text-danger',
		success: 'text-success'
	};
	const fallbackIcon: Record<Severity, typeof Info> = {
		info: Info,
		warning: TriangleAlert,
		danger: TriangleAlert,
		success: CircleCheck
	};

	const Icon = $derived(icon ?? fallbackIcon[severity]);
</script>

<div
	role="status"
	class="flex flex-wrap gap-2.5 rounded-md border px-3 py-2.5 text-sm
		{align === 'start' ? 'items-start' : 'items-center'} {tone[severity]} {cls}"
>
	<Icon size={15} class="shrink-0 {align === 'start' ? 'mt-0.5' : ''} {iconTone[severity]}" />
	<span class="min-w-0 flex-1">
		{#if title}<strong>{title}</strong>
		{/if}{@render children?.()}
	</span>
	{#if actions}
		<span class="flex shrink-0 items-center gap-4">{@render actions()}</span>
	{/if}
</div>
