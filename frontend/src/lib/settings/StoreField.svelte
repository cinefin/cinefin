<script lang="ts" module>
	import type { MainDraft, SettingsStore } from './form.svelte';

	type TextKey = {
		[K in keyof MainDraft]: MainDraft[K] extends string ? K : never;
	}[keyof MainDraft];

	/** One text setting of the draft as a labelled control: an Input, a Select of `options`
	 *  ([value, label] pairs), or a native time/colour input. */
	export interface StoreFieldSpec {
		field: TextKey;
		label: string;
		id: string;
		hint?: string;
		type?: 'number' | 'time' | 'color';
		placeholder?: string;
		options?: readonly (readonly [string, string])[];
		/** The control's class. */
		input?: string;
		class?: string;
	}

	/** A spec on one line: the field, its label and control id, then the rest. */
	export const storeField = (
		field: TextKey,
		label: string,
		id: string,
		more: Omit<StoreFieldSpec, 'field' | 'label' | 'id'> = {}
	): StoreFieldSpec => ({ field, label, id, ...more });
</script>

<script lang="ts">
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Field from './Field.svelte';

	let {
		store,
		field,
		label,
		id,
		hint,
		type,
		placeholder,
		options,
		input = '',
		class: cls
	}: StoreFieldSpec & { store: SettingsStore } = $props();
</script>

<Field {label} forId={id} {hint} {store} {field} class={cls}>
	{#if options}
		<Select {id} bind:value={store.main[field]} class={input}>
			{#each options as [value, text] (value)}
				<option {value}>{text}</option>
			{/each}
		</Select>
	{:else if type === 'time' || type === 'color'}
		<input {id} {type} bind:value={store.main[field]} class={input} />
	{:else}
		<Input {id} {type} bind:value={store.main[field]} {placeholder} class={input} />
	{/if}
</Field>
