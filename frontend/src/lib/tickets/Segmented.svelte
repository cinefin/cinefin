<script lang="ts" generics="T">
	// A row of pressed buttons for a short choice (alignment, size).
	import type { Choice } from './kinds';

	interface Props {
		choices: Choice<T>[];
		value: T;
		label: string;
		onchange: (value: T) => void;
	}
	let { choices, value, label, onchange }: Props = $props();

	const same = (a: T, b: T) => JSON.stringify(a) === JSON.stringify(b);
</script>

<div class="inline-flex flex-wrap border border-border-strong" role="group" aria-label={label}>
	{#each choices as choice, i (i)}
		<button
			type="button"
			class="h-8 border-r border-border-strong px-2.5 text-xs font-medium text-muted last:border-r-0
				hover:text-text aria-pressed:bg-surface-3 aria-pressed:text-text"
			aria-pressed={same(choice.id, value)}
			title={choice.hint}
			onclick={() => onchange(choice.id)}>{choice.label}</button
		>
	{/each}
</div>
