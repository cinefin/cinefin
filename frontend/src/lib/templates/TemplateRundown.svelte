<script lang="ts">
	// A template's running order, read-only. Summaries are built from the API item itself
	// (which carries the command, bumper, trailer and tag it points at) — no reference lists needed.
	import { Layers } from '@lucide/svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import { CUE_LABEL, itemTypeDisplay } from '$lib/item-types';

	interface TemplateItem {
		id: number;
		item_type: string;
		order: number;
		feature_number?: number | null;
		bound_to_feature?: number | null;
		trailer_count?: number | null;
		match_genre?: boolean;
		match_certification?: boolean;
		match_year?: boolean;
		year_delta?: number | null;
		certification_feature?: number | null;
		count?: number;
		hold_black?: boolean;
		command?: { name?: string } | null;
		bumper?: { title?: string } | null;
		trailer?: { title?: string } | null;
		tag?: { name?: string } | null;
		trailer_tag?: { name?: string } | null;
	}

	interface Props {
		items: TemplateItem[];
	}

	let { items }: Props = $props();

	const ordered = $derived([...items].sort((a, b) => a.order - b.order));

	function title(item: TemplateItem): string {
		switch (item.item_type) {
			case 'feature':
				return `Feature ${item.feature_number ?? ''}`.trim();
			case 'trailer_rule':
				return `Trailers${item.bound_to_feature ? ` for feature ${item.bound_to_feature}` : ''}`;
			case 'trailer':
				return item.trailer?.title || 'Trailer';
			case 'bumper':
				// A tag set = a random pick; else a specific clip.
				if (item.tag?.name) return `Random: ${item.tag.name}`;
				return item.bumper?.title || 'User media';
			case 'audio_bumper':
				return item.bound_to_feature
					? `Audio for feature ${item.bound_to_feature}`
					: 'Audio user media';
			case 'command':
				return item.command?.name || 'Command';
			case 'certification':
				return item.certification_feature
					? `Certificate for feature ${item.certification_feature}`
					: 'Certificate card';
			default:
				return itemTypeDisplay(item.item_type).label;
		}
	}

	function summary(item: TemplateItem): string {
		switch (item.item_type) {
			case 'trailer_rule': {
				const bits: string[] = [];
				if (item.match_genre) bits.push('genre');
				if (item.match_certification) bits.push('rating');
				if (item.match_year && item.year_delta) bits.push(`±${item.year_delta}y`);
				const count = item.trailer_count ?? 3;
				let text = `${count} trailer${count === 1 ? '' : 's'}`;
				if (bits.length) text += ` matching ${bits.join(', ')}`;
				if (item.trailer_tag?.name) text += ` · ${item.trailer_tag.name}`;
				return text;
			}
			case 'command':
				return item.hold_black ? 'Holds a black screen until it finishes' : 'Fires as a cue';
			case 'bumper':
				// Only the random mode has a count worth showing.
				if (!item.tag) return '';
				return (item.count ?? 1) > 1 ? `${item.count} clips` : 'One clip';
			case 'audio_bumper':
				return item.bound_to_feature ? `Matches feature ${item.bound_to_feature}` : '';
			case 'feature':
				return 'Filled when a programme is built from this template';
			default:
				return '';
		}
	}

	function badgeLabel(item: TemplateItem): string | undefined {
		return item.item_type === 'command' && !item.hold_black ? CUE_LABEL : undefined;
	}
</script>

{#if !ordered.length}
	<div class="p-4">
		<EmptyState
			icon={Layers}
			title="This template is empty"
			message="Add items to build the shape a programme will follow."
			compact
		/>
	</div>
{:else}
	<ul class="divide-y divide-border">
		{#each ordered as item, i (item.id)}
			{@const type = itemTypeDisplay(item.item_type)}
			{@const Icon = type.icon}
			<li class="flex items-baseline gap-3 py-3 pr-3 pl-3 {type.classes.edge}">
				<span class="w-6 shrink-0 text-right font-mono text-xs text-faint">
					{String(i + 1).padStart(2, '0')}
				</span>
				<Icon size={14} class="shrink-0 self-center {type.classes.icon}" aria-hidden="true" />
				<span class="shrink-0 self-center">
					<TypeBadge type={item.item_type} label={badgeLabel(item)} short col />
				</span>
				<span class="min-w-0 flex-1">
					<span class="block truncate text-sm font-medium">{title(item)}</span>
					{#if summary(item)}
						<span class="block truncate text-xs text-muted">{summary(item)}</span>
					{/if}
				</span>
			</li>
		{/each}
	</ul>
{/if}
