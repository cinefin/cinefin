<script lang="ts">
	import { base } from '$app/paths';
	import { ChevronDown, Film, Folder, RadioTower, TriangleAlert } from '@lucide/svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import { CUE_LABEL, itemTypeDisplay, itemTypeLabel } from '$lib/item-types';
	import type { ProgrammeItem, ProgrammePlaylistItem } from './types';
	import { formatDuration } from './helpers';

	interface Props {
		programmeId: number;
		onedit?: () => void;
		items: ProgrammeItem[];
		byBlock: Map<number, ProgrammePlaylistItem[]>;
		unattached: ProgrammePlaylistItem[];
	}

	let { programmeId, items, byBlock, unattached, onedit }: Props = $props();

	let expanded = $state<Set<number | string>>(new Set());
	function toggleExpand(key: number | string) {
		const next = new Set(expanded);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		expanded = next;
	}

	// Rule blocks (trailer rules, random bumpers/movies) resolve at generation:
	// once generated entries exist, their summed durations are the real runtime.
	const RESOLVED_TYPES = new Set(['trailer_rule', 'bumper', 'random_movie']);

	function effectiveRuntime(item: ProgrammeItem, children: ProgrammePlaylistItem[]): number {
		if (RESOLVED_TYPES.has(item.type) && children.length) {
			const sum = children.reduce((s, pi) => s + (pi.duration || 0), 0);
			if (sum > 0) return sum;
		}
		return item.duration_seconds;
	}

	function childSummary(children: ProgrammePlaylistItem[]): string {
		const counts = new Map<string, number>();
		for (const pi of children) {
			const label = itemTypeLabel(pi.type);
			counts.set(label, (counts.get(label) ?? 0) + 1);
		}
		return [...counts.entries()]
			.map(([label, n]) => (n > 1 ? `${label} ×${n}` : label))
			.join(' · ');
	}

	function blockDetails(item: ProgrammeItem): string {
		const d = item.details ?? {};
		switch (item.type) {
			case 'movie': {
				if (d.missing) {
					const bits = ['removed from library'];
					if (d.year) bits.unshift(String(d.year));
					return bits.join(' · ');
				}
				const parts: string[] = [];
				if (d.year) parts.push(String(d.year));
				if (d.certification) parts.push(d.certification);
				if (d.audio_track !== undefined && d.audio_track !== null)
					parts.push(`audio ${d.audio_track}`);
				if (d.subtitle_track !== undefined && d.subtitle_track !== null)
					parts.push(`sub ${d.subtitle_track}`);
				return parts.join(' · ');
			}
			case 'trailer_rule': {
				const criteria: string[] = [];
				if (d.genre_ids?.length) criteria.push('genres');
				else if (d.match_genres) criteria.push('genres');
				if (d.certificate_ceiling) criteria.push(`≤ ${d.certificate_ceiling}`);
				else if (d.match_certification) criteria.push('rating');
				if (d.year_from && d.year_to) criteria.push(`${d.year_from}-${d.year_to}`);
				else if (d.year_from) criteria.push(`${d.year_from}+`);
				else if (d.year_to) criteria.push(`≤ ${d.year_to}`);
				else if (d.year_delta) criteria.push(`±${d.year_delta}y`);
				if (d.trailer_tag_name) criteria.push(`tagged ${d.trailer_tag_name}`);
				let text = `${d.count || 3} trailers`;
				if (criteria.length) text += ` matching ${criteria.join(', ')}`;
				return text;
			}
			case 'certification':
				if (d.certification) return `${d.certification} certificate`;
				if (d.for_random_movie) return 'for random movie selection';
				return '';
			case 'random_movie': {
				const filters: string[] = [];
				if (d.genre_names?.length) filters.push(d.genre_names.join(', '));
				if (d.certification) filters.push(d.certification);
				if (d.year_from && d.year_to) filters.push(`${d.year_from}-${d.year_to}`);
				else if (d.year_from) filters.push(`${d.year_from}+`);
				else if (d.year_to) filters.push(`≤${d.year_to}`);
				return filters.length ? filters.join(' · ') : 'any movie';
			}
			case 'bumper':
				if (d.tag_name) return `random · ${d.tag_name}`;
				if (d.tag_id) return `random · tag ${d.tag_id}`;
				return d.year ? String(d.year) : '';
			case 'trailer':
				return d.year ? String(d.year) : '';
		}
		return '';
	}

	function matchTier(
		pi: ProgrammePlaylistItem
	): { label: string; detail: string; filler: boolean } | null {
		const meta = pi.details?.metadata;
		if (!meta || !meta.rule_based_selection || !meta.match_tier) return null;
		return {
			label: meta.match_tier >= 3 ? 'unrelated filler' : 'relaxed match',
			detail:
				`Selected for ${meta.reference_movie || 'the feature'} via "${meta.match_tier_name}" ` +
				`(${meta.matched_full ?? '?'} of ${meta.requested ?? '?'} requested trailers matched the full criteria)`,
			filler: meta.match_tier >= 3
		};
	}

	// hold_black isn't in the hand-written details type — types.ts is owned elsewhere.
	function badgeLabel(item: ProgrammeItem): string | undefined {
		if (item.type !== 'command') return undefined;
		const hold = (item.details as { hold_black?: boolean } | undefined)?.hold_black;
		return hold ? undefined : CUE_LABEL;
	}
</script>

{#if !items.length && !unattached.length}
	<div class="p-4">
		<EmptyState
			icon={Film}
			title="This running order is empty"
			message="Add blocks to build it."
			compact
		>
			{#snippet action()}
				{#if onedit}
					<Button size="sm" onclick={onedit}>Edit programme</Button>
				{:else}
					<Button href="{base}/programmes/{programmeId}?edit=1" size="sm">Edit programme</Button>
				{/if}
			{/snippet}
		</EmptyState>
	</div>
{:else}
	<div class="overflow-x-auto">
		<table class="w-full text-sm">
			<tbody class="divide-y divide-border">
				{#snippet blockRow(
					item: {
						type: string;
						title: string;
						runtime: number;
						missing?: boolean;
						detailText?: string;
						badge?: string;
					},
					num: string,
					key: number | string,
					children: ProgrammePlaylistItem[]
				)}
					{@const type = itemTypeDisplay(item.type)}
					{@const Icon = type.icon}
					{@const expandable = children.length > 0}
					{@const isOpen = expanded.has(key)}
					<tr class={item.missing ? 'opacity-60' : ''}>
						<td
							class="w-11 py-3 pr-2 pl-3 text-right align-middle font-mono text-xs text-faint {type
								.classes.edge}"
						>
							{num}
						</td>
						<td class="py-3 pl-1 align-middle whitespace-nowrap">
							<span class="flex items-center gap-1.5">
								{#if item.missing}
									<TriangleAlert
										size={13}
										class="shrink-0 text-danger"
										aria-label="This movie is no longer in your library"
									/>
								{:else}
									<Icon size={14} class="shrink-0 {type.classes.icon}" aria-hidden="true" />
								{/if}
								<TypeBadge type={item.type} label={item.badge} short col />
							</span>
						</td>
						<td class="px-2 py-3 align-middle">
							<span class="flex min-w-0 items-baseline gap-x-2">
								<span class="shrink truncate font-medium">{item.title}</span>
								{#if item.detailText}
									<span class="shrink truncate text-xs text-muted">{item.detailText}</span>
								{/if}
								{#if expandable}
									<button
										type="button"
										class="inline-flex shrink-0 items-center gap-1 text-xs text-faint hover:text-text"
										title={isOpen
											? 'Hide the generated playlist entries'
											: 'Show the generated playlist entries'}
										aria-expanded={isOpen}
										onclick={() => toggleExpand(key)}
									>
										<ChevronDown
											size={12}
											class="transition-transform {isOpen ? '' : '-rotate-90'}"
										/>
										{childSummary(children)}
										<span class="text-faint">
											· {children.length}
											{children.length === 1 ? 'entry' : 'entries'}
										</span>
									</button>
								{/if}
							</span>
						</td>
						<td class="w-20 px-3 py-3 text-right align-middle font-mono text-xs whitespace-nowrap">
							{formatDuration(item.runtime)}
						</td>
					</tr>
					{#if isOpen}
						{#each children as pi (pi.order)}
							{@const tier = matchTier(pi)}
							{@const isStream = /^https?:/i.test(pi.file_path || '')}
							{@const childType = itemTypeDisplay(pi.type)}
							<tr class="bg-surface-2/40">
								<td class="px-3 py-2 {childType.classes.edge}"></td>
								<td class="py-2 pr-2 pl-8" colspan="2">
									<span class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
										<span>{pi.title}</span>
										{#if pi.details?.metadata?.year}
											<span class="font-mono text-faint">{pi.details.metadata.year}</span>
										{/if}
										<span class="text-muted">{itemTypeLabel(pi.type)}</span>
										{#if tier}
											<span title={tier.detail}>
												<Badge variant={tier.filler ? 'danger' : 'warning'}>
													{tier.label}
												</Badge>
											</span>
										{/if}
										<span
											class="inline-flex min-w-0 items-center gap-1 font-mono text-faint"
											title={pi.file_path}
										>
											{#if isStream}
												<RadioTower size={10} class="shrink-0" />
											{:else}
												<Folder size={10} class="shrink-0" />
											{/if}
											<span class="max-w-72 truncate">{pi.file_path || '-'}</span>
										</span>
									</span>
								</td>
								<td class="px-3 py-2 text-right font-mono text-xs whitespace-nowrap">
									{formatDuration(pi.duration)}
								</td>
							</tr>
						{/each}
					{/if}
				{/snippet}

				{#if unattached.length}
					{@render blockRow(
						{
							type: 'system',
							title: 'Pre-show & generated items',
							runtime: unattached.reduce((sum, pi) => sum + (pi.duration || 0), 0)
						},
						'-',
						'preshow',
						unattached
					)}
				{/if}
				{#each items as item, i (item.id)}
					{@const children = byBlock.get(item.id) ?? []}
					{@render blockRow(
						{
							type: item.type,
							title: item.title,
							runtime: effectiveRuntime(item, children),
							missing: !!item.details?.missing,
							detailText: blockDetails(item),
							badge: badgeLabel(item)
						},
						String(i + 1).padStart(2, '0'),
						item.id,
						children
					)}
				{/each}
			</tbody>
		</table>
	</div>
{/if}
