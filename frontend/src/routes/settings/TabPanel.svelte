<script lang="ts">
	import type { Snippet } from 'svelte';
	import { fade } from 'svelte/transition';

	interface Props {
		prefix: string;
		tab: string;
		class?: string;
		children: Snippet;
	}
	let { prefix, tab, class: cls = '', children }: Props = $props();
</script>

<div
	role="tabpanel"
	id="{prefix}-{tab}"
	aria-labelledby="tab-{tab}"
	class={cls}
	in:fade={{ duration: 120 }}
>
	{@render children()}
</div>
