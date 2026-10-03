<script lang="ts">
	/** The tally — the one loud state, reserved for on air: a solid --color-live block. */
	interface Props {
		label?: string;
		class?: string;
	}
	let { label = 'On air', class: cls = '' }: Props = $props();
</script>

<span class="inline-block rounded-sm bg-live px-2.5 py-0.5 text-xs font-semibold text-white {cls}">
	{label}
</span>
