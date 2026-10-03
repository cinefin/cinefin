<script lang="ts">
	// A player's screen and sound. Saves itself; a change that needs the player restarted says so.
	import { onDestroy, untrack } from 'svelte';
	import { RotateCw } from '@lucide/svelte';
	import { api } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { showToast } from '$lib/toast.svelte';
	import { query } from '$lib/api/query.svelte';
	import { attempt } from '$lib/settings/form.svelte';
	import { AutoSave } from '$lib/settings/autosave.svelte';
	import SaveState from '$lib/settings/SaveState.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import HostConfigFields from '$lib/playout/HostConfigFields.svelte';
	import { describeConfig, loadHostConfig, saveHostConfig } from '$lib/playout/host-config';

	interface Props {
		hostId: number;
		hostName: string;
		/** One line for the collapsed row: the screen, then the sound. */
		summary?: string;
	}
	let { hostId, hostName, summary = $bindable('') }: Props = $props();

	const host = query(() => loadHostConfig(hostId));
	$effect(() => {
		if (host.error) summary = "Couldn't read the player's settings";
		else if (!host.data) summary = 'Reading…';
		else {
			const d = describeConfig(host.data.config, host.data.hardware);
			summary = `${d.screen} · ${d.sound}`;
		}
	});
	let restartPending = $state(false);
	let restarting = $state(false);

	// What the player last accepted; a save runs only when the form differs from it.
	let saved: string | null = null;
	const saver = new AutoSave(async () => {
		if (!host.data) return;
		const draft = JSON.stringify(host.data.config);
		if (draft === saved) return;
		if (await saveHostConfig(hostId, host.data.config, false)) restartPending = true;
		saved = draft;
	});

	$effect(() => {
		if (!host.data) return;
		const draft = JSON.stringify(host.data.config);
		untrack(() => {
			if (saved === null) saved = draft;
			else if (draft !== saved) saver.schedule();
		});
	});
	onDestroy(() => {
		if (saver.waiting) void saver.flush();
	});

	async function restart() {
		restarting = true;
		await attempt(async () => {
			await saver.flush();
			await mutate(
				api.POST('/api/v2/playout/hosts/{host_id}/restart', {
					params: { path: { host_id: hostId } }
				})
			);
			restartPending = false;
			showToast(`${hostName} is restarting`, 'success');
		}, 'Could not restart the player');
		restarting = false;
	}
</script>

{#if host.loading}
	<Spinner size="sm" label="Reading the host's configuration…" />
{:else if host.error}
	<ErrorState compact error={host.error} retry={() => void host.load()} />
{:else if host.data}
	<div class="max-w-2xl space-y-4">
		{#if restartPending}
			<div
				class="flex flex-wrap items-center gap-3 border border-warning/40 bg-warning/10 px-3 py-2 text-sm"
				role="status"
			>
				<span class="mr-auto">Saved. It takes effect when {hostName} restarts.</span>
				<Button size="sm" variant="ghost" onclick={() => (restartPending = false)}>Later</Button>
				<Button size="sm" disabled={restarting} onclick={() => void restart()}>
					<RotateCw size={13} />
					{restarting ? 'Restarting…' : 'Restart now'}
				</Button>
			</div>
		{/if}
		<HostConfigFields
			bind:config={host.data.config}
			hardware={host.data.hardware}
			idPrefix="hc-{hostId}"
		/>
		<SaveState {saver} />
	</div>
{/if}
