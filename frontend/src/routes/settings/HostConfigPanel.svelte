<script lang="ts">
	import { AlertTriangle, RefreshCw, Save } from '@lucide/svelte';
	import { showToast } from '$lib/toast.svelte';
	import { query } from '$lib/api/query.svelte';
	import { attempt } from '$lib/settings/form.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import HostConfigFields from '$lib/playout/HostConfigFields.svelte';
	import { loadHostConfig, saveHostConfig } from '$lib/playout/host-config';

	const { hostId }: { hostId: number } = $props();

	const host = query(() => loadHostConfig(hostId));
	let saving = $state(false);
	let restartPending = $state(false);

	async function save(thenRestart: boolean) {
		if (!host.data) return;
		const draft = host.data.config;
		saving = true;
		await attempt(async () => {
			restartPending = await saveHostConfig(hostId, draft, thenRestart);
			showToast(
				thenRestart && !restartPending ? 'Saved. The player is restarting' : 'Saved',
				'success'
			);
		}, 'Could not save');
		saving = false;
	}
</script>

{#if host.loading}
	<div class="p-3"><Spinner size="sm" label="Reading the host's configuration…" /></div>
{:else if host.error}
	<div class="p-3"><ErrorState compact error={host.error} retry={() => void host.load()} /></div>
{:else if host.data}
	<div class="max-w-2xl space-y-5 p-4">
		<HostConfigFields
			bind:config={host.data.config}
			hardware={host.data.hardware}
			idPrefix="hc-{hostId}"
		/>

		<div class="flex flex-wrap items-center gap-2 border-t border-border pt-3">
			<Button variant="primary" disabled={saving} onclick={() => void save(false)}>
				<Save size={13} /> Save
			</Button>
			<Button disabled={saving} onclick={() => void save(true)}>
				<RefreshCw size={13} /> Save and restart the player
			</Button>
			{#if restartPending}
				<span class="flex items-center gap-1.5 text-xs text-warning">
					<AlertTriangle size={13} /> Saved - takes effect when the player restarts.
				</span>
			{/if}
		</div>
	</div>
{/if}
