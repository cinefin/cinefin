<script lang="ts">
	interface Props {
		value?: string;
		type?: 'text' | 'search' | 'number' | 'password' | 'email';
		placeholder?: string;
		id?: string;
		name?: string;
		disabled?: boolean;
		class?: string;
		oninput?: (event: Event) => void;
		onchange?: (event: Event) => void;
	}

	let {
		value = $bindable(''),
		type = 'text',
		placeholder,
		id,
		name,
		disabled = false,
		class: cls = '',
		oninput,
		onchange
	}: Props = $props();
</script>

<input
	{type}
	{id}
	{name}
	{placeholder}
	{disabled}
	{oninput}
	{onchange}
	bind:value
	class="h-9 w-full max-w-xl rounded-md border border-border bg-surface-2 px-3 text-sm text-text
		transition-colors placeholder:text-faint hover:border-border-strong
		focus:border-accent focus:ring-1 focus:ring-inset focus:ring-accent/45 focus:outline-none
		disabled:opacity-45 disabled:hover:border-border {cls}"
/>
