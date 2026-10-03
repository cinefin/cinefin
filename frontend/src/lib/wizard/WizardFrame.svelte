<script lang="ts" module>
	import type { LucideIcon } from '@lucide/svelte';

	export interface RailStep {
		id: string;
		label: string;
		done?: boolean;
		/** Can it be clicked to go there? */
		enabled?: boolean;
	}
	export interface RailGroup {
		id: string;
		label: string;
		icon: LucideIcon;
		done?: boolean;
		enabled?: boolean;
		/** The group's own steps, listed under it while it is the current group. */
		steps?: RailStep[];
	}
	export interface WizardAction {
		label: string;
		onclick: () => void;
		disabled?: boolean;
		icon?: 'back' | 'next' | 'check' | 'home' | 'none';
	}
</script>

<script lang="ts">
	// One frame for setup and Add a player: the step list, the step's title and content, and
	// one row of buttons, so the player's steps read as part of setup.
	import { ArrowLeft, ArrowRight, Check, CircleCheck, House } from '@lucide/svelte';
	import type { Snippet } from 'svelte';
	import Button from '$lib/components/ui/Button.svelte';

	interface Props {
		groups: RailGroup[];
		/** The current group, and the step within it when it has steps. */
		group: string;
		step?: string;
		title: string;
		subtitle?: string;
		back?: WizardAction | null;
		skip?: WizardAction | null;
		next?: WizardAction | null;
		error?: string;
		onselect?: (group: string, step?: string) => void;
		/** Inside a dialog: a narrower list and less padding. */
		compact?: boolean;
		children: Snippet;
	}
	let {
		groups,
		group,
		step,
		title,
		subtitle,
		back,
		skip,
		next,
		error,
		onselect,
		compact = false,
		children
	}: Props = $props();

	const current = $derived(groups.find((g) => g.id === group));
	const currentStep = $derived(current?.steps?.find((s) => s.id === step));
	const groupIndex = $derived(groups.findIndex((g) => g.id === group));
	const whereLabel = $derived(
		[
			groups.length > 1 ? `${groupIndex + 1} of ${groups.length}` : '',
			[current?.label, currentStep?.label].filter(Boolean).join(' › ')
		]
			.filter(Boolean)
			.join(' · ')
	);
</script>

<div class="flex min-h-full flex-col lg:flex-row">
	<nav
		aria-label="Steps"
		class="hidden shrink-0 border-border bg-shell lg:block lg:border-r
			{compact ? 'w-52 px-3 py-5' : 'w-72 px-5 py-10'}"
	>
		<ol class="space-y-1">
			{#each groups as g (g.id)}
				{@const on = g.id === group}
				<li>
					<button
						type="button"
						class="flex h-9 w-full items-center gap-2.5 px-3 text-left text-sm
							{on
							? 'bg-surface-2 font-semibold text-text'
							: g.done
								? 'text-muted enabled:hover:text-text'
								: 'text-faint'}"
						aria-current={on && !g.steps?.length ? 'step' : undefined}
						disabled={on || !g.enabled || !onselect}
						onclick={() => onselect?.(g.id)}
					>
						{#if g.done && !on}
							<CircleCheck size={16} class="shrink-0 text-success" />
						{:else}
							<g.icon size={16} class="shrink-0" />
						{/if}
						{g.label}
					</button>
					{#if on && g.steps?.length}
						<ol class="mt-1 mb-2 space-y-0.5 pl-9">
							{#each g.steps as s (s.id)}
								{@const here = s.id === step}
								<li>
									<button
										type="button"
										class="flex h-8 w-full items-center gap-2.5 text-left text-[0.8125rem]
											{here ? 'font-medium text-text' : s.done ? 'text-muted enabled:hover:text-text' : 'text-faint'}"
										aria-current={here ? 'step' : undefined}
										disabled={here || !s.enabled || !onselect}
										onclick={() => onselect?.(g.id, s.id)}
									>
										{#if s.done && !here}
											<Check size={13} class="shrink-0 text-success" />
										{:else}
											<span
												class="mx-[3px] h-[7px] w-[7px] shrink-0 {here
													? 'bg-accent'
													: 'bg-border-strong'}"
											></span>
										{/if}
										{s.label}
									</button>
								</li>
							{/each}
						</ol>
					{/if}
				</li>
			{/each}
		</ol>
	</nav>

	<div
		class="flex min-w-0 flex-1 flex-col gap-6 {compact
			? 'p-5 sm:p-6'
			: 'mx-auto w-full max-w-3xl px-4 py-8 sm:px-8 lg:mx-0 lg:px-14 lg:py-12'}"
	>
		<header>
			<!-- Where you are, for the screens the step list doesn't fit. -->
			<p class="mb-2 text-xs text-muted lg:hidden">{whereLabel}</p>
			<h1 class="{compact ? 'text-lg' : 'text-2xl'} leading-tight font-semibold text-text">
				{title}
			</h1>
			{#if subtitle}
				<p class="mt-1.5 max-w-xl text-sm text-muted">{subtitle}</p>
			{/if}
		</header>

		<div class="min-w-0">{@render children()}</div>

		{#if error}
			<div class="border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
				{error}
			</div>
		{/if}

		{#if back || skip || next}
			<div class="mt-auto flex flex-wrap items-center gap-2 border-t border-border pt-5">
				{#if back}
					<Button variant="ghost" disabled={back.disabled} onclick={back.onclick}>
						{#if back.icon !== 'none'}<ArrowLeft size={14} />{/if}
						{back.label}
					</Button>
				{/if}
				<div class="ml-auto flex flex-wrap items-center gap-2">
					{#if skip}
						<Button variant="ghost" disabled={skip.disabled} onclick={skip.onclick}>
							{skip.label}
						</Button>
					{/if}
					{#if next}
						<Button variant="primary" disabled={next.disabled} onclick={next.onclick}>
							{#if next.icon === 'check'}<Check size={14} />{:else if next.icon === 'home'}<House
									size={14}
								/>{/if}
							{next.label}
							{#if !next.icon || next.icon === 'next'}<ArrowRight size={14} />{/if}
						</Button>
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>
