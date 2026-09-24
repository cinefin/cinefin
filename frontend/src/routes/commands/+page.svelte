<script lang="ts">
	import {
		Check,
		Copy,
		FilterX,
		FlaskConical,
		Pencil,
		Play,
		Plus,
		RefreshCw,
		Trash2,
		TriangleAlert,
		X,
		Zap
	} from '@lucide/svelte';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import { base } from '$app/paths';
	import { query } from '$lib/api/query.svelte';
	import { sortRows } from '$lib/filters';
	import { showToast as toast } from '$lib/toast.svelte';
	import SortHeader from '$lib/components/SortHeader.svelte';
	import type { components } from '$lib/api/types.gen';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
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
	const pickerProviders = $derived(providers.filter((p) => p.enabled || p.id === fProvider));

	// A command runs only if its provider is loaded AND enabled. A disabled one is
	// loaded but off (show a badge); a missing one is gone (unknown provider).
	const providerDisabled = (c: CommandItem) => providerById.get(c.provider)?.enabled === false;
	const canRun = (c: CommandItem) => providerById.get(c.provider)?.enabled === true;

	let searchInput = $state('');
	let search = $state('');
	let providerFilter = $state('all');

	let debounceTimer: ReturnType<typeof setTimeout> | undefined;
	function onSearchInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => (search = searchInput.trim()), 300);
	}

	function clearFilters() {
		searchInput = '';
		search = '';
		providerFilter = 'all';
	}

	const configSummary = (c: CommandItem): string => c.summary;

	function usageSummary(c: CommandItem): string {
		const u = c.used_in;
		if (!u) return '';
		const parts: string[] = [];
		if (u.programmes) parts.push(`${u.programmes} programme${u.programmes === 1 ? '' : 's'}`);
		if (u.templates) parts.push(`${u.templates} template${u.templates === 1 ? '' : 's'}`);
		if (u.credits) parts.push(`${u.credits} credits cue${u.credits === 1 ? '' : 's'}`);
		if (u.preshow) parts.push('pre-show');
		return parts.length ? `Used in ${parts.join(' · ')}` : '';
	}

	const allCommands = $derived(commandsQ.data?.commands ?? []);
	const filtered = $derived(
		allCommands.filter((c) => {
			if (search) {
				const q = search.toLowerCase();
				if (!c.name.toLowerCase().includes(q) && !configSummary(c).toLowerCase().includes(q))
					return false;
			}
			if (providerFilter !== 'all' && c.provider !== providerFilter) return false;
			return true;
		})
	);
	const filtersActive = $derived(Boolean(search || providerFilter !== 'all'));
	const counts = $derived.by(() => {
		const c: Record<string, number> = { all: allCommands.length };
		for (const cmd of allCommands) c[cmd.provider] = (c[cmd.provider] || 0) + 1;
		return c;
	});
	// Loaded providers, plus any id still on a command whose plugin is gone.
	const filterOptions = $derived.by(() => {
		const opts = providers.map((p) => ({ id: p.id, label: p.label }));
		for (const cmd of allCommands)
			if (!providerById.has(cmd.provider) && !opts.some((o) => o.id === cmd.provider))
				opts.push({ id: cmd.provider, label: cmd.provider_label });
		return opts;
	});
	const remoteCount = $derived(allCommands.filter((c) => c.show_on_remote).length);

	let sort = $state('');
	const sortCommands = (rows: CommandItem[]) =>
		sortRows(rows, sort, {
			name: (c) => c.name.toLowerCase(),
			provider: (c) => c.provider_label.toLowerCase(),
			target: (c) => configSummary(c).toLowerCase(),
			duration: (c) => c.duration ?? -1,
			remote: (c) => (c.show_on_remote ? 1 : 0)
		});

	const groups = $derived.by(() => {
		if (filtersActive)
			return [
				{
					provider: null as string | null,
					label: '',
					icon: undefined as string | undefined,
					commands: sortCommands(filtered)
				}
			];
		return filterOptions
			.map((p) => ({
				provider: p.id as string | null,
				label: p.label,
				icon: providerById.get(p.id)?.icon,
				commands: sortCommands(filtered.filter((c) => c.provider === p.id))
			}))
			.filter((g) => g.commands.length);
	});

	function refreshAll() {
		void commandsQ.load();
		void providersQ.load();
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

	async function toggleRemote(id: number) {
		try {
			await api.POST('/api/v2/commands/{command_id}/toggle_remote', {
				params: { path: { command_id: id } }
			});
			const c = commandsQ.data?.commands.find((x) => x.id === id);
			if (c) c.show_on_remote = !c.show_on_remote;
		} catch (e) {
			console.error('Error toggling remote:', e);
			toast('Failed to toggle remote display', 'error');
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
						body: payload
					})
				);
				toast('Command updated successfully', 'success');
			} else {
				await unwrap(
					api.POST('/api/v2/commands/create', { body: { ...payload, show_on_remote: false } })
				);
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

<div class="mb-1 flex flex-wrap items-center gap-2">
	<h1 class="mr-auto text-lg font-semibold">Commands</h1>
	<span class="font-mono text-xs text-muted">
		{counts.all} total · {remoteCount} on remote
	</span>
	<Button onclick={refreshAll} title="Refresh list"><RefreshCw size={14} /> Refresh</Button>
	<Button variant="primary" onclick={showCreateModal}><Plus size={14} /> Create command</Button>
</div>

<p class="mb-4 text-sm text-muted">
	Actions Cinefin can run - REST calls, Home Assistant services, or any provider plugin. Fire them
	from a programme rundown, on credits, pre-show, or as buttons on the
	<a href="{base}/remote" class="text-accent hover:underline">Remote</a>.
</p>

{#if providersQ.data?.failures.length}
	<div class="mb-4 border border-border bg-surface-1 p-3 text-sm" role="alert">
		<p class="mb-1 inline-flex items-center gap-1.5 text-warning">
			<TriangleAlert size={14} />
			{providersQ.data.failures.length === 1
				? 'A provider plugin failed to load'
				: `${providersQ.data.failures.length} provider plugins failed to load`}
		</p>
		{#each providersQ.data.failures as f (f.source)}
			<p class="font-mono text-xs text-muted">{f.source}: {f.error}</p>
		{/each}
	</div>
{/if}

<div class="mb-4 flex flex-wrap items-center gap-2">
	<Input
		type="search"
		placeholder="Search commands by name or config…"
		bind:value={searchInput}
		oninput={onSearchInput}
		class="w-full sm:w-72"
	/>
	<Select bind:value={providerFilter} class="flex-1 sm:flex-none">
		<option value="all">All ({counts.all})</option>
		{#each filterOptions as p (p.id)}
			<option value={p.id}>{p.label} ({counts[p.id] ?? 0})</option>
		{/each}
	</Select>
	{#if filtersActive}
		<Button variant="ghost" onclick={clearFilters} title="Clear search and filters">
			<FilterX size={14} /> Clear
		</Button>
	{/if}
</div>

{#if commandsQ.loading}
	<Spinner label="Loading commands…" />
{:else if commandsQ.error}
	<ErrorState error={commandsQ.error} retry={() => void commandsQ.load()} />
{:else if !filtered.length}
	{#if filtersActive}
		<EmptyState
			icon={FilterX}
			title="No matching commands"
			message="No commands match your current search or provider filter. Clear the filters to see them all."
		>
			{#snippet action()}
				<Button onclick={clearFilters}>Clear filters</Button>
			{/snippet}
		</EmptyState>
	{:else}
		<EmptyState
			icon={Zap}
			title="No commands yet"
			message="Create your first command to trigger REST calls or Home Assistant actions from your programmes and remote."
		>
			{#snippet action()}
				<Button variant="primary" onclick={showCreateModal}
					><Plus size={14} /> Create command</Button
				>
			{/snippet}
		</EmptyState>
	{/if}
{:else}
	<div class="overflow-x-auto border border-border">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-border bg-surface-2 text-left text-xs font-medium text-muted">
					<SortHeader {sort} col="name" label="Command name" onsort={(s) => (sort = s)} />
					<SortHeader {sort} col="provider" label="Provider" onsort={(s) => (sort = s)} />
					<SortHeader {sort} col="target" label="Target" onsort={(s) => (sort = s)} />
					<SortHeader
						{sort}
						col="duration"
						label="Duration"
						defaultDesc
						onsort={(s) => (sort = s)}
					/>
					<SortHeader {sort} col="remote" label="Remote" defaultDesc onsort={(s) => (sort = s)} />
					<th class="px-3 py-2 text-right">Actions</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#each groups as group (group.provider ?? 'filtered')}
					{#if group.provider}
						{@const GroupIcon = providerIcon(group.icon)}
						<tr class="bg-surface-2">
							<td colspan="6" class="px-3 py-1.5">
								<span class="flex items-center gap-2 text-xs font-medium text-muted">
									<GroupIcon size={13} />
									{group.label}
									<span class="font-mono text-faint">{group.commands.length}</span>
								</span>
							</td>
						</tr>
					{/if}
					{#each group.commands as c (c.id)}
						{@const summary = configSummary(c)}
						{@const usage = usageSummary(c)}
						{@const RowIcon = providerIcon(c.provider_icon)}
						<tr>
							<td class="px-3 py-2">
								<div class="font-medium">{c.name}</div>
								{#if usage}<div class="text-xs text-faint">{usage}</div>{/if}
							</td>
							<td class="px-3 py-2">
								<span class="flex flex-wrap items-center gap-1.5">
									<Badge variant="outline"><RowIcon size={11} /> {c.provider_label}</Badge>
									{#if providerDisabled(c)}
										<Badge variant="warning">Disabled</Badge>
									{/if}
								</span>
							</td>
							<td class="max-w-64 px-3 py-2">
								<span class="block truncate font-mono text-xs text-muted" title={summary}>
									{summary}
								</span>
							</td>
							<td class="px-3 py-2 font-mono text-xs">
								{c.duration ? `${c.duration}s` : '-'}
							</td>
							<td class="px-3 py-2">
								<button
									type="button"
									class="inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-xs
										{c.show_on_remote
										? 'border-accent-dim bg-accent/10 text-accent'
										: 'border-border-strong text-muted hover:text-text'}"
									aria-pressed={c.show_on_remote}
									title={c.show_on_remote
										? 'Shown as a button on the Remote - click to remove'
										: 'Add as a button on the Remote'}
									onclick={() => void toggleRemote(c.id)}
								>
									{#if c.show_on_remote}<Check size={11} />{:else}<Plus size={11} />{/if}
									Remote
								</button>
							</td>
							<td class="px-3 py-2">
								<span class="flex items-center justify-end gap-1">
									<Button
										size="sm"
										disabled={!canRun(c)}
										onclick={() => void runCommand(c.id)}
										title={providerDisabled(c)
											? `The ${c.provider_label} plugin is disabled — enable it in Settings → Plugins to run this`
											: !canRun(c)
												? `The ${c.provider_label} plugin is not loaded`
												: 'Run this command now'}
									>
										<Play size={12} /> Run
									</Button>
									<button
										type="button"
										class="rounded-sm p-1.5 text-muted hover:bg-surface-2 hover:text-text"
										title="Edit"
										aria-label="Edit"
										onclick={() => editCommand(c)}
									>
										<Pencil size={13} />
									</button>
									<button
										type="button"
										class="rounded-sm p-1.5 text-muted hover:bg-surface-2 hover:text-text"
										title="Duplicate"
										aria-label="Duplicate"
										onclick={() => duplicateCommand(c)}
									>
										<Copy size={13} />
									</button>
									<button
										type="button"
										class="rounded-sm p-1.5 text-muted hover:bg-surface-2 hover:text-danger"
										title="Delete"
										aria-label="Delete"
										onclick={() => askDelete(c)}
									>
										<Trash2 size={13} />
									</button>
								</span>
							</td>
						</tr>
					{/each}
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<Dialog bind:open={modalOpen} title={modalTitle}>
	<div class="space-y-4">
		<div>
			<label class="mb-1 block text-sm text-muted" for="cmd-name">Command name *</label>
			<Input id="cmd-name" bind:value={fName} />
			<p class="mt-1 text-xs text-faint">Enter a descriptive name for this command</p>
		</div>

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
