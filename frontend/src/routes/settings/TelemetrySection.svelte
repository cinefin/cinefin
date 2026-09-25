<script lang="ts">
	import type { SettingsStore } from '$lib/settings/form.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Toggle from '$lib/components/ui/Toggle.svelte';
	import Field from './Field.svelte';
	import Disclosure from './Disclosure.svelte';

	interface Props {
		store: SettingsStore;
	}
	let { store }: Props = $props();
</script>

<div class="max-w-xl space-y-4">
	<Toggle
		label="Send anonymous usage telemetry"
		bind:checked={store.main.telemetry_enabled}
		dirty={store.isDirty('telemetry_enabled')}
		hint="Off by default. When on, Cinefin sends one anonymous heartbeat per day — version and configuration shape only, never your library, URLs, credentials or paths."
	/>

	{#if store.main.telemetry_enabled}
		<Field
			label="Aptabase host"
			forId="set-telemetry-host"
			hint="Base URL of the Aptabase instance that receives events. Defaults to the project's collector; point it at your own self-hosted Aptabase to keep everything in-house."
			dirty={store.isDirty('telemetry_host')}
			error={store.errorFor('telemetry_host')}
		>
			<Input
				id="set-telemetry-host"
				bind:value={store.main.telemetry_host}
				placeholder="https://telemetry.cinefin.dev"
			/>
		</Field>

		<Field
			label="App-Key"
			forId="set-telemetry-app-key"
			hint="The Aptabase application key. Nothing is sent while the host or key is blank."
			dirty={store.isDirty('telemetry_app_key')}
			error={store.errorFor('telemetry_app_key')}
		>
			<Input
				id="set-telemetry-app-key"
				bind:value={store.main.telemetry_app_key}
				placeholder="A-SH-0000000000"
			/>
		</Field>

		{#if store.telemetryInstallId}
			<Field label="Anonymous install id" hint="Read-only. The only per-install identifier sent.">
				<div class="font-mono text-sm text-muted select-all">{store.telemetryInstallId}</div>
			</Field>
		{:else}
			<p class="text-xs text-faint">An anonymous install id is generated when you save.</p>
		{/if}
	{/if}

	<Disclosure title="Exactly what a heartbeat contains">
		<ul class="list-disc space-y-1 pl-4 text-xs leading-relaxed text-faint">
			<li>A random install id (minted on opt-in) — the only per-install identifier.</li>
			<li>Cinefin version, OS name/version, and whether it runs in Docker or bare-metal.</li>
			<li>Python and Django versions.</li>
			<li>
				Which sync source <em>types</em> exist (plex / jellyfin) — never their URLs or tokens.
			</li>
			<li>The active playout transport (agent / local socket / none) and ratings system.</li>
			<li>Whether the auth gate is on, and which command-provider plugins are enabled.</li>
		</ul>
		<p class="mt-2 text-xs text-faint">
			No URLs, tokens, paths, IP addresses, movie or programme titles, or usage counts are ever
			sent. Sent at most once per day.
		</p>
	</Disclosure>
</div>
