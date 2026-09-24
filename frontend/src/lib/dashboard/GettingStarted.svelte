<script lang="ts">
	import { base } from '$app/paths';
	import { Check, X } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';

	export interface Step {
		label: string;
		done: boolean;
		note?: string;
		href?: string;
		action?: string;
	}

	interface Props {
		steps: Step[];
		ready?: boolean;
		/**
		 * Whether the panel is on screen. The dashboard's own "no playout host"
		 * banner reads this and stands down while the checklist is up, so a new
		 * operator is told about the player once, not twice.
		 */
		visible?: boolean;
	}

	let { steps, ready = true, visible = $bindable(false) }: Props = $props();

	const DISMISS_KEY = 'cpx-getting-started-done';

	// localStorage can throw (private windows, blocked site data) and is only a
	// per-viewer convenience here — a failure just means the panel shows again.
	function readDismissed(): boolean {
		try {
			return localStorage.getItem(DISMISS_KEY) === '1';
		} catch {
			return false;
		}
	}

	let dismissed = $state(readDismissed());

	const complete = $derived(steps.every((s) => s.done));
	const doneCount = $derived(steps.filter((s) => s.done).length);
	// Only the next outstanding step offers an action: one thing at a time.
	const nextIndex = $derived(steps.findIndex((s) => !s.done));

	function dismiss() {
		dismissed = true;
		try {
			localStorage.setItem(DISMISS_KEY, '1');
		} catch {
			// Not persisting is survivable; the panel simply returns next load.
		}
	}

	// Finishing the last step retires the panel permanently.
	$effect(() => {
		if (complete && !dismissed) dismiss();
	});

	const show = $derived(ready && !dismissed && !complete);
	$effect(() => {
		visible = show;
	});
</script>

{#if show}
	<Card title="Get started" class="mb-4">
		{#snippet actions()}
			<span class="font-mono text-xs text-faint">{doneCount} of {steps.length}</span>
			<button
				type="button"
				class="ml-3 text-faint hover:text-text"
				title="Hide this"
				onclick={dismiss}
			>
				<X size={14} />
				<span class="sr-only">Hide getting started</span>
			</button>
		{/snippet}

		<ul class="-my-1 divide-y divide-border">
			{#each steps as step, i (step.label)}
				<li class="flex items-center gap-3 py-1.5">
					{#if step.done}
						<Check size={14} class="shrink-0 text-success" />
					{:else}
						<span class="size-3.5 shrink-0 border border-border-strong" aria-hidden="true"></span>
					{/if}

					<span class="min-w-0 flex-1 truncate text-sm {step.done ? 'text-muted' : 'text-text'}">
						{step.label}
					</span>

					{#if step.done && step.note}
						<span class="shrink-0 font-mono text-xs text-faint">{step.note}</span>
					{:else if i === nextIndex && step.href}
						<Button size="sm" variant="primary" href={step.href}>{step.action ?? 'Open'}</Button>
					{/if}
				</li>
			{/each}
		</ul>
	</Card>
{/if}
