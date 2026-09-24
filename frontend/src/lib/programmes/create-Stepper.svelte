<script lang="ts">
	import { Check } from '@lucide/svelte';

	interface WizardStep {
		id: string;
		label: string;
		summary?: string;
		enabled: boolean;
		done: boolean;
	}

	interface Props {
		steps: WizardStep[];
		current: string;
		onselect: (id: string) => void;
	}

	let { steps, current, onselect }: Props = $props();
</script>

<ol class="flex flex-col gap-2 sm:flex-row">
	{#each steps as step, i (step.id)}
		{@const active = step.id === current}
		<li class="flex min-w-0 flex-1 items-center gap-2">
			<button
				type="button"
				disabled={!step.enabled || active}
				aria-current={active ? 'step' : undefined}
				class="flex min-w-0 flex-1 items-center gap-2.5 border px-3 py-2 text-left
					transition-colors {active
					? 'border-accent bg-surface-2'
					: step.enabled
						? 'border-border bg-surface-1 hover:border-border-strong'
						: 'border-border bg-surface-1 opacity-45'}"
				onclick={() => onselect(step.id)}
			>
				<span
					class="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm border text-xs
						font-medium {active ? 'border-accent text-accent' : 'border-border-strong text-muted'}"
					aria-hidden="true"
				>
					{#if step.done && !active}<Check size={13} />{:else}{i + 1}{/if}
				</span>
				<span class="min-w-0">
					<span class="block truncate text-sm font-medium">{step.label}</span>
					<span class="block truncate text-xs {step.summary ? 'text-muted' : 'text-faint'}">
						{step.summary || 'Not yet'}
					</span>
				</span>
			</button>
		</li>
	{/each}
</ol>
