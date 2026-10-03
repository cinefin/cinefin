<script lang="ts">
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import { featureOptions, idOptions, type ConfigProps } from '../types';

	let { block, ctx, commit }: ConfigProps = $props();
</script>

<ConfigForm>
	<ConfigField label="Feature number">
		<ConfigSelect
			value={block.content.feature_number}
			options={featureOptions(ctx.featureCount)}
			placeholder="Select..."
			onnumber={(v) => commit(() => (block.content.feature_number = v))}
		/>
	</ConfigField>
	<ConfigField label="Credits command">
		<ConfigSelect
			value={block.content.credits_command_id}
			options={idOptions(ctx.commands)}
			placeholder="None"
			onnumber={(v) => commit(() => (block.content.credits_command_id = v))}
		/>
	</ConfigField>
</ConfigForm>
