<script lang="ts">
	// Every loaded command-provider plugin, any that failed to load, and the provider-wide settings
	// of those that declare some. A plugin's settings save themselves once they are complete.
	import { onDestroy } from 'svelte';
	import { Plug, Power, Search, TriangleAlert } from '@lucide/svelte';
	import { base } from '$app/paths';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { query } from '$lib/api/query.svelte';
	import type { components } from '$lib/api/types.gen';
	import ProviderFields from '$lib/commands/ProviderFields.svelte';
	import {
		fromFormValues,
		providerIcon,
		toFormValues,
		type FormValues,
		type ProviderInfo
	} from '$lib/commands/providers';
	import { attempt, errorText, runCheck } from '$lib/settings/form.svelte';
	import type { CheckState } from '$lib/settings/types';
	import { showToast } from '$lib/toast.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import CheckResult from './CheckResult.svelte';
	import { AutoSave } from '$lib/settings/autosave.svelte';
	import SaveState from '$lib/settings/SaveState.svelte';

	type Candidate = components['schemas']['DiscoveredSchema'];

	const pluginsQ = query(async () => {
		const data = await unwrap(api.GET('/api/v2/commands/providers'));
		const configurable = data.providers.filter((p) => p.settings.length);
		const saved = await Promise.all(
			configurable.map((p) =>
				unwrap(
					api.GET('/api/v2/commands/providers/{provider_id}/settings', {
						params: { path: { provider_id: p.id } }
					})
				)
			)
		);
		values = Object.fromEntries(
			configurable.map((p, i) => [p.id, toFormValues(p.settings, saved[i].values)])
		);
		return data;
	});

	let values = $state<Record<string, FormValues>>({});
	let busy = $state<string | null>(null);
	let checks = $state<Record<string, CheckState>>({});
	let candidates = $state<Record<string, Candidate[] | null>>({});

	// One saver per plugin; the values last saved, so only a real change saves.
	const savers: Record<string, AutoSave> = {};
	const savedValues: Record<string, string> = {};
	let incomplete = $state<Record<string, string | null>>({});

	function saverFor(p: ProviderInfo): AutoSave {
		return (savers[p.id] ??= new AutoSave(async () => {
			const draft = JSON.stringify(values[p.id] ?? {});
			if (draft === savedValues[p.id]) return;
			const result = fromFormValues(p.settings, values[p.id] ?? {});
			if ('error' in result) return;
			await unwrap(
				api.PUT('/api/v2/commands/providers/{provider_id}/settings', {
					params: { path: { provider_id: p.id } },
					body: { values: result.config }
				})
			);
			savedValues[p.id] = draft;
		}, 800));
	}

	// A change saves itself; one with a required field still empty waits and says why.
	$effect(() => {
		for (const p of pluginsQ.data?.providers ?? []) {
			const v = values[p.id];
			if (!v) continue;
			const draft = JSON.stringify(v);
			if (savedValues[p.id] === undefined) {
				savedValues[p.id] = draft;
				continue;
			}
			if (draft === savedValues[p.id]) continue;
			const result = fromFormValues(p.settings, v);
			incomplete[p.id] = 'error' in result ? result.error : null;
			if (!('error' in result)) saverFor(p).schedule();
		}
	});
	onDestroy(() => {
		for (const s of Object.values(savers)) if (s.waiting) void s.flush();
	});

	async function test(p: ProviderInfo) {
		// Test what's in the form, saved or not; required-field gaps are the plugin's to report.
		const config = fromFormValues(
			p.settings.map((f) => ({ ...f, required: false })),
			values[p.id] ?? {}
		);
		if ('error' in config) {
			checks[p.id] = { state: 'error', message: config.error };
			return;
		}
		busy = `${p.id}:test`;
		checks[p.id] = { state: 'pending', message: 'Testing…' };
		checks[p.id] = await runCheck(() =>
			unwrap(
				api.POST('/api/v2/commands/providers/{provider_id}/settings/test', {
					params: { path: { provider_id: p.id } },
					body: { values: config.config }
				})
			)
		);
		busy = null;
	}

	async function discover(p: ProviderInfo) {
		busy = `${p.id}:discover`;
		candidates[p.id] = null;
		checks[p.id] = { state: 'pending', message: 'Searching the network…' };
		try {
			const res = await unwrap(
				api.GET('/api/v2/commands/providers/{provider_id}/discover', {
					params: { path: { provider_id: p.id } }
				})
			);
			if (!res.candidates.length) {
				checks[p.id] = { state: 'warn', message: 'Nothing found - enter the settings manually.' };
			} else if (res.candidates.length === 1) {
				apply(p, res.candidates[0]);
			} else {
				checks[p.id] = null;
				candidates[p.id] = res.candidates;
			}
		} catch (e) {
			checks[p.id] = { state: 'error', message: errorText(e, 'Discovery failed') };
		} finally {
			busy = null;
		}
	}

	function apply(p: ProviderInfo, c: Candidate) {
		const current = values[p.id] ?? {};
		const found = toFormValues(p.settings, c.values);
		for (const key of Object.keys(c.values)) current[key] = found[key] ?? '';
		values[p.id] = current;
		candidates[p.id] = null;
		checks[p.id] = { state: 'ok', message: `Found ${c.label || 'it'} - remember to save` };
	}

	async function setEnabled(p: ProviderInfo, enabled: boolean) {
		busy = `${p.id}:enabled`;
		await attempt(async () => {
			await mutate(
				api.POST('/api/v2/commands/providers/{provider_id}/enabled', {
					params: { path: { provider_id: p.id } },
					body: { enabled }
				})
			);
			await pluginsQ.refresh();
			showToast(`${p.label} ${enabled ? 'enabled' : 'disabled'}`, 'success');
		}, 'Failed to update the plugin');
		busy = null;
	}
</script>

{#if pluginsQ.loading}
	<Spinner label="Loading plugins…" />
{:else if pluginsQ.error}
	<ErrorState error={pluginsQ.error} retry={() => void pluginsQ.load()} />
{:else if pluginsQ.data}
	{#if pluginsQ.data.failures.length}
		<div class="mb-4 border border-border bg-surface-1 p-3 text-sm" role="alert">
			<p class="mb-1 inline-flex items-center gap-1.5 text-warning">
				<TriangleAlert size={14} />
				{pluginsQ.data.failures.length === 1
					? 'A plugin failed to load'
					: `${pluginsQ.data.failures.length} plugins failed to load`}
			</p>
			{#each pluginsQ.data.failures as f (f.source)}
				<p class="font-mono text-xs text-muted">{f.source}: {f.error}</p>
			{/each}
		</div>
	{/if}

	{@const active = pluginsQ.data.providers.filter((p) => p.enabled)}
	{@const disabled = pluginsQ.data.providers.filter((p) => !p.enabled)}

	<div class="space-y-4">
		{#each active as p (p.id)}
			{@const Icon = providerIcon(p.icon)}
			<Card title={p.label}>
				{#snippet actions()}
					<span class="font-mono text-xs text-faint">{p.source}</span>
					<Button
						size="sm"
						disabled={busy !== null}
						title="Disable this plugin — its commands stop running and it leaves the command picker"
						onclick={() => void setEnabled(p, false)}
					>
						<Power size={13} /> Disable
					</Button>
				{/snippet}
				<div class="max-w-xl space-y-4">
					{#if p.description}
						<p class="flex items-center gap-2 text-sm text-muted">
							<Icon size={14} class="shrink-0" />
							{p.description}
						</p>
					{/if}
					{#if p.settings.length && values[p.id]}
						<ProviderFields
							fields={p.settings}
							bind:values={values[p.id]}
							idPrefix="plugin-{p.id}"
						/>
						{#if candidates[p.id]}
							<div class="flex flex-wrap gap-2">
								{#each candidates[p.id] ?? [] as c, i (i)}
									<Button size="sm" onclick={() => apply(p, c)}>{c.label}</Button>
								{/each}
							</div>
						{/if}
						<CheckResult result={checks[p.id] ?? null} />
						{#if incomplete[p.id]}
							<p class="text-xs text-warning">Not saved yet: {incomplete[p.id]}</p>
						{:else}
							<SaveState saver={saverFor(p)} />
						{/if}
						<div class="flex flex-wrap items-center gap-2">
							{#if p.has_settings_test}
								<Button disabled={busy !== null} onclick={() => void test(p)}>
									<Plug size={14} /> Test connection
								</Button>
							{/if}
							{#if p.has_discover}
								<Button
									disabled={busy !== null}
									title="Search the local network"
									onclick={() => void discover(p)}
								>
									<Search size={14} /> Discover
								</Button>
							{/if}
						</div>
					{:else}
						<p class="text-xs text-faint">No settings - configure it per command.</p>
					{/if}
				</div>
			</Card>
		{/each}
	</div>

	{#if disabled.length}
		<div class="mt-4 border border-border bg-surface-1">
			<p class="border-b border-border px-3.5 py-2 text-[0.78125rem] font-medium text-muted">
				Disabled
			</p>
			<div class="divide-y divide-border">
				{#each disabled as p (p.id)}
					{@const Icon = providerIcon(p.icon)}
					<div class="flex items-center gap-2 px-3.5 py-2 text-sm">
						<Icon size={14} class="shrink-0 text-faint" />
						<span class="text-muted">{p.label}</span>
						<span class="font-mono text-xs text-faint">{p.source}</span>
						<Button
							size="sm"
							class="ml-auto"
							disabled={busy !== null}
							onclick={() => void setEnabled(p, true)}
						>
							<Power size={13} /> Enable
						</Button>
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<p class="mt-4 text-xs text-faint">
		Plugins add the kinds of action a
		<a href="{base}/commands" class="text-accent hover:underline">command</a>
		can run. They ship with Cinefin in <span class="font-mono">contrib/plugins/</span> - new ones are
		added by pull request (see docs/PLUGINS.md).
	</p>
{/if}
