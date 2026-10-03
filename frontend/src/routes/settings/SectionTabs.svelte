<script lang="ts">
	// A section's tab strip; each tab controls the TabPanel with id `{prefix}-{tab}`.
	import Tabs from '$lib/components/ui/Tabs.svelte';

	interface Props {
		tabs: { id: string; label: string }[];
		value: string;
		label: string;
		prefix: string;
	}
	let { tabs, value = $bindable(), label, prefix }: Props = $props();
</script>

<Tabs {tabs} {value} {label} onselect={(id) => (value = id)} panelId={(id) => `${prefix}-${id}`} />
