<script lang="ts">
	// A check's outcome as a status: a lamp beside words (spec §06 C3), breathing while it runs.
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import type { CheckState } from '$lib/settings/types';

	interface Props {
		result: CheckState;
		class?: string;
	}

	let { result, class: cls = '' }: Props = $props();

	const COLOUR = { ok: 'green', error: 'red', warn: 'amber', pending: 'blue' } as const;
</script>

{#if result}
	<p class={cls} role="status">
		<StatusLamp
			colour={COLOUR[result.state]}
			pending={result.state === 'pending'}
			quiet={result.state === 'pending'}
		>
			{result.message}
		</StatusLamp>
	</p>
{/if}
