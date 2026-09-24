<script lang="ts">
	import { CircleHelp, SquareArrowOutUpRight, Zap } from '@lucide/svelte';
	import { base } from '$app/paths';
	import { api, unwrap } from '$lib/api/client';
	import { showToast } from '$lib/toast.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import type { EditorBlock, EditorContext } from '../types';
	import { HELP, commandTarget } from '../types';

	interface Props {
		block: EditorBlock;
		ctx: EditorContext;
		commit: (mutate: () => void) => void;
	}

	let { block, ctx, commit }: Props = $props();

	const cmd = $derived(ctx.commands.find((c) => c.id === block.content.command_id));
	const target = $derived(cmd ? commandTarget(cmd) : '');
	const holdHint = $derived.by(() => {
		if (!block.content.hold_black || !cmd) return null;
		return cmd.duration
			? `At least ${cmd.duration}s of black while it runs`
			: 'Black holds until the command finishes; set a duration for a longer minimum';
	});

	let testing = $state(false);

	function selectCommand(value: string): void {
		const chosen = ctx.commands.find((c) => c.id === parseInt(value, 10));
		if (!chosen) return;
		commit(() => {
			block.content.command_id = chosen.id;
			block.content.name = chosen.name;
			block.details = { ...block.details, duration: chosen.duration };
		});
	}

	async function testCommand(): Promise<void> {
		if (!cmd || testing) return;
		testing = true;
		try {
			const data = await unwrap(
				api.POST('/api/v2/commands/{command_id}/execute', {
					params: { path: { command_id: cmd.id } }
				})
			);
			const result = data.result;
			if (result.ok) showToast(`Command succeeded (${result.detail})`, 'success');
			else showToast(`Command failed${result.detail ? ` (${result.detail})` : ''}`, 'error');
		} catch (e) {
			showToast('Command failed: ' + (e instanceof Error ? e.message : 'Unknown error'), 'error');
		} finally {
			testing = false;
		}
	}
</script>

<ConfigForm>
	<ConfigField label="Command">
		<ConfigSelect
			value={block.content.command_id ? String(block.content.command_id) : ''}
			options={ctx.commands.map((c) => ({ value: String(c.id), label: c.name }))}
			placeholder="Select..."
			onchange={selectCommand}
		/>
	</ConfigField>

	<ConfigField label="Hold black screen" hint={holdHint}>
		<label class="inline-flex h-8 items-center gap-2 text-sm text-text">
			<input
				type="checkbox"
				class="accent-accent"
				checked={block.content.hold_black === true}
				onchange={(e) =>
					commit(() => {
						block.content.hold_black = (e.target as HTMLInputElement).checked;
					})}
			/>
			Hold until it finishes
		</label>
		<span class="cursor-help text-faint" title={HELP.command_hold}>
			<CircleHelp size={13} aria-label="Hold vs. instant commands" />
		</span>
	</ConfigField>

	{#if cmd}
		<ConfigField label={cmd ? cmd.provider_label : 'Target'} wide>
			<span class="truncate font-mono text-xs text-muted" title={target}>{target || '-'}</span>
		</ConfigField>
	{/if}

	{#snippet actions()}
		{#if cmd}
			<Button
				size="sm"
				disabled={testing}
				title="Run this command now and show the result"
				onclick={() => void testCommand()}
			>
				<Zap size={12} />
				{testing ? 'Running…' : 'Test'}
			</Button>
		{/if}
		<a
			class="inline-flex items-center gap-1 text-xs text-muted hover:text-text"
			href="{base}/commands"
			title="Create and edit commands on the Commands page"
		>
			<SquareArrowOutUpRight size={11} /> Manage commands
		</a>
	{/snippet}
</ConfigForm>
