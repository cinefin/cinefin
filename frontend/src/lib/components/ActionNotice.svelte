<script lang="ts">
	import { CircleCheck, TriangleAlert, X } from '@lucide/svelte';
	import type { NoticeState } from '$lib/notice.svelte';

	interface Props {
		notice: NoticeState;
		class?: string;
	}

	let { notice, class: cls = '' }: Props = $props();
</script>

{#if notice.current}
	<div
		role="status"
		class="flex items-center gap-2.5 rounded-md border px-3 py-2 text-sm
			{notice.current.kind === 'error'
			? 'border-danger/40 bg-danger/10'
			: 'border-success/40 bg-success/10'} {cls}"
	>
		<span
			aria-hidden="true"
			class={notice.current.kind === 'error' ? 'text-danger' : 'text-success'}
		>
			{#if notice.current.kind === 'error'}
				<TriangleAlert size={14} />
			{:else}
				<CircleCheck size={14} />
			{/if}
		</span>
		<span class="flex-1">{notice.current.text}</span>
		<button
			type="button"
			class="text-muted hover:text-text"
			aria-label="Dismiss"
			onclick={() => notice.dismiss()}
		>
			<X size={14} />
		</button>
	</div>
{/if}
