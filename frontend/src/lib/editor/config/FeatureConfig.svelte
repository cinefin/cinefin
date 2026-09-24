<script lang="ts">
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import type { EditorBlock, EditorContext } from '../types';

	interface Props {
		block: EditorBlock;
		ctx: EditorContext;
		commit: (mutate: () => void) => void;
	}

	let { block, ctx, commit }: Props = $props();

	const featureOptions = $derived(
		Array.from({ length: ctx.featureCount }, (_, i) => ({
			value: String(i + 1),
			label: `Feature ${i + 1}`
		}))
	);
	const commandOptions = $derived(
		ctx.commands.map((c) => ({ value: String(c.id), label: c.name }))
	);
</script>

<ConfigForm>
	<ConfigField label="Feature number">
		<ConfigSelect
			value={block.content.feature_number ? String(block.content.feature_number) : ''}
			options={featureOptions}
			placeholder="Select..."
			onchange={(v) =>
				commit(() => {
					block.content.feature_number = v === '' ? null : parseInt(v, 10);
				})}
		/>
	</ConfigField>
	<ConfigField label="Credits command">
		<ConfigSelect
			value={block.content.credits_command_id ? String(block.content.credits_command_id) : ''}
			options={commandOptions}
			placeholder="None"
			onchange={(v) =>
				commit(() => {
					block.content.credits_command_id = v === '' ? null : parseInt(v, 10);
				})}
		/>
	</ConfigField>
</ConfigForm>
