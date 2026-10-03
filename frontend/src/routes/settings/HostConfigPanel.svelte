<script lang="ts">
	import { AlertTriangle, RefreshCw, Save } from '@lucide/svelte';
	import { showToast } from '$lib/toast.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import HostConfigFields from '$lib/playout/HostConfigFields.svelte';
	import {
		loadHostConfig,
		saveHostConfig,
		type Hardware,
		type LaunchConfig
	} from '$lib/playout/host-config';

	interface Props {
		hostId: number;
		kind: string;
	}

	const { hostId, kind }: Props = $props();

	let config = $state<LaunchConfig | null>(null);
	let hardware = $state<Hardware | null>(null);
	let loading = $state(true);
	let loadError = $state<string | null>(null);
	let saving = $state(false);
	let restartPending = $state(false);

	async function load() {
		loading = true;
		loadError = null;
		try {
			({ config, hardware } = await loadHostConfig(hostId));
		} catch (e) {
			loadError = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (kind === 'agent') void load();
		else loading = false;
	});

	async function save(thenRestart: boolean) {
		if (!config) return;
		saving = true;
		try {
			restartPending = await saveHostConfig(hostId, config, thenRestart);
			showToast(
				thenRestart && !restartPending ? 'Saved. The player is restarting' : 'Saved',
				'success'
			);
		} catch (e) {
			showToast(e instanceof Error ? e.message : String(e), 'error');
		} finally {
			saving = false;
		}
	}
</script>

{#if kind !== 'agent'}
	<p class="p-3 text-sm text-muted">
		A local mpv host has no agent, so Cinefin cannot configure it. Set its display and audio through
		mpv's own options when you launch it.
	</p>
{:else if loading}
	<div class="p-3"><Spinner size="sm" label="Reading the host's configuration…" /></div>
{:else if loadError}
	<div class="p-3"><ErrorState compact message={loadError} retry={() => void load()} /></div>
{:else if config}
	<div class="max-w-2xl space-y-5 p-4">
		<HostConfigFields bind:config {hardware} idPrefix="hc-{hostId}" />

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
