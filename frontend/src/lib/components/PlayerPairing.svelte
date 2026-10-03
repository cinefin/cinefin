<script lang="ts">
	/**
	 * Pair a playout agent: list the players announcing themselves on the local
	 * network, and pair one with the 6-digit code on its screen. A player that
	 * is not listed (Cinefin in Docker cannot see mDNS) is added by address with
	 * the same code. Used by Settings → Playout and the setup wizard.
	 */
	import { onMount } from 'svelte';
	import { Link, RefreshCw } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import type { components } from '$lib/api/types.gen';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';

	type Found = components['schemas']['DiscoveredPlayerSchema'];
	type Host = components['schemas']['PlayoutHostSchema'];

	interface Props {
		/** Called with the new (or re-paired) host once pairing succeeds. */
		onpaired?: (host: Host) => void;
	}
	let { onpaired }: Props = $props();

	let found = $state<Found[] | null>(null);
	let scanning = $state(false);

	// The pairing form: a listed player, or an address typed in.
	let target = $state<{ base_url: string; name: string } | null>(null);
	let byAddress = $state(false);
	let address = $state('');
	let code = $state('');
	let error = $state('');
	let pairing = $state(false);

	async function scan() {
		scanning = true;
		try {
			found = await unwrap(api.GET('/api/v2/playout/discover'));
		} catch {
			found = [];
		} finally {
			scanning = false;
		}
	}

	onMount(() => void scan());

	function choose(player: Found) {
		target = { base_url: player.base_url, name: player.name };
		byAddress = false;
		code = '';
		error = '';
	}

	function chooseAddress() {
		target = null;
		byAddress = true;
		code = '';
		error = '';
	}

	function cancel() {
		target = null;
		byAddress = false;
		error = '';
	}

	async function pair(event: SubmitEvent) {
		event.preventDefault();
		const base_url = target?.base_url ?? address.trim();
		if (!base_url) {
			error = "Enter the player's address.";
			return;
		}
		if (code.replace(/\D/g, '').length !== 6) {
			error = "Enter the 6-digit code from the player's screen.";
			return;
		}
		pairing = true;
		error = '';
		try {
			const host = await unwrap(
				api.POST('/api/v2/playout/hosts/pair', { body: { base_url, code } })
			);
			cancel();
			address = '';
			code = '';
			onpaired?.(host);
			void scan();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Pairing failed';
		} finally {
			pairing = false;
		}
	}
</script>

<div class="space-y-3">
	<div class="flex items-center justify-between gap-3">
		<h3 class="text-sm font-medium">Players on your network</h3>
		<Button size="sm" disabled={scanning} onclick={() => void scan()}>
			<RefreshCw size={13} />
			{scanning ? 'Looking…' : 'Look again'}
		</Button>
	</div>

	{#if found === null}
		<Spinner size="sm" label="Looking for players…" />
	{:else if found.length === 0}
		<p class="text-sm text-muted">
			No players found. Start <code class="font-mono text-xs">cinefin-playout</code> on the machine at
			your screen, then look again. If Cinefin runs in Docker it cannot see players on the network: add
			the player by the address shown on its screen.
		</p>
	{:else}
		<ul class="space-y-2">
			{#each found as p (p.id)}
				<li
					class="flex flex-col gap-2 rounded-md border border-border p-2.5 sm:flex-row sm:items-center"
				>
					<div class="min-w-0 flex-1">
						<span class="text-sm font-medium">{p.name}</span>
						<code class="ml-2 font-mono text-xs break-all text-muted">{p.base_url}</code>
						{#if p.version}<span class="ml-2 font-mono text-[0.7rem] text-faint">{p.version}</span
							>{/if}
					</div>
					<div class="shrink-0">
						{#if p.host_id != null && p.paired}
							<StatusLamp colour="green" quiet>Added</StatusLamp>
						{:else if p.paired}
							<span class="text-xs text-faint">Paired with another Cinefin</span>
						{:else}
							<Button size="sm" variant="primary" onclick={() => choose(p)}>
								<Link size={13} /> Pair
							</Button>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
	{/if}

	{#if !target && !byAddress}
		<button
			type="button"
			class="text-xs text-muted underline hover:text-text"
			onclick={chooseAddress}
		>
			Add a player by address
		</button>
	{:else}
		<form class="space-y-3 border border-border bg-surface-2 p-3" onsubmit={pair}>
			{#if byAddress}
				<div>
					<label class="mb-1 block text-xs font-medium text-muted" for="pair-address">Address</label
					>
					<Input
						id="pair-address"
						bind:value={address}
						placeholder="10.0.0.5 or http://10.0.0.5:8089"
					/>
				</div>
			{/if}
			<div>
				<label class="mb-1 block text-xs font-medium text-muted" for="pair-code">
					Code shown on {target ? target.name : 'the player'}'s screen
				</label>
				<Input id="pair-code" bind:value={code} placeholder="123 456" class="max-w-40 font-mono" />
				<p class="mt-1 text-xs text-faint">
					The code changes every few minutes and after a wrong try, so read the one on screen now.
				</p>
			</div>
			{#if error}
				<p class="text-sm text-danger">{error}</p>
			{/if}
			<div class="flex gap-2">
				<Button type="submit" variant="primary" disabled={pairing}>
					{pairing ? 'Pairing…' : 'Pair'}
				</Button>
				<Button variant="ghost" onclick={cancel}>Cancel</Button>
			</div>
		</form>
	{/if}
</div>
