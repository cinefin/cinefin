<script lang="ts">
	import { CircleCheck, CircleX, Info, TriangleAlert } from '@lucide/svelte';
	import { toasts, type ToastKind } from '$lib/toast.svelte';

	const styles: Record<ToastKind, string> = {
		success: 'border-success/50 text-success',
		error: 'border-danger/50 text-danger',
		warning: 'border-warning/50 text-warning',
		info: 'border-border-strong text-muted'
	};

	const icons = {
		success: CircleCheck,
		error: CircleX,
		warning: TriangleAlert,
		info: Info
	} as const;
</script>

{#if toasts.list.length}
	<!-- One global stack, mounted once in the app layout. Sits top-centre just
	     below the h-14 topbar so it never obscures a page's own controls (the
	     Settings save bar in particular lives bottom-right). -->
	<div
		class="pointer-events-none fixed top-16 left-1/2 z-50 flex w-96 max-w-[calc(100vw-2rem)]
			-translate-x-1/2 flex-col gap-2"
		role="status"
		aria-live="polite"
	>
		{#each toasts.list as t (t.id)}
			{@const Icon = icons[t.kind]}
			<button
				type="button"
				class="pointer-events-auto flex items-start gap-2.5 rounded-md border bg-surface-2 px-3 py-2.5
					text-left {styles[t.kind]}"
				onclick={() => toasts.dismiss(t.id)}
				title="Dismiss"
			>
				<span class="mt-0.5 shrink-0"><Icon size={15} /></span>
				<span class="min-w-0 flex-1 text-sm break-words text-text">{t.message}</span>
			</button>
		{/each}
	</div>
{/if}
