<script lang="ts">
	/**
	 * The Cinefin mark (spec S1), inline so frame and perfs inherit currentColor while the three
	 * exposures stay fixed brand channels. `wordmark` adds the name in Tilt Warp.
	 */
	interface Props {
		/** Tailwind height class for the mark, e.g. `h-6`. Width follows. */
		markClass?: string;
		wordmark?: boolean;
	}
	let { markClass = 'h-7', wordmark = false }: Props = $props();

	// The projector warm-up (spec M1), once per session.
	const warm = (() => {
		try {
			if (sessionStorage.getItem('cinefin-warmup')) return false;
			sessionStorage.setItem('cinefin-warmup', '1');
			return true;
		} catch {
			return false;
		}
	})();
</script>

<!-- The mark sits in a fixed slot so the wordmark's x is stable whatever the mark height. -->
<span class="flex min-w-0 items-center gap-2.5 text-text">
	<span class="flex w-6 shrink-0 justify-center">
		<svg
			class="{markClass} w-auto {warm ? 'warmup' : ''}"
			viewBox="0 0 36 48"
			fill="none"
			role={wordmark ? undefined : 'img'}
			aria-label={wordmark ? undefined : 'Cinefin'}
			aria-hidden={wordmark ? 'true' : undefined}
		>
			<path
				class="fr"
				fill-rule="evenodd"
				clip-rule="evenodd"
				d="M0 0h36v48H0V0Zm3 3h30v42H3V3Z"
				fill="currentColor"
			/>
			<g class="perf" fill="currentColor">
				<rect x="6" y="6" width="4" height="6" /><rect x="6" y="16" width="4" height="6" />
				<rect x="6" y="26" width="4" height="6" /><rect x="6" y="36" width="4" height="6" />
				<rect x="26" y="6" width="4" height="6" /><rect x="26" y="16" width="4" height="6" />
				<rect x="26" y="26" width="4" height="6" /><rect x="26" y="36" width="4" height="6" />
			</g>
			<rect class="ch ch-r" x="13" y="6" width="10" height="10" fill="#FF2F4D" />
			<rect class="ch ch-g" x="13" y="19" width="10" height="10" fill="#25E88A" />
			<rect class="ch ch-b" x="13" y="32" width="10" height="10" fill="#3A7BFF" />
		</svg>
	</span>
	{#if wordmark}
		<span class="truncate font-display text-[1.05rem] leading-none font-normal">Cinefin</span>
	{/if}
</span>

<style>
	/* The guide's warm-up, verbatim (spec M1). */
	@media (prefers-reduced-motion: no-preference) {
		.warmup .fr {
			animation: frame-in 0.5s cubic-bezier(0.22, 0.61, 0.36, 1) both;
		}
		.warmup .ch {
			transform-origin: center;
			animation: warm-strike 0.55s cubic-bezier(0.22, 0.61, 0.36, 1) both;
		}
		.warmup .ch-r {
			animation-delay: 0.2s;
		}
		.warmup .ch-g {
			animation-delay: 0.33s;
		}
		.warmup .ch-b {
			animation-delay: 0.46s;
		}
		.warmup .perf {
			animation: frame-in 0.4s cubic-bezier(0.22, 0.61, 0.36, 1) 0.6s both;
		}
	}
	/* No `to` frames: they default to the element's own (opaque, untransformed) style. */
	@keyframes warm-strike {
		from {
			opacity: 0;
			transform: translateY(4px) scaleY(0.72);
		}
	}
	@keyframes frame-in {
		from {
			opacity: 0;
		}
	}
</style>
