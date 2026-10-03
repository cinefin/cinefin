<script lang="ts">
	/**
	 * The pairing code: one box per digit, grouped 3 + 3 like the player's
	 * screen shows it. Typing moves to the next box, Backspace to the previous,
	 * and a pasted code (with or without its space) fills every box.
	 */
	import { CODE_LENGTH, codeDigits } from './wizard';

	interface Props {
		/** Two-way: the digits entered so far. */
		value?: string;
		invalid?: boolean;
		disabled?: boolean;
		/** Called once all six digits are in. */
		oncomplete?: (code: string) => void;
	}

	let { value = $bindable(''), invalid = false, disabled = false, oncomplete }: Props = $props();

	const boxes: HTMLInputElement[] = [];

	export function focus() {
		boxes[Math.min(value.length, CODE_LENGTH - 1)]?.focus();
	}

	function set(next: string, focusAt: number) {
		value = codeDigits(next);
		boxes[Math.min(focusAt, value.length, CODE_LENGTH - 1)]?.focus();
		if (value.length === CODE_LENGTH) oncomplete?.(value);
	}

	// Typing (or a phone's one-time-code autofill) into box i: the digits
	// replace from i onward.
	function oninput(i: number, e: Event) {
		const input = e.target as HTMLInputElement;
		let typed = codeDigits(input.value);
		// One digit typed beside the box's own (the caret was not on it): keep the new one.
		const old = value[i];
		if (old && typed.length === 2) typed = typed[0] === old ? typed[1] : typed[0];
		input.value = value[i] ?? '';
		if (!typed) return;
		set(value.slice(0, i) + typed + value.slice(i + typed.length), i + typed.length);
	}

	function onpaste(i: number, e: ClipboardEvent) {
		const text = codeDigits(e.clipboardData?.getData('text') ?? '');
		if (!text) return;
		e.preventDefault();
		// A whole code pasted anywhere fills from the start.
		const from = text.length === CODE_LENGTH ? 0 : i;
		set(value.slice(0, from) + text, from + text.length);
	}

	function onkeydown(i: number, e: KeyboardEvent) {
		if (e.key === 'Backspace') {
			e.preventDefault();
			// Clear this box, or step back and clear the one before.
			const at = value[i] !== undefined ? i : i - 1;
			if (at < 0) return;
			value = value.slice(0, at) + value.slice(at + 1);
			boxes[at]?.focus();
		} else if (e.key === 'ArrowLeft' && i > 0) {
			e.preventDefault();
			boxes[i - 1]?.focus();
		} else if (e.key === 'ArrowRight' && i < CODE_LENGTH - 1) {
			e.preventDefault();
			boxes[Math.min(i + 1, value.length)]?.focus();
		}
	}
</script>

<div class="flex items-center gap-1.5 sm:gap-2" role="group" aria-label="Pairing code">
	{#each { length: CODE_LENGTH } as _, i (i)}
		{#if i === 3}<span class="w-1.5 sm:w-3" aria-hidden="true"></span>{/if}
		<input
			bind:this={boxes[i]}
			value={value[i] ?? ''}
			type="text"
			inputmode="numeric"
			autocomplete={i === 0 ? 'one-time-code' : 'off'}
			aria-label="Digit {i + 1}"
			aria-invalid={invalid || undefined}
			{disabled}
			class="h-14 w-10 rounded-md border bg-surface-2 text-center font-mono text-2xl text-text
				focus:border-accent focus:outline-none disabled:opacity-45 sm:h-16 sm:w-12 sm:text-3xl
				{invalid ? 'border-danger' : 'border-border-strong'}"
			oninput={(e) => oninput(i, e)}
			onpaste={(e) => onpaste(i, e)}
			onkeydown={(e) => onkeydown(i, e)}
			onfocus={(e) => (e.target as HTMLInputElement).select()}
		/>
	{/each}
</div>
