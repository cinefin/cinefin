<script lang="ts">
	// Renders a provider's declared fields (command config or provider settings) generically.
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import {
		suggestionsFor,
		type FormValues,
		type ProviderField,
		type Suggestion
	} from './providers';

	interface Props {
		fields: ProviderField[];
		values: FormValues;
		suggestions?: Record<string, Suggestion[]>;
		/** Unique per form, so ids and datalists never collide. */
		idPrefix: string;
	}

	let { fields, values = $bindable(), suggestions = {}, idPrefix }: Props = $props();

	const textareaClass =
		'w-full rounded-md border border-border-strong bg-surface-2 px-3 py-2 font-mono text-sm text-text placeholder:text-faint focus:border-accent-dim';
	const datalistInputClass =
		'h-9 w-full rounded-md border border-border-strong bg-surface-2 px-3 text-sm text-text placeholder:text-faint focus:border-accent-dim';
</script>

{#each fields as f (f.key)}
	{@const id = `${idPrefix}-${f.key}`}
	{@const options = f.type === 'text' ? suggestionsFor(f, values, suggestions) : []}
	<div>
		{#if f.type === 'boolean'}
			<label class="flex items-center gap-2 text-sm text-muted" for={id}>
				<input
					{id}
					type="checkbox"
					bind:checked={() => values[f.key] === 'true', (on) => (values[f.key] = on ? 'true' : '')}
				/>
				{f.label}
			</label>
		{:else}
			<label class="mb-1 block text-sm text-muted" for={id}>
				{f.label}{f.required ? ' *' : ''}
			</label>
			{#if f.type === 'select'}
				<Select
					{id}
					bind:value={() => values[f.key] ?? '', (v) => (values[f.key] = v)}
					class="w-full"
				>
					{#if !f.required && !f.default}<option value=""></option>{/if}
					{#each f.choices as choice (choice)}
						<option value={choice}>{choice}</option>
					{/each}
				</Select>
			{:else if f.type === 'json' || f.type === 'textarea'}
				<textarea
					{id}
					bind:value={() => values[f.key] ?? '', (v) => (values[f.key] = v)}
					rows={f.type === 'json' ? 3 : 4}
					placeholder={f.placeholder}
					class={textareaClass}
				></textarea>
			{:else if options.length}
				<input
					{id}
					type="text"
					bind:value={() => values[f.key] ?? '', (v) => (values[f.key] = v)}
					placeholder={f.placeholder}
					list="{id}-list"
					class={datalistInputClass}
				/>
				<datalist id="{id}-list">
					{#each options as s (s.value)}
						<option value={s.value} label={s.label ?? undefined}></option>
					{/each}
				</datalist>
			{:else}
				<Input
					{id}
					type={f.type === 'secret' ? 'password' : f.type === 'number' ? 'number' : 'text'}
					bind:value={() => values[f.key] ?? '', (v) => (values[f.key] = v)}
					placeholder={f.placeholder}
					class="max-w-none"
				/>
			{/if}
		{/if}
		{#if f.help}<p class="mt-1 text-xs text-faint">{f.help}</p>{/if}
	</div>
{/each}
