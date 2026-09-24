<script lang="ts">
	interface Props {
		src: string | null | undefined;
		from?: 'left' | 'right';
		class?: string;
	}
	let { src, from = 'right', class: cls = '' }: Props = $props();
</script>

{#if src}
	<div aria-hidden="true" class="pointer-events-none absolute inset-0 overflow-hidden {cls}">
		<img
			{src}
			alt=""
			class="absolute inset-0 h-full w-full scale-125 object-cover opacity-50 blur-2xl"
		/>
		<div
			class="absolute inset-0 {from === 'right'
				? 'bg-gradient-to-r from-surface-2 via-surface-2/90 to-surface-2/10'
				: 'bg-gradient-to-l from-surface-2 via-surface-2/90 to-surface-2/10'}"
		></div>
	</div>
{/if}
