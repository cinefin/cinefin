<script lang="ts">
	import {
		Check,
		Copy,
		Ellipsis,
		FilterX,
		FlaskConical,
		Lock,
		Pencil,
		Play,
		Plus,
		Trash2,
		X,
		Zap
	} from '@lucide/svelte';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import { base } from '$app/paths';
	import { query } from '$lib/api/query.svelte';
	import { formatTime } from '$lib/format';
	import { showToast as toast } from '$lib/toast.svelte';
	import FilterBar from '$lib/components/FilterBar.svelte';
	import type { components } from '$lib/api/types.gen';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Banner from '$lib/components/ui/Banner.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Menu, { type MenuItem } from '$lib/components/ui/Menu.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import ProviderFields from '$lib/commands/ProviderFields.svelte';
	import {
		fromFormValues,
		providerIcon,
		toFormValues,
		type FormValues,
		type ProviderInfo,
		type Suggestion
	} from '$lib/commands/providers';

	type CommandResult = components['schemas']['CommandResultSchema'];
	type CommandItem = components['schemas']['CommandSchema'];

	const commandsQ = query(async () => await unwrap(api.GET('/api/v2/commands/list')));
	const providersQ = query(async () => await unwrap(api.GET('/api/v2/commands/providers')));
	const providers = $derived(providersQ.data?.providers ?? []);
	const providerById = $derived(new Map(providers.map((p) => [p.id, p])));
	// The picker offers enabled plugins only — plus the one the command being edited
	// already uses, so a command whose plugin was later disabled stays editable.
	// Built-in providers' commands come ready-made — none can be created for them.
	const pickerProviders = $derived(
		providers.filter((p) => !p.builtin && (p.enabled || p.id === fProvider))
	);

	// A command runs only if its provider is loaded AND enabled. A disabled one is
	// loaded but off (show a badge); a missing one is gone (unknown provider).
	const providerDisabled = (c: CommandItem) => providerById.get(c.provider)?.enabled === false;
	const canRun = (c: CommandItem) => providerById.get(c.provider)?.enabled === true;

	let search = $state('');
	let providerFilter = $state('');

	function clearFilters() {
		search = '';
		providerFilter = '';
	}

	function usageSummary(c: CommandItem): string {
		const u = c.used_in;
		if (!u) return '';
		const parts: string[] = [];
		if (u.programmes) parts.push(`${u.programmes} programme${u.programmes === 1 ? '' : 's'}`);
		if (u.templates) parts.push(`${u.templates} template${u.templates === 1 ? '' : 's'}`);
		if (u.credits) parts.push(`${u.credits} credits cue${u.credits === 1 ? '' : 's'}`);
		if (u.preshow) parts.push('a screening lead-in');
		return parts.length ? `Used in ${parts.join(' · ')}` : '';
	}

	const allCommands = $derived(commandsQ.data?.commands ?? []);
	const filtered = $derived(
		allCommands.filter((c) => {
			if (search) {
				const q = search.toLowerCase();
				if (!c.name.toLowerCase().includes(q) && !c.summary.toLowerCase().includes(q)) return false;
			}
			if (providerFilter && c.provider !== providerFilter) return false;
			return true;
		})
	);
	const filtersActive = $derived(Boolean(search || providerFilter));
	const counts = $derived.by(() => {
		const c: Record<string, number> = { all: allCommands.length };
		for (const cmd of allCommands) c[cmd.provider] = (c[cmd.provider] || 0) + 1;
		return c;
	});
	// Loaded providers, plus any id still on a command whose plugin is gone.
	const filterOptions = $derived.by(() => {
		// Built-in providers (the system actions) group first.
		const opts = [...providers]
			.sort((a, b) => Number(b.builtin) - Number(a.builtin))
			.map((p) => ({ id: p.id, label: p.label }));
		for (const cmd of allCommands)
			if (!providerById.has(cmd.provider) && !opts.some((o) => o.id === cmd.provider))
				opts.push({ id: cmd.provider, label: cmd.provider_label });
		return opts;
	});

	// One group per provider (built-in first); a search or filter shows one flat group.
	const groups = $derived.by(() => {
		if (filtersActive)
			return [{ id: 'results', label: 'Results', builtin: false, commands: filtered }];
		return filterOptions
			.map((p) => ({
				id: p.id,
				label: p.label,
				builtin: !!providerById.get(p.id)?.builtin,
				commands: filtered.filter((c) => c.provider === p.id)
			}))
			.filter((g) => g.commands.length);
	});

	function rowMenu(c: CommandItem): MenuItem[] {
		if (c.locked) return [{ label: 'Edit duration', icon: Pencil, onclick: () => editCommand(c) }];
		return [
			{ label: 'Edit', icon: Pencil, onclick: () => editCommand(c) },
			{ label: 'Duplicate', icon: Copy, onclick: () => duplicateCommand(c) },
			{ separator: true },
			{ label: 'Delete', icon: Trash2, danger: true, onclick: () => void askDelete(c) }
		];
	}

	let confirmDialog = $state<ConfirmDialog>();

	async function askDelete(c: CommandItem) {
		const usage = usageSummary(c);
		const warning = usage
			? ` It is still in use (${usage.replace(/^Used in /, '')}) - those blocks will simply stop firing.`
			: '';
		if (
			await confirmDialog!.confirm(`Delete command “${c.name}”?${warning}`, {
				confirmLabel: 'Delete'
			})
		) {
			void deleteCommand(c.id);
		}
	}

	async function deleteCommand(id: number) {
		try {
			await api.DELETE('/api/v2/commands/{command_id}/delete', {
				params: { path: { command_id: id } }
			});
			toast('Command deleted', 'success');
			void commandsQ.load();
		} catch (e) {
			toast(toApiError(e).message || 'Failed to delete command', 'error');
		}
	}

	async function runCommand(id: number) {
		try {
			const data = await unwrap(
				api.POST('/api/v2/commands/{command_id}/execute', { params: { path: { command_id: id } } })
			);
			const result = data.result;
			toast(
				result.ok ? `Command succeeded (${result.detail})` : `Command failed (${result.detail})`,
				result.ok ? 'success' : 'error'
			);
		} catch (e) {
			toast(toApiError(e).message || 'Failed to run command', 'error');
		}
	}

	let modalOpen = $state(false);
	let modalTitle = $state('Create command');
	let editing = $state<CommandItem | null>(null);
	let saveBusy = $state(false);
	let testBusy = $state(false);
	let testResult = $state<CommandResult | null>(null);

	let fName = $state('');
	let fProvider = $state('rest');
	let fDuration = $state('');
	let fValues = $state<FormValues>({});
	const fProviderInfo = $derived<ProviderInfo | undefined>(providerById.get(fProvider));

	function resetForm() {
		fName = '';
		// Default to an enabled provider — a disabled one can't run.
		const enabled = providers.filter((p) => p.enabled);
		fProvider = enabled.find((p) => p.id === 'rest')?.id ?? enabled[0]?.id ?? 'rest';
		fDuration = '';
		fValues = toFormValues(providerById.get(fProvider)?.fields ?? [], {});
		testResult = null;
	}

	// Editing a built-in command changes only its duration.
	const locked = $derived(editing?.locked ?? false);

	function fillForm(c: CommandItem, nameSuffix = '') {
		fName = (c.name || '') + nameSuffix;
		fProvider = c.provider;
		fDuration = c.duration ? String(c.duration) : '';
		fValues = toFormValues(providerById.get(c.provider)?.fields ?? [], c.config ?? {});
		testResult = null;
	}

	function switchProvider(id: string) {
		fProvider = id;
		fValues = toFormValues(providerById.get(id)?.fields ?? [], {});
		suggestions = {};
		suggestState = 'idle';
		testResult = null;
	}

	function showCreateModal() {
		editing = null;
		modalTitle = 'Create command';
		resetForm();
		modalOpen = true;
	}

	function editCommand(c: CommandItem) {
		editing = c;
		modalTitle = 'Edit command';
		fillForm(c);
		modalOpen = true;
	}

	function duplicateCommand(c: CommandItem) {
		editing = null;
		modalTitle = 'Duplicate command';
		fillForm(c, ' (Copy)');
		modalOpen = true;
	}

	function collectForm(): {
		name: string;
		provider: string;
		config: Record<string, unknown>;
		duration: number;
	} | null {
		if (!fProviderInfo) {
			toast(`The "${fProvider}" provider is not loaded - pick another one`, 'error');
			return null;
		}
		const result = fromFormValues(fProviderInfo.fields, fValues);
		if ('error' in result) {
			toast(result.error, 'error');
			return null;
		}
		return {
			name: fName.trim(),
			provider: fProvider,
			config: result.config,
			duration: parseFloat(fDuration) || 0
		};
	}

	async function saveCommand() {
		const payload = collectForm();
		if (!payload) return;
		if (!payload.name || payload.name.length < 2) {
			toast('Command name is required (minimum 2 characters)', 'error');
			return;
		}
		saveBusy = true;
		try {
			if (editing) {
				await unwrap(
					api.PUT('/api/v2/commands/{command_id}/update', {
						params: { path: { command_id: editing.id } },
						body: locked ? { duration: payload.duration } : payload
					})
				);
				toast('Command updated successfully', 'success');
			} else {
				await unwrap(api.POST('/api/v2/commands/create', { body: payload }));
				toast('Command created successfully', 'success');
			}
			modalOpen = false;
			editing = null;
			void commandsQ.load();
		} catch (e) {
			toast(toApiError(e).message || 'Failed to save command', 'error');
		} finally {
			saveBusy = false;
		}
	}

	async function testCurrentForm() {
		const payload = collectForm();
		if (!payload) return;
		testBusy = true;
		try {
			const data = await unwrap(
				api.POST('/api/v2/commands/test', {
					body: { provider: payload.provider, config: payload.config }
				})
			);
			testResult = data.result;
		} catch (e) {
			toast(toApiError(e).message || 'Test failed', 'error');
		} finally {
			testBusy = false;
		}
	}

	// Autocomplete values from the provider (e.g. Home Assistant's services and entities).
	let suggestions = $state<Record<string, Suggestion[]>>({});
	let suggestState = $state<'idle' | 'loading' | 'ok' | 'error'>('idle');
	let suggestMessage = $state('');
	const wantsSuggestions = $derived(Boolean(fProviderInfo?.has_suggestions));

	$effect(() => {
		if (modalOpen && wantsSuggestions && suggestState === 'idle') void loadSuggestions(fProvider);
	});

	async function loadSuggestions(providerId: string) {
		suggestState = 'loading';
		try {
			const data = await unwrap(
				api.GET('/api/v2/commands/providers/{provider_id}/suggestions', {
					params: { path: { provider_id: providerId } }
				})
			);
			if (providerId !== fProvider) return;
			suggestions = data.suggestions;
			suggestMessage = data.message;
			suggestState = data.ok ? 'ok' : 'error';
		} catch (e) {
			suggestState = 'error';
			suggestMessage = toApiError(e).message || 'Suggestions are not available';
		}
	}
	const suggestionCount = $derived(Object.values(suggestions).reduce((n, l) => n + l.length, 0));
</script>

<svelte:head><title>Commands - Cinefin</title></svelte:head>

<div class="mb-1 flex items-center gap-2">
	<h1 class="mr-auto text-lg font-semibold">Commands</h1>
	<Button variant="primary" onclick={showCreateModal}><Plus size={14} /> Create command</Button>
</div>
<p class="mb-4 text-sm text-muted">
	Actions Cinefin can run — from a programme rundown, on credits, in a screening's lead-in, or as
	buttons on the dashboard and the <a href="{base}/remote" class="text-accent hover:underline"
		>Remote</a
	>.
</p>

{#if providersQ.data?.failures.length}
	<Banner
		severity="warning"
		align="start"
		class="mb-4"
		title={providersQ.data.failures.length === 1
			? 'A provider plugin failed to load.'
			: `${providersQ.data.failures.length} provider plugins failed to load.`}
	>
		{#each providersQ.data.failures as f (f.source)}
			<p class="font-mono text-xs">{f.source}: {f.error}</p>
		{/each}
	</Banner>
{/if}

<FilterBar
	search={{ value: search, placeholder: 'Search commands…', onchange: (v) => (search = v) }}
	filters={[
		{
			id: 'provider',
			label: 'Provider',
			allLabel: 'All providers',
			value: providerFilter,
			options: filterOptions.map((p) => ({ value: p.id, label: p.label })),
			onchange: (v) => (providerFilter = v)
		}
	]}
	count={filtersActive ? `${filtered.length} of ${counts.all}` : `${counts.all} total`}
	onreset={clearFilters}
/>

{#if commandsQ.loading}
	<Spinner label="Loading commands…" />
{:else if commandsQ.error}
	<ErrorState error={commandsQ.error} retry={() => void commandsQ.load()} />
{:else if !filtered.length}
	<EmptyState
		icon={filtersActive ? FilterX : Zap}
		title={filtersActive ? 'No matching commands' : 'No commands yet'}
		message={filtersActive
			? 'Nothing matches the search or provider filter.'
			: 'Create one to fire REST calls, Home Assistant actions or any plugin from your programmes.'}
	>
		{#snippet action()}
			{#if filtersActive}
				<Button onclick={clearFilters}>Clear filters</Button>
			{:else}
				<Button variant="primary" onclick={showCreateModal}
					><Plus size={14} /> Create command</Button
				>
			{/if}
		{/snippet}
	</EmptyState>
{:else}
	<div class="space-y-3">
		{#each groups as group (group.id)}
			<Card title={group.label}>
				{#snippet actions()}
					{#if group.builtin}
						<span class="flex items-center gap-1 text-xs text-faint"
							><Lock size={11} /> Built in</span
						>
					{/if}
					<span class="font-mono text-xs text-faint">{group.commands.length}</span>
				{/snippet}
				<ul class="-mx-4 -my-2 divide-y divide-border">
					{#each group.commands as c (c.id)}
						{@const Icon = providerIcon(c.provider_icon)}
						{@const detail = [c.summary !== c.name ? c.summary : '', usageSummary(c)]
							.filter(Boolean)
							.join(' · ')}
						<li class="flex items-center gap-3 px-4 py-2">
							<Icon size={14} class="shrink-0 text-muted" />
							<div class="min-w-0 flex-1">
								<p class="truncate text-sm">{c.name}</p>
								{#if detail}
									<p class="truncate font-mono text-xs text-faint" title={detail}>{detail}</p>
								{/if}
							</div>
							{#if providerDisabled(c)}
								<Badge variant="warning">Disabled</Badge>
							{/if}
							{#if c.duration}
								<span class="shrink-0 font-mono text-xs text-muted" title="Duration"
									>{formatTime(c.duration)}</span
								>
							{/if}
							<Button
								size="sm"
								disabled={!canRun(c)}
								onclick={() => void runCommand(c.id)}
								title={providerDisabled(c)
									? `The ${c.provider_label} plugin is disabled — enable it in Settings → Plugins`
									: !canRun(c)
										? `The ${c.provider_label} plugin is not loaded`
										: 'Run this command now'}
							>
								<Play size={12} /> Run
							</Button>
							<Menu
								items={rowMenu(c)}
								icon={Ellipsis}
								variant="ghost"
								size="sm"
								align="right"
								ariaLabel="More actions for {c.name}"
							/>
						</li>
					{/each}
				</ul>
			</Card>
		{/each}
	</div>
{/if}

<Dialog bind:open={modalOpen} title={modalTitle}>
	<div class="space-y-4">
		<div>
			<label class="mb-1 block text-sm text-muted" for="cmd-name">Command name *</label>
			<Input id="cmd-name" bind:value={fName} disabled={locked} />
			<p class="mt-1 text-xs text-faint">
				{locked
					? 'A built-in command: it can be used anywhere, and only its duration can change.'
					: 'Enter a descriptive name for this command'}
			</p>
		</div>

		{#if !locked}
			<div>
				<label class="mb-1 block text-sm text-muted" for="cmd-provider">Provider *</label>
				<Select
					id="cmd-provider"
					value={fProvider}
					onchange={(e) => switchProvider((e.currentTarget as HTMLSelectElement).value)}
					class="w-full"
				>
					{#each pickerProviders as p (p.id)}
						<option value={p.id}>{p.label}</option>
					{/each}
					{#if !fProviderInfo}
						<option value={fProvider}>{fProvider} (not loaded)</option>
					{/if}
				</Select>
				{#if fProviderInfo?.description}
					<p class="mt-1 text-xs text-faint">{fProviderInfo.description}</p>
				{:else if !fProviderInfo}
					<p class="mt-1 text-xs text-warning">
						This command's provider plugin is not loaded, so its settings can't be edited.
					</p>
				{/if}
			</div>

			{#if wantsSuggestions && suggestState !== 'idle'}
				<p class="text-xs text-muted">
					{#if suggestState === 'loading'}
						Loading suggestions from {fProviderInfo?.label}…
					{:else if suggestState === 'ok'}
						<span class="inline-flex items-center gap-1 text-success">
							<Check size={12} /> Connected
						</span>
						- {suggestionCount} suggestions available in the fields below.
					{:else}
						<span class="inline-flex items-center gap-1 text-warning">
							<X size={12} />
							{suggestMessage}
						</span>
						- fields accept free text.
					{/if}
				</p>
			{/if}

			{#if fProviderInfo}
				<ProviderFields
					fields={fProviderInfo.fields}
					bind:values={fValues}
					{suggestions}
					idPrefix="cmd-{fProvider}"
				/>
			{/if}
		{/if}

		<div>
			<label class="mb-1 block text-sm text-muted" for="cmd-duration">Duration (seconds)</label>
			<Input id="cmd-duration" type="number" bind:value={fDuration} />
			<p class="mt-1 text-xs text-faint">
				Roughly how long the action takes. Only used when a rundown block has "hold black screen"
				enabled - black is then held for exactly this long before playback continues. Instant cues
				ignore it.
			</p>
		</div>

		{#if testResult}
			<div class="rounded-md border border-border bg-surface-2 p-3">
				<p
					class="mb-1.5 inline-flex items-center gap-1.5 text-sm {testResult.ok
						? 'text-success'
						: 'text-danger'}"
				>
					{#if testResult.ok}<Check size={14} />{:else}<X size={14} />{/if}
					{testResult.detail}
				</p>
				<pre
					class="max-h-40 overflow-auto font-mono text-xs whitespace-pre-wrap text-muted">{testResult.output ||
						'(no output)'}</pre>
			</div>
		{/if}
	</div>
	{#snippet footer()}
		<Button disabled={testBusy} onclick={() => void testCurrentForm()}>
			<FlaskConical size={14} />
			{testBusy ? 'Testing…' : 'Test'}
		</Button>
		<Button onclick={() => (modalOpen = false)}>Cancel</Button>
		<Button variant="primary" disabled={saveBusy} onclick={() => void saveCommand()}>
			{saveBusy ? 'Saving…' : 'Save command'}
		</Button>
	{/snippet}
</Dialog>

<ConfirmDialog bind:this={confirmDialog} />
