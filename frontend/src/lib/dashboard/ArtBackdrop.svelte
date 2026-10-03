<script lang="ts">
	let { src, from = 'right' }: { src: string | null | undefined; from?: 'left' | 'right' } =
		$props();
</script>

{#if src}
	<div aria-hidden="true" class="pointer-events-none absolute inset-0 overflow-hidden">
		<img
			{src}
			alt=""
			class="absolute inset-0 h-full w-full scale-125 object-cover opacity-50 blur-2xl"
		/>
		<div
			class="absolute inset-0 {from === 'right' ? 'bg-gradient-to-r' : 'bg-gradient-to-l'}
				from-surface-2 via-surface-2/90 to-surface-2/10"
		></div>
	</div>
{/if}
