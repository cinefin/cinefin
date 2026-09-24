<script lang="ts">
	/** The mark with its channel chase running — the loading symbol (spec M2). Indeterminate work
	 *  only; determinate work gets a meter. Used by ui/Spinner and the topbar's job lamp. */
	interface Props {
		height?: number;
		class?: string;
	}
	let { height = 28, class: cls = '' }: Props = $props();
</script>

<svg class="chase text-text {cls}" {height} viewBox="0 0 36 48" fill="none" aria-hidden="true">
	<path
		fill-rule="evenodd"
		clip-rule="evenodd"
		d="M0 0h36v48H0V0Zm3 3h30v42H3V3Z"
		fill="currentColor"
	/>
	<g fill="currentColor">
		<rect x="6" y="6" width="4" height="6" /><rect x="6" y="16" width="4" height="6" />
		<rect x="6" y="26" width="4" height="6" /><rect x="6" y="36" width="4" height="6" />
		<rect x="26" y="6" width="4" height="6" /><rect x="26" y="16" width="4" height="6" />
		<rect x="26" y="26" width="4" height="6" /><rect x="26" y="36" width="4" height="6" />
	</g>
	<rect class="ch-r" x="13" y="6" width="10" height="10" fill="#FF2F4D" />
	<rect class="ch-g" x="13" y="19" width="10" height="10" fill="#25E88A" />
	<rect class="ch-b" x="13" y="32" width="10" height="10" fill="#3A7BFF" />
</svg>

<style>
	.chase .ch-r {
		animation: chase 1.5s cubic-bezier(0.22, 0.61, 0.36, 1) infinite;
	}
	.chase .ch-g {
		animation: chase 1.5s cubic-bezier(0.22, 0.61, 0.36, 1) 0.16s infinite;
	}
	.chase .ch-b {
		animation: chase 1.5s cubic-bezier(0.22, 0.61, 0.36, 1) 0.32s infinite;
	}
	@keyframes chase {
		0%,
		100% {
			opacity: 1;
		}
		33% {
			opacity: 0.28;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.chase :global(rect) {
			animation: none !important;
		}
	}
</style>
