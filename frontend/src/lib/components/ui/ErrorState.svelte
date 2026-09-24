<script lang="ts">
	import { TriangleAlert } from '@lucide/svelte';
	import Button from './Button.svelte';
	import type { ApiError } from '$lib/api/client';

	interface Props {
		/** The failed query's error; its message is shown as-is. */
		error?: ApiError | Error | null;
		/** Fallback line when there is no error message. */
		message?: string;
		/** Retry runs the region's load again — always offer one for a primary region. */
		retry?: () => void;
		compact?: boolean;
		class?: string;
	}

	let {
		error,
		message = 'Something went wrong',
		retry,
		compact = false,
		class: cls = ''
	}: Props = $props();
</script>

<!-- Same shape as EmptyState (centred, plain bordered panel); the danger
     tint and the icon carry the "this failed" signal, and the region's own
     error message is the text — no invented label. -->
<div
	class="flex flex-col items-center border border-danger/40 bg-danger/5 px-4 text-center
		{compact ? 'py-4' : 'py-8'} {cls}"
	role="alert"
>
	<span aria-hidden="true" class="mb-2 text-danger"><TriangleAlert size={20} /></span>
	<p class="max-w-md text-sm font-medium text-text">{error?.message || message}</p>
	{#if retry}
		<div class="mt-3">
			<Button size="sm" onclick={retry}>Try again</Button>
		</div>
	{/if}
</div>
