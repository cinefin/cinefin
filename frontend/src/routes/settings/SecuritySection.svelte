<script lang="ts">
	import { fade } from 'svelte/transition';
	import { Check, Copy, KeyRound, Plus, Trash2, TriangleAlert } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { query } from '$lib/api/query.svelte';
	import { showToast } from '$lib/toast.svelte';
	import { formatDateTime } from '$lib/settings/form.svelte';
	import type { CheckState } from '$lib/settings/types';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import CheckResult from './CheckResult.svelte';
	import Field from './Field.svelte';
	import Toggle from '$lib/components/ui/Toggle.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	interface Props {
		confirm: ConfirmDialog['confirm'];
	}
	let { confirm }: Props = $props();

	const TABS = [
		{ id: 'account', label: 'Account' },
		{ id: 'keys', label: 'API keys' }
	];
	let tab = $state('account');

	const security = query(() => unwrap(api.GET('/api/v2/security/')));

	let username = $state('admin');
	let password = $state('');
	let passwordConfirm = $state('');
	let passwordResult = $state<CheckState>(null);
	let savingPassword = $state(false);

	$effect(() => {
		if (security.data?.username) username = security.data.username;
	});

	async function savePassword() {
		passwordResult = null;
		if (!password) {
			passwordResult = { state: 'error', message: 'Enter a password' };
			return;
		}
		if (password !== passwordConfirm) {
			passwordResult = { state: 'error', message: 'Passwords do not match' };
			return;
		}
		savingPassword = true;
		try {
			const state = await unwrap(
				api.POST('/api/v2/security/set-password', {
					body: {
						password,
						confirm: passwordConfirm,
						username: username.trim() || null,
						enable_auth: false
					}
				})
			);
			security.data = state;
			password = '';
			passwordConfirm = '';
			passwordResult = { state: 'ok', message: 'Password saved' };
			showToast('Password saved', 'success');
		} catch (e) {
			passwordResult = {
				state: 'error',
				message: e instanceof Error ? e.message : 'Failed to save password'
			};
		} finally {
			savingPassword = false;
		}
	}

	let authEnabled = $state(false);
	let kioskPublic = $state(false);
	$effect(() => {
		if (security.data) {
			authEnabled = security.data.auth_enabled;
			kioskPublic = security.data.kiosk_public;
		}
	});

	async function toggleAuth() {
		const enable = authEnabled;
		if (enable && security.data && !security.data.has_account) {
			authEnabled = false;
			showToast('Set a password first, then enable authentication', 'error');
			return;
		}
		try {
			const state = await unwrap(
				api.POST('/api/v2/security/toggle', { body: { auth_enabled: enable } })
			);
			security.data = state;
			showToast(
				enable
					? 'Authentication enabled - you may need to sign in on your next action'
					: 'Authentication disabled',
				'success'
			);
		} catch (e) {
			authEnabled = !enable;
			showToast(e instanceof Error ? e.message : 'Failed to change authentication', 'error');
		}
	}

	async function toggleKiosk() {
		const value = kioskPublic;
		try {
			const state = await unwrap(
				api.POST('/api/v2/security/toggle', { body: { kiosk_public: value } })
			);
			security.data = state;
			showToast(
				value ? 'Kiosk display is public' : 'Kiosk display now requires a login',
				'success'
			);
		} catch (e) {
			kioskPublic = !value;
			showToast(e instanceof Error ? e.message : 'Failed to update kiosk setting', 'error');
		}
	}

	const apiKeys = query(() => unwrap(api.GET('/api/v2/security/api-keys')));

	let newKeyName = $state('');
	let creatingKey = $state(false);
	let createdKeyOpen = $state(false);
	let createdKey = $state('');

	async function createKey() {
		const name = newKeyName.trim();
		if (!name) {
			showToast('Give the key a label first', 'error');
			return;
		}
		creatingKey = true;
		try {
			const created = await unwrap(api.POST('/api/v2/security/api-keys', { body: { name } }));
			newKeyName = '';
			createdKey = created.key;
			createdKeyOpen = true;
			void apiKeys.refresh();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to create API key', 'error');
		} finally {
			creatingKey = false;
		}
	}

	async function revokeKey(id: number, name: string) {
		if (
			!(await confirm(`Revoke "${name}"? Any client using it stops working immediately.`, {
				confirmLabel: 'Revoke'
			}))
		) {
			return;
		}
		try {
			await mutate(
				api.DELETE('/api/v2/security/api-keys/{key_id}', {
					params: { path: { key_id: id } }
				})
			);
			showToast('API key revoked', 'success');
			void apiKeys.refresh();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to revoke API key', 'error');
		}
	}

	function copyKey() {
		navigator.clipboard?.writeText(createdKey).then(
			() => showToast('Key copied to clipboard', 'success'),
			() => showToast('Could not copy - select and copy manually', 'error')
		);
	}

	const usedAt = (iso: string | null | undefined) => (iso ? formatDateTime(iso) : 'never');
</script>

<div class="space-y-4">
	{#if security.data && !security.data.auth_active}
		<div
			class="flex items-start gap-3 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm"
			role="alert"
		>
			<TriangleAlert size={18} class="mt-0.5 shrink-0 text-warning" />
			<div>
				<strong>Authentication is off.</strong>
				Anyone who can reach this server can control the theater, run commands, and restore backups. Set
				a password below and turn authentication on.
			</div>
		</div>
	{/if}

	<Tabs
		tabs={TABS}
		value={tab}
		label="Security settings"
		onselect={(id) => (tab = id)}
		panelId={(id) => `st-${id}`}
	/>

	{#if tab === 'account'}
		<div
			role="tabpanel"
			id="st-account"
			aria-labelledby="tab-account"
			class="max-w-xl"
			in:fade={{ duration: 120 }}
		>
			{#if security.loading}
				<Spinner label="Loading security state…" />
			{:else if security.error}
				<ErrorState compact error={security.error} retry={() => void security.load()} />
			{:else}
				<div class="space-y-4">
					<Field
						label="Username"
						forId="set-auth-username"
						hint={security.data?.has_account
							? 'The single account used to sign in. Saving a new password updates it.'
							: 'No account yet - set a password to create one.'}
					>
						<Input
							id="set-auth-username"
							bind:value={username}
							placeholder="admin"
							class="max-w-xs"
						/>
					</Field>
					<div class="grid gap-4 sm:grid-cols-2">
						<Field label="New password" forId="set-auth-password">
							<Input id="set-auth-password" type="password" bind:value={password} />
						</Field>
						<Field label="Confirm password" forId="set-auth-password-confirm">
							<Input id="set-auth-password-confirm" type="password" bind:value={passwordConfirm} />
						</Field>
					</div>
					<div class="space-y-2">
						<Button variant="primary" disabled={savingPassword} onclick={savePassword}>
							<Check size={14} /> Save password
						</Button>
						<CheckResult result={passwordResult} />
						<p class="text-xs text-faint">
							Any password you like - this is a single-user home system.
						</p>
					</div>
				</div>
			{/if}

			<div class="mt-6 border-t border-border pt-5">
				<h3 class="mb-3 text-[0.78125rem] font-medium text-muted">Enforcement</h3>
				<div class="space-y-2.5">
					<Toggle
						label="Require authentication"
						hint="When on, every page redirects to a login screen and the API returns 401 until you sign in. You must set a password first. Locked out? Run manage.py disable_auth on the server."
						bind:checked={authEnabled}
						disabled={!security.data}
						onchange={toggleAuth}
					/>
					<Toggle
						label="Keep the kiosk display public"
						hint="A wall-mounted kiosk screen can't log in. When on, the kiosk display (/app/kiosk) and the read-only data it polls stay reachable without a session - nothing that can change state is exposed. Turn off if the kiosk screen isn't physically trusted."
						bind:checked={kioskPublic}
						disabled={!security.data}
						onchange={toggleKiosk}
					/>
				</div>
				<p class="mt-3 text-xs text-faint">
					These apply immediately when toggled (not part of "Save changes"). If you lose access, run
					<code class="font-mono">manage.py set_admin_password</code> or
					<code class="font-mono">manage.py disable_auth</code> on the server.
				</p>
			</div>
		</div>
	{:else if tab === 'keys'}
		<div
			role="tabpanel"
			id="st-keys"
			aria-labelledby="tab-keys"
			class="max-w-2xl"
			in:fade={{ duration: 120 }}
		>
			<p class="mb-3 text-xs text-faint">
				Bearer tokens for programmatic access to the Cinefin API - send
				<code class="font-mono">Authorization: Bearer &lt;key&gt;</code>. A key has the same reach
				as a signed-in session and only applies while authentication is on. The full key is shown
				once, when created; store it then. Revoking a key stops it working immediately.
			</p>

			{#if apiKeys.loading}
				<Spinner size="sm" />
			{:else if apiKeys.error}
				<ErrorState compact error={apiKeys.error} retry={() => void apiKeys.load()} />
			{:else if !apiKeys.data?.length}
				<EmptyState compact icon={KeyRound} title="No API keys yet" />
			{:else}
				<div class="divide-y divide-border rounded-md border border-border">
					{#each apiKeys.data as k (k.id)}
						<div class="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
							<span class="font-medium">{k.name}</span>
							<code class="font-mono text-xs text-muted">{k.prefix}…</code>
							<span class="min-w-0 flex-1 truncate text-right text-xs text-faint">
								created {usedAt(k.created_at)} · last used {usedAt(k.last_used_at)}
							</span>
							<Button size="sm" variant="danger" onclick={() => revokeKey(k.id, k.name)}>
								<Trash2 size={13} /> Revoke
							</Button>
						</div>
					{/each}
				</div>
			{/if}

			<div class="mt-4">
				<Field label="New key label" forId="apikey-name">
					<div class="flex max-w-md gap-2">
						<Input id="apikey-name" bind:value={newKeyName} placeholder="e.g. Home Assistant" />
						<Button variant="primary" disabled={creatingKey} onclick={createKey}>
							<Plus size={14} /> Create key
						</Button>
					</div>
				</Field>
			</div>
		</div>
	{/if}
</div>

<Dialog bind:open={createdKeyOpen} title="API key created">
	<p class="mb-3 text-xs text-faint">
		Copy this now - it will not be shown again. If you lose it, revoke the key and create a new one.
	</p>
	<div class="flex items-center gap-2">
		<code
			class="min-w-0 flex-1 rounded-md border border-border bg-surface-2 px-3 py-2 font-mono text-xs break-all"
		>
			{createdKey}
		</code>
		<Button onclick={copyKey}><Copy size={14} /> Copy</Button>
	</div>
</Dialog>
