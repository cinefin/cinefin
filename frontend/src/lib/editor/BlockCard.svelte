<script lang="ts" generics="M">
	import { ChevronDown, ChevronUp, Copy, GripVertical, TriangleAlert, X } from '@lucide/svelte';
	import type { Component } from 'svelte';
	import { CUE_LABEL, itemTypeDisplay } from '$lib/item-types';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import { blockSummary, blockTitle } from './display';
	import type { BlockEditor } from './editor.svelte';
	import type { EditorBlock, EditorContext } from './types';
	import AudioBumperConfig from './config/AudioBumperConfig.svelte';
	import BumperConfig from './config/BumperConfig.svelte';
	import CertificationConfig from './config/CertificationConfig.svelte';
	import CommandConfig from './config/CommandConfig.svelte';
	import FeatureConfig from './config/FeatureConfig.svelte';
	import MovieConfig from './config/MovieConfig.svelte';
	import RandomMovieConfig from './config/RandomMovieConfig.svelte';
	import TrailerConfig from './config/TrailerConfig.svelte';
	import TrailerRuleConfig from './config/TrailerRuleConfig.svelte';

	interface Props {
		block: EditorBlock;
		index: number;
		total: number;
		ctx: EditorContext;
		editor: BlockEditor<M>;
		error?: string | null;
		onremove: (index: number) => void;
	}

	let { block, index, total, ctx, editor, error = null, onremove }: Props = $props();

	type ConfigComponent = Component<{
		block: EditorBlock;
		ctx: EditorContext;
		commit: (mutate: () => void) => void;
	}>;

	const CONFIGS: Record<string, Record<string, ConfigComponent>> = {
		programme: {
			movie: MovieConfig,
			trailer_rule: TrailerRuleConfig,
			command: CommandConfig,
			// `random_bumper` maps here defensively: legacy values the adapter didn't normalise still open this panel.
			bumper: BumperConfig,
			random_bumper: BumperConfig,
			trailer: TrailerConfig,
			random_movie: RandomMovieConfig,
			certification: CertificationConfig,
			audio_bumper: AudioBumperConfig
		},
		template: {
			feature: FeatureConfig,
			trailer_rule: TrailerRuleConfig,
			command: CommandConfig,
			bumper: BumperConfig,
			random_bumper: BumperConfig,
			trailer: TrailerConfig,
			certification: CertificationConfig,
			audio_bumper: AudioBumperConfig
		}
	};

	const ConfigPanel = $derived(CONFIGS[ctx.mode][block.type]);
	const canExpand = $derived(!!ConfigPanel);
	const expanded = $derived(canExpand && editor.isExpanded(block.uid));
	const isCue = $derived(block.type === 'command' && !block.content.hold_black);
	const type = $derived(itemTypeDisplay(block.type));
	const Icon = $derived(type.icon);
	const summary = $derived(blockSummary(block, ctx));

	let headerEl = $state<HTMLDivElement>();

	function commit(mutate: () => void): void {
		editor.commit(mutate);
	}

	function toggle(): void {
		if (canExpand) editor.toggleExpand(index);
	}

	function onHeaderClick(e: MouseEvent): void {
		if ((e.target as HTMLElement).closest('button')) return;
		toggle();
	}

	function onHeaderKeydown(e: KeyboardEvent): void {
		if (e.target !== e.currentTarget) return;
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			toggle();
		}
	}

	function onCardKeydown(e: KeyboardEvent): void {
		if (e.key !== 'Escape' || !expanded) return;
		e.stopPropagation();
		editor.collapse();
		headerEl?.focus();
	}

	const actionBtn =
		'inline-flex h-6 w-6 items-center justify-center rounded-sm text-faint transition-colors ' +
		'hover:bg-surface-3 hover:text-text disabled:pointer-events-none disabled:opacity-30';
	const tall = 'row-start-1 row-span-2 @md:row-span-1';
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class={type.classes.edge} onkeydown={onCardKeydown}>
	<div
		bind:this={headerEl}
		role="button"
		tabindex="0"
		aria-expanded={canExpand ? expanded : undefined}
		class="grid items-center gap-x-2 py-2 pr-2 outline-none select-none
			grid-cols-[1.75rem_auto_minmax(0,1fr)_auto]
			focus-visible:ring-1 focus-visible:ring-accent-dim focus-visible:ring-inset
			{canExpand ? 'cursor-pointer' : 'cursor-default'}"
		onclick={onHeaderClick}
		onkeydown={onHeaderKeydown}
	>
		<span class="col-start-1 {tall} flex justify-center">
			<GripVertical size={14} class="cursor-grab text-faint" aria-hidden="true" />
		</span>

		<span class="col-start-2 {tall} flex items-center gap-1.5">
			<Icon size={14} class="shrink-0 {type.classes.icon}" aria-hidden="true" />
			<TypeBadge type={block.type} label={isCue ? CUE_LABEL : undefined} short col />
		</span>

		<span class="col-start-3 row-start-1 flex min-w-0 items-baseline gap-2">
			<span class="min-w-0 truncate text-sm text-text {isCue ? '' : 'font-medium'}">
				{blockTitle(block, ctx)}
			</span>
			<span class="hidden min-w-0 items-baseline gap-2 text-xs text-muted @md:flex">
				{#if error}
					<span class="inline-flex min-w-0 items-center gap-1 text-danger">
						<TriangleAlert size={12} class="shrink-0" aria-hidden="true" />
						<span class="truncate">{error}</span>
					</span>
				{:else}
					<span class="truncate" title={summary}>{summary}</span>
				{/if}
			</span>
		</span>

		<span class="col-start-3 row-start-2 min-w-0 truncate text-xs text-muted @md:hidden">
			{#if error}
				<span class="text-danger">{error}</span>
			{:else}
				{summary}
			{/if}
		</span>

		<div class="col-start-4 {tall} flex items-center justify-end gap-0.5">
			<button
				type="button"
				class={actionBtn}
				disabled={index === 0}
				title="Move up"
				onclick={() => editor.move(index, -1)}
			>
				<ChevronUp size={14} />
			</button>
			<button
				type="button"
				class={actionBtn}
				disabled={index === total - 1}
				title="Move down"
				onclick={() => editor.move(index, 1)}
			>
				<ChevronDown size={14} />
			</button>
			<button
				type="button"
				class={actionBtn}
				title="Duplicate"
				onclick={() => editor.duplicate(index)}
			>
				<Copy size={13} />
			</button>
			<button
				type="button"
				class="{actionBtn} hover:text-danger"
				title="Remove"
				onclick={() => onremove(index)}
			>
				<X size={14} />
			</button>
			{#if canExpand}
				<ChevronDown
					size={14}
					class="ml-0.5 shrink-0 text-faint transition-transform {expanded ? 'rotate-180' : ''}"
					aria-hidden="true"
				/>
			{/if}
		</div>
	</div>

	{#if expanded && ConfigPanel}
		<div class="border-t border-border bg-surface-2/40 px-4 py-3" data-no-drag>
			<div class="mb-2.5 flex items-center gap-1.5 text-xs font-medium text-muted">
				<Icon size={12} class={type.classes.icon} aria-hidden="true" />
				{isCue ? CUE_LABEL : type.label}
			</div>
			<ConfigPanel {block} {ctx} {commit} />
		</div>
	{/if}
</div>
