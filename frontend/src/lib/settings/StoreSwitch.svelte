<script lang="ts">
	// A switch for one boolean of the settings draft, for a SettingRow's right column (the row
	// names it). It saves itself with the rest of the draft.
	import Switch from '$lib/components/ui/Switch.svelte';
	import type { MainDraft, SettingsStore } from './form.svelte';

	type BoolKey = {
		[K in keyof MainDraft]: MainDraft[K] extends boolean ? K : never;
	}[keyof MainDraft];

	let { store, field, label }: { store: SettingsStore; field: BoolKey; label: string } = $props();
</script>

<Switch
	label=""
	ariaLabel={label}
	checked={store.main[field]}
	onchange={(on) => (store.main[field] = on)}
/>
