<script lang="ts">
	// A Toggle bound to one boolean of the settings draft (it saves itself), with its pending mark.
	import Toggle from '$lib/components/ui/Toggle.svelte';
	import type { MainDraft, SettingsStore } from './form.svelte';

	type BoolKey = {
		[K in keyof MainDraft]: MainDraft[K] extends boolean ? K : never;
	}[keyof MainDraft];

	interface Props {
		store: SettingsStore;
		field: BoolKey;
		label: string;
		hint?: string;
	}
	let { store, field, label, hint }: Props = $props();
</script>

<Toggle {label} {hint} bind:checked={store.main[field]} dirty={store.isDirty(field)} />
