<script lang="ts">
	/**
	 * The global playout bar (every page but the remote, while a player is active), drawn from
	 * the server's status via `$lib/playout/phase`. Action failures only console.error: a
	 * background surface shouldn't stack toasts over whatever page is open.
	 */
	import { base } from '$app/paths';
	import {
		Pause,
		Play,
		Settings,
		SkipBack,
		SkipForward,
		SlidersVertical,
		Square
	} from '@lucide/svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import PhaseLamp from '$lib/components/shell/PhaseLamp.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import { formatTime } from '$lib/format';
	import { itemTypeClasses, itemTypeLabel } from '$lib/item-types';
	import CueDialog from '$lib/playout/CueDialog.svelte';
	import { barLines, can, lamp, primaryAction, screeningLine } from '$lib/playout/phase';
	import RunningOrder from '$lib/playout/RunningOrder.svelte';
	import { playlist } from '$lib/stores/player.svelte';
	import { playout, type ControlBody } from '$lib/stores/playout.svelte';
	import { playoutReach } from '$lib/stores/playoutReach.svelte';

	$effect(() => playout.subscribe());
	$effect(() => playlist.subscribe());
	// The player's address for the offline line: the host list, never the (public) status.
	$effect(() => playoutReach.subscribe());

	const status = $derived(playout.status);
	const phase = $derived(status?.phase);
	const light = $derived(lamp(status));
	const lines = $derived(status ? barLines(status, playoutReach.hostUrl) : null);
	const primary = $derived(primaryAction(status));
	const loaded = $derived(!!status?.programme);

	async function act(body: ControlBody) {
		try {
			await playout.control(body);
		} catch (err) {
			console.error('Playout bar: action failed:', err);
		}
		playlist.refresh();
	}

	// Ending the programme is destructive and this bar follows you onto every
	// page, so it asks first, with the remote's wording.
	let confirmDlg = $state<ConfirmDialog | undefined>();
	async function endProgramme() {
		const ok = await confirmDlg?.confirm(
			'End the programme? The running order is cleared and the player goes to standby.',
			{ confirmLabel: 'End programme' }
		);
		if (ok) void act({ action: 'end' });
	}

	let cueOpen = $state(false);
	async function statusLine(show: boolean) {
		try {
			await playout.setStatusLine(show);
		} catch (err) {
			console.error('Playout bar: status line failed:', err);
		}
	}

	const iconBtn =
		'rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text disabled:pointer-events-none disabled:opacity-40';
</script>

{#snippet skip(action: 'previous' | 'next', label: string, Icon: typeof SkipBack, cls = '')}
	<button
		type="button"
		class="{iconBtn} {cls}"
		title={label}
		aria-label={label}
		disabled={!status || !can(status, action)}
		onclick={() => void act({ action })}
	>
		<Icon size={15} />
	</button>
{/snippet}

{#if status?.player && lines}
	<ConfirmDialog bind:this={confirmDlg} title="End programme?" />
	<CueDialog bind:open={cueOpen} oncued={() => playlist.refresh()} />
	<div class="border-t border-border bg-surface-1">
		<div class="flex h-14 items-center gap-3 px-3 md:gap-4 md:px-4">
			<div class="hidden w-28 shrink-0 sm:block">
				<PhaseLamp lamp={light} />
			</div>

			<div class="min-w-0 flex-1 sm:w-40 sm:flex-none md:w-64">
				{#if loaded}
					<a
						href="{base}/programmes/{status.programme?.id}"
						class="block truncate text-sm font-medium hover:text-accent"
						title="Open programme">{lines.title}</a
					>
				{:else}
					<p class="truncate text-sm font-medium">{lines.title}</p>
				{/if}
				<p class="truncate text-xs text-muted" title={lines.detail}>
					{#if lines.type}<span class={itemTypeClasses(lines.type).icon}
							>{itemTypeLabel(lines.type, { short: true })}</span
						>{' · '}{/if}{lines.detail}
				</p>
			</div>

			{#if phase === 'offline'}
				<p class="hidden min-w-0 flex-1 truncate text-sm text-muted lg:block">
					Retrying every few seconds.{status.player.kind === 'agent'
						? ' The player shows its own standby meanwhile.'
						: ''}
				</p>
				<Button href="{base}/settings?tab=playout" size="sm" class="ml-auto lg:ml-0">
					<Settings size={13} /> Player settings
				</Button>
			{:else if phase === 'standby'}
				<p class="hidden min-w-0 flex-1 truncate text-sm text-muted lg:block">
					{status.next_screening
						? `Next screening · ${screeningLine(status.next_screening)}`
						: 'No screenings scheduled'}
				</p>
				<span class="ml-auto hidden md:block lg:ml-0">
					<Switch
						class="text-xs text-muted"
						label="Status line"
						checked={status.player.show_status}
						onchange={(show) => void statusLine(show)}
					/>
				</span>
				<Button
					variant="primary"
					size="sm"
					class="ml-auto md:ml-0"
					disabled={!can(status, 'cue')}
					onclick={() => (cueOpen = true)}
				>
					Cue a programme
				</Button>
			{:else}
				{#if phase === 'cued'}
					<Button variant="primary" size="sm" onclick={() => void act({ action: 'start' })}>
						<Play size={13} /> Start
					</Button>
				{:else}
					<div class="flex items-center gap-1">
						{@render skip('previous', 'Previous item', SkipBack, 'hidden sm:block')}
						<button
							type="button"
							class="rounded-md bg-accent p-2 text-on-accent hover:bg-accent-hover disabled:pointer-events-none disabled:opacity-40"
							title={primary.label}
							aria-label={primary.label}
							disabled={!primary.enabled}
							onclick={() => void act({ action: primary.action })}
						>
							{#if primary.action === 'pause'}<Pause size={15} />{:else}<Play size={15} />{/if}
						</button>
						{#if phase === 'hold'}
							<Button
								size="sm"
								title="End the command's hold and move on"
								disabled={!can(status, 'end_hold')}
								onclick={() => void act({ action: 'end_hold' })}>End hold</Button
							>
						{:else}
							{@render skip('next', 'Next item', SkipForward)}
						{/if}
					</div>
				{/if}

				{#if status.manual}
					<p class="hidden min-w-0 flex-1 truncate text-sm text-muted sm:block">
						{status.manual.items.length} in the manual queue
					</p>
				{:else}
					<div class="hidden min-w-0 flex-1 items-center gap-2.5 sm:flex">
						<span class="shrink-0 font-mono text-xs text-muted">
							{formatTime(
								phase === 'preshow'
									? (status.playback?.position ?? 0)
									: (status.playlist?.programme_elapsed_time ?? 0)
							)}
						</span>
						<RunningOrder
							{status}
							items={playlist.data?.playlist ?? []}
							onjump={(index) => void act({ action: 'jump', index })}
							class="flex-1"
						/>
						<span class="shrink-0 font-mono text-xs text-muted">
							{formatTime(status.playlist?.programme_total_duration ?? 0)}
						</span>
					</div>
				{/if}

				<!-- Destructive, so it stands apart from the transport and confirms. -->
				<button
					type="button"
					class="ml-auto flex shrink-0 items-center gap-1.5 rounded-md border border-danger/40 px-2.5 py-1.5 text-xs text-danger hover:bg-danger/10 disabled:opacity-40 sm:ml-0"
					title="End - the running order is cleared and the player goes to standby"
					disabled={!can(status, 'end')}
					onclick={() => void endProgramme()}
				>
					<Square size={13} />
					<span class="hidden md:inline">{status.manual ? 'End' : 'End programme'}</span>
				</button>
			{/if}

			<a
				href="{base}/remote"
				class="flex shrink-0 items-center gap-1.5 rounded-md border border-border-strong px-2.5 py-1.5 text-xs text-muted hover:bg-surface-2 hover:text-text"
				title="Open the remote"
			>
				<SlidersVertical size={13} />
				<span class="hidden md:inline">Remote</span>
			</a>
		</div>
	</div>
{/if}
