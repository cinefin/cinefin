<script lang="ts">
	import { Download, FileArchive, Info, RotateCcw, TriangleAlert } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import { uploadWithProgress } from '$lib/upload';
	import { showToast } from '$lib/toast.svelte';
	import { formatBytes, formatDateTime } from '$lib/settings/form.svelte';
	import type { CheckState } from '$lib/settings/types';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import CheckResult from './CheckResult.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	interface Props {
		confirm: ConfirmDialog['confirm'];
	}
	let { confirm }: Props = $props();

	const info = query(() => unwrap(api.GET('/api/v2/backup/info')));

	let fileInput: HTMLInputElement | undefined = $state();
	let backupFile = $state<File | null>(null);
	let restoring = $state(false);
	let restoreResult = $state<CheckState>(null);
	let restartRequired = $state(false);

	function onFilePicked() {
		backupFile = fileInput?.files?.[0] ?? null;
		restoreResult = null;
	}

	interface RestoreResult {
		restored: boolean;
		restart_required: boolean;
		manifest: { created_at: string | null };
	}

	async function restore() {
		if (!backupFile) return;
		const confirmed = await confirm(
			'This replaces your entire database - programmes, schedules, settings, ticket history - ' +
				"with the backup's contents. The current data is overwritten. A restart is required " +
				'afterward. Restore this backup?',
			{ confirmLabel: 'Restore' }
		);
		if (!confirmed) return;

		restoring = true;
		restoreResult = { state: 'pending', message: 'Validating and restoring…' };
		try {
			const result = await uploadWithProgress<RestoreResult>(
				'/api/v2/backup/restore',
				backupFile,
				{},
				(e) => {
					if (e.percent < 100) {
						restoreResult = {
							state: 'pending',
							message: `Uploading… ${Math.round(e.percent)}%`
						};
					} else {
						restoreResult = { state: 'pending', message: 'Validating and restoring…' };
					}
				},
				'backup'
			);
			restartRequired = true;
			const when = result?.manifest?.created_at;
			restoreResult = {
				state: 'ok',
				message: when
					? `Restored backup from ${formatDateTime(when)} - restart required (see below)`
					: 'Restored - restart required (see below)'
			};
			showToast('Backup restored - restart Cinefin to load it', 'success');
		} catch (e) {
			const msg = e instanceof Error ? e.message : 'Restore failed';
			restoreResult = { state: 'error', message: msg };
			showToast(msg, 'error');
		} finally {
			restoring = false;
		}
	}
</script>

<div class="space-y-4">
	<div class="flex items-start gap-3 rounded-md border border-border bg-surface-1 p-3 text-sm">
		<Info size={18} class="mt-0.5 shrink-0 text-muted" />
		<div class="text-muted">
			A backup contains your whole database - programmes, schedules, settings and ticket history.
			<strong class="text-text">Media files aren't included</strong> (posters, generated cert/title videos,
			uploaded media): they're large and re-derivable - thumbnails re-sync from Jellyfin/Plex and cert/title
			cards regenerate.
		</div>
	</div>

	<Card title="Download backup">
		{#if info.loading}
			<Spinner size="sm" />
		{:else if info.error}
			<ErrorState compact error={info.error} retry={() => void info.load()} />
		{:else if info.data}
			<div class="mb-4 max-w-md divide-y divide-border rounded-md border border-border text-sm">
				<div class="flex justify-between gap-4 px-3 py-1.5">
					<span class="text-muted">Database file</span>
					<span class="font-mono text-xs">{info.data.database_filename || '-'}</span>
				</div>
				<div class="flex justify-between gap-4 px-3 py-1.5">
					<span class="text-muted">Size</span>
					<span class="font-mono text-xs">{formatBytes(info.data.database_size_bytes || 0)}</span>
				</div>
				<div class="flex justify-between gap-4 px-3 py-1.5">
					<span class="text-muted">Last modified</span>
					<span class="font-mono text-xs">{formatDateTime(info.data.database_modified_at)}</span>
				</div>
				<div class="flex justify-between gap-4 px-3 py-1.5">
					<span class="text-muted">App version</span>
					<span class="font-mono text-xs">{info.data.app_version || '-'}</span>
				</div>
			</div>
		{/if}
		<Button variant="primary" href="/api/v2/backup/download">
			<Download size={14} /> Download backup
		</Button>
		<p class="mt-2 text-xs text-faint">
			Downloads a single <code class="font-mono">.zip</code> - keep it somewhere safe, off this machine.
		</p>
	</Card>

	<Card title="Restore from backup">
		<div class="space-y-3">
			<div class="flex flex-wrap items-center gap-2">
				<Button onclick={() => fileInput?.click()}>
					<FileArchive size={14} /> Choose backup file
				</Button>
				<Button variant="danger" disabled={!backupFile || restoring} onclick={restore}>
					<RotateCcw size={14} /> Restore this backup
				</Button>
			</div>
			<input
				type="file"
				bind:this={fileInput}
				accept=".zip,application/zip"
				hidden
				onchange={onFilePicked}
			/>
			{#if backupFile}
				<p class="text-xs text-muted">
					Selected: {backupFile.name} ({formatBytes(backupFile.size)})
				</p>
			{/if}
			<CheckResult result={restoreResult} />
			<p class="text-xs text-faint">
				Restoring <strong class="text-text">replaces your entire database</strong> with the backup's contents
				- the current data is overwritten. A restart is required afterward.
			</p>
			{#if restartRequired}
				<div
					class="flex items-start gap-3 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm"
					role="alert"
				>
					<TriangleAlert size={18} class="mt-0.5 shrink-0 text-warning" />
					<div>
						<strong>Backup restored.</strong>
						Restart Cinefin now to load the restored database -
						<code class="font-mono">systemctl restart</code> /
						<code class="font-mono">docker restart</code>, however you run it. The app keeps using
						the old data until it's restarted.
					</div>
				</div>
			{/if}
		</div>
	</Card>
</div>
