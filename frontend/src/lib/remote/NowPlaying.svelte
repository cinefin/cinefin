<script lang="ts">
	/**
	 * What is on air, as the remote's banner: the item's poster (a film's or trailer's art,
	 * blurred behind and shown beside the title), else its type's icon. It stands in for a
	 * picture of the screen, which the remote can never show (there is no live video).
	 */
	import ArtBackdrop from '$lib/dashboard/ArtBackdrop.svelte';
	import { itemTypeDisplay } from '$lib/item-types';

	interface Props {
		/** Poster art, for films and trailers. */
		art?: string | null;
		type: string;
		title: string;
		/** The line above the title: the programme and where in it this is. */
		kicker: string;
		facts?: (string | number)[];
		holding?: boolean;
		/** Instead of the item type's name (a programme: "Next screening", "Cued"). */
		badge?: string;
	}
	let { art = null, type, title, kicker, facts = [], holding = false, badge }: Props = $props();

	const info = $derived(itemTypeDisplay(type));
	let broken = $state(false);
	$effect(() => {
		void art;
		broken = false;
	});
	const poster = $derived(art && !broken ? art : null);
</script>

<div class="relative overflow-hidden border-b border-border px-4 pt-5 pb-4">
	<ArtBackdrop src={poster} from="left" />
	<div class="relative flex items-end gap-4">
		<span
			class="relative flex h-24 w-16 shrink-0 items-center justify-center overflow-hidden border border-border bg-surface-3 sm:h-36 sm:w-24"
		>
			<info.icon size={28} class={info.classes.icon} aria-hidden="true" />
			{#if poster}
				<img
					src={poster}
					alt=""
					class="absolute inset-0 h-full w-full object-cover"
					onerror={() => (broken = true)}
				/>
			{/if}
		</span>
		<div class="min-w-0 pb-1">
			<p class="truncate text-sm text-muted">{kicker}</p>
			<h2 class="mt-1 text-2xl leading-tight font-semibold text-balance sm:text-3xl">
				{title}
			</h2>
			<p class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
				{#if badge}
					<span class="font-medium text-text">{badge}</span>
				{:else if type !== 'title'}
					<span class="font-medium {info.classes.icon}">{holding ? 'Hold' : info.short}</span>
				{/if}
				{#if facts.length}
					<span class="font-mono text-faint">{facts.join(' · ')}</span>
				{/if}
			</p>
		</div>
	</div>
</div>
