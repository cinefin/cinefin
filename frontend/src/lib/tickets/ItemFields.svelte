<script lang="ts">
	// The settings of one ticket element (any kind but columns), whether it is a line of its own or
	// an item in a columns cell. Changes go back through `onpatch`, which records and saves them.
	import Field from '$lib/settings/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Toggle from '$lib/components/ui/Toggle.svelte';
	import ImageLibrary from '$lib/components/ImageLibrary.svelte';
	import Segmented from './Segmented.svelte';
	import {
		ALIGNMENTS,
		BARCODES,
		QR_ERRORS,
		QR_RENDERS,
		TEXT_SIZES,
		TOKENS,
		type TicketElement
	} from './kinds';

	interface Props {
		el: TicketElement;
		onpatch: (key: keyof TicketElement, value: unknown) => void;
	}
	let { el, onpatch }: Props = $props();

	const uid = $props.id();
	const val = (e: Event) => (e.currentTarget as HTMLInputElement).value;
	const checked = (e: Event) => (e.currentTarget as HTMLInputElement).checked;
	const inputCls =
		'w-full rounded-md border border-border bg-surface-2 px-3 py-2 font-mono text-sm text-text hover:border-border-strong focus:border-accent focus:outline-none';

	// The content field the token chips insert into.
	let contentField = $state<HTMLInputElement | HTMLTextAreaElement>();
	function insertToken(token: string) {
		const field = contentField;
		if (!field) return;
		const start = field.selectionStart ?? field.value.length;
		const end = field.selectionEnd ?? field.value.length;
		const ins = `{${token}}`;
		onpatch('content', field.value.slice(0, start) + ins + field.value.slice(end));
		requestAnimationFrame(() => {
			field.focus();
			field.setSelectionRange(start + ins.length, start + ins.length);
		});
	}
</script>

<!-- The one size control: a share of the ticket's width, or of the cell in a columns row. An image
	 (fallback null) can instead print at its own size. -->
{#snippet width(fallback: number | null)}
	{@const value = el.width === undefined ? fallback : el.width}
	<Field label="Width (share of the ticket, or of its cell)" forId="{uid}-width">
		<div class="flex flex-wrap items-center gap-3">
			<input
				id="{uid}-width"
				type="range"
				min="10"
				max="100"
				step="5"
				class="w-48 accent-accent disabled:opacity-40"
				disabled={value === null}
				value={value ?? 100}
				oninput={(e) => onpatch('width', parseInt(val(e), 10))}
			/>
			<span class="w-12 font-mono text-xs text-muted">{value === null ? '' : `${value}%`}</span>
			{#if fallback === null}
				<Toggle
					label="Its own size"
					checked={value === null}
					onchange={(e) => onpatch('width', checked(e) ? null : 50)}
				/>
			{/if}
		</div>
	</Field>
{/snippet}

{#snippet tokens()}
	<div class="flex flex-wrap gap-1.5" role="group" aria-label="Insert a detail">
		{#each TOKENS as t (t.id)}
			<button
				type="button"
				class="h-7 rounded-sm border border-border bg-surface-2 px-2 text-xs text-muted hover:bg-surface-3 hover:text-text"
				title={t.hint ?? `Inserts {${t.id}}`}
				onclick={() => insertToken(t.id)}>{t.label}</button
			>
		{/each}
	</div>
{/snippet}

<div class="space-y-4">
	{#if el.type === 'text'}
		<Field label="Text" forId="{uid}-content">
			<textarea
				id="{uid}-content"
				rows="2"
				class={inputCls}
				bind:this={contentField}
				value={el.content ?? ''}
				oninput={(e) => onpatch('content', val(e))}></textarea>
		</Field>
		{@render tokens()}
	{:else if el.type === 'barcode'}
		<div class="grid gap-3 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
			<Field label="Type" forId="{uid}-symbology">
				<Select
					id="{uid}-symbology"
					value={el.symbology || 'code128'}
					onchange={(e) => onpatch('symbology', val(e))}
				>
					{#each BARCODES as b (b.id)}<option value={b.id}>{b.label}</option>{/each}
				</Select>
			</Field>
			<Field label="Content" forId="{uid}-content">
				<input
					id="{uid}-content"
					type="text"
					class={inputCls}
					bind:this={contentField}
					value={el.content ?? ''}
					oninput={(e) => onpatch('content', val(e))}
				/>
			</Field>
		</div>
		{@render tokens()}
		<p class="text-xs text-muted">
			Code 128 takes any text and suits most scanners. EAN, UPC and ITF take digits only and are
			padded with zeros.
		</p>
	{:else if el.type === 'qr'}
		<div class="grid gap-3 sm:grid-cols-2">
			<Field label="Opens" forId="{uid}-mode">
				<Select
					id="{uid}-mode"
					value={el.mode === 'fun' ? 'fun' : 'content'}
					onchange={(e) => onpatch('mode', val(e))}
				>
					<option value="fun">A surprise link</option>
					<option value="content">Fixed content</option>
				</Select>
			</Field>
			<Field label="Error correction" forId="{uid}-error">
				<Select
					id="{uid}-error"
					value={el.error || 'low'}
					onchange={(e) => onpatch('error', val(e))}
				>
					{#each QR_ERRORS as q (q.id)}<option value={q.id}>{q.label}</option>{/each}
				</Select>
			</Field>
			<Field label="Drawn by" forId="{uid}-render">
				<Select
					id="{uid}-render"
					value={el.render || 'image'}
					onchange={(e) => onpatch('render', val(e))}
				>
					{#each QR_RENDERS as r (r.id)}<option value={r.id}>{r.label}</option>{/each}
				</Select>
			</Field>
		</div>
		{@render width(50)}
		{#if el.mode === 'fun'}
			<p class="text-xs text-muted">One of the design's surprise links, picked at random.</p>
		{:else}
			<Field label="Content" forId="{uid}-content">
				<input
					id="{uid}-content"
					type="text"
					class={inputCls}
					bind:this={contentField}
					value={el.content ?? ''}
					oninput={(e) => onpatch('content', val(e))}
				/>
			</Field>
			{@render tokens()}
		{/if}
		<p class="text-xs text-muted">
			More error correction scans through smudges and tears but makes a denser code. The printer's
			own QR is sharper; use it if your printer has one.
		</p>
	{:else if el.type === 'rating'}
		{@render width(25)}
		<p class="text-xs text-muted">
			The programme's certificate: the most restrictive among its features.
		</p>
	{:else if el.type === 'image'}
		<Field label="Image">
			<ImageLibrary
				library="tickets"
				selected={el.file}
				onselect={(img) => onpatch('file', img.name)}
			/>
		</Field>
		{@render width(null)}
		<p class="text-xs text-muted">Prints in black and white: bold, high-contrast art works best.</p>
	{:else if el.type === 'spacer'}
		<Field label="Blank lines (1 to 10)" forId="{uid}-lines" class="max-w-40">
			<Input
				id="{uid}-lines"
				type="number"
				value={String(el.lines ?? 1)}
				oninput={(e) => onpatch('lines', parseInt(val(e), 10) || 1)}
			/>
		</Field>
	{:else if el.type === 'rule'}
		<p class="text-xs text-muted">A line across the ticket, or across its cell.</p>
	{/if}

	{#if el.type !== 'rule' && el.type !== 'spacer'}
		<div class="flex flex-wrap items-end gap-x-5 gap-y-3">
			<Field label="Align">
				<Segmented
					label="Align"
					choices={ALIGNMENTS}
					value={el.align ?? 'center'}
					onchange={(v) => onpatch('align', v)}
				/>
			</Field>
			{#if el.type === 'text'}
				<Field label="Size">
					<Segmented
						label="Text size"
						choices={TEXT_SIZES}
						value={typeof el.size === 'string' ? el.size : 'normal'}
						onchange={(v) => onpatch('size', v)}
					/>
				</Field>
			{/if}
		</div>
		{#if el.type === 'text'}
			<div class="flex gap-5">
				<Toggle label="Bold" checked={!!el.bold} onchange={(e) => onpatch('bold', checked(e))} />
				<Toggle
					label="White on black"
					checked={!!el.invert}
					onchange={(e) => onpatch('invert', checked(e))}
				/>
			</div>
		{/if}
	{/if}
</div>
