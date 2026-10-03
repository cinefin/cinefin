<script lang="ts">
	// A ticket design's own page, opened from Settings › Tickets.
	import { page } from '$app/state';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import TicketDesigner from '../../TicketDesigner.svelte';

	let confirmDialog: ConfirmDialog;
	const confirm = (text: string, opts?: { confirmLabel?: string }) =>
		confirmDialog.confirm(text, opts);
</script>

<ConfirmDialog bind:this={confirmDialog} />
<TicketDesigner id={Number(page.params.id)} {confirm} />
