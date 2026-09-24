<script lang="ts">
	/**
	 * The tally lamp — the one loud state, as on a studio wall: a solid red
	 * block, lit or dark, never blinking (spec §06). Reserved for ON AIR;
	 * everything else is a StatusLamp. Carries --color-live (the brand red),
	 * not the quieter working danger.
	 */
	interface Props {
		label?: string;
		class?: string;
	}
	let { label = 'On air', class: cls = '' }: Props = $props();
</script>

<span class="inline-block rounded-sm bg-live px-2.5 py-0.5 text-xs font-semibold text-white {cls}">
	{label}
</span>
