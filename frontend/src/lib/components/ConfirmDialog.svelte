<script lang="ts">
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';

	/** Awaitable confirm dialog. Pages hold one instance and `await confirm('Delete X?')`. */

	interface Props {
		title?: string;
		confirmLabel?: string;
	}
	let { title = 'Are you sure?', confirmLabel = 'Confirm' }: Props = $props();

	let open = $state(false);
	let message = $state('');
	let label = $state('');
	let titleOverride = $state<string | null>(null);
	let danger = $state(true);
	let resolver: ((ok: boolean) => void) | null = null;

	export function confirm(
		text: string,
		opts?: { confirmLabel?: string; title?: string; danger?: boolean }
	): Promise<boolean> {
		message = text;
		label = opts?.confirmLabel ?? confirmLabel;
		titleOverride = opts?.title ?? null;
		danger = opts?.danger ?? true;
		open = true;
		return new Promise((resolve) => {
			resolver = resolve;
		});
	}

	function settle(ok: boolean) {
		open = false;
		resolver?.(ok);
		resolver = null;
	}

	// Closing by any other route (Escape, backdrop, the header X) is a "no".
	$effect(() => {
		if (!open && resolver) settle(false);
	});
</script>

<Dialog bind:open title={titleOverride ?? title}>
	<p class="text-sm text-muted">{message}</p>
	{#snippet footer()}
		<Button onclick={() => settle(false)}>Cancel</Button>
		<Button variant={danger ? 'danger' : 'primary'} onclick={() => settle(true)}>
			{label || confirmLabel}
		</Button>
	{/snippet}
</Dialog>
