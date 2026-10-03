<script lang="ts">
	// A player's screen and sound fields (Settings › Playout and the Add a player wizard,
	// which puts its test card and test sound beside them via `screenAction` / `soundAction`).
	// An Android TV player has one screen and one sound output, its HDMI: it picks the
	// display mode instead of a screen, and has its own picture and sound switches.
	import type { Snippet } from 'svelte';
	import { AlertTriangle, ChevronRight } from '@lucide/svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Toggle from '$lib/components/ui/Toggle.svelte';
	import Field from '$lib/settings/Field.svelte';
	import {
		audioDevices,
		currentMode,
		displayModes,
		isAndroid,
		modeLabel,
		type Hardware,
		type LaunchConfig
	} from './host-config';

	interface Props {
		config: LaunchConfig;
		hardware: Hardware | null;
		/** Unique per form on the page, for the field ids. */
		idPrefix: string;
		screenAction?: Snippet;
		soundAction?: Snippet;
	}

	let { config = $bindable(), hardware, idPrefix, screenAction, soundAction }: Props = $props();

	const SPDIF_CODECS = ['ac3', 'eac3', 'dts', 'dts-hd', 'truehd'];
	const HWDEC = 'auto auto-safe auto-copy no nvdec vaapi videotoolbox d3d11va'.split(' ');
	const CHANNELS = ['auto', 'stereo', '5.1', '7.1'];
	// gpu_context has no enumeration from the host; "" lets mpv choose.
	const GPU_CONTEXTS = ['', 'displayvk', 'drm', 'wayland', 'x11egl', 'win'];

	let showAdvanced = $state(false);
	const isDrm = $derived(config.graphics.mode === 'drm');
	const android = $derived(isAndroid(config));
	const modes = $derived(displayModes(hardware));
	const bitstream = $derived((config.audio.spdif_passthrough ?? []).length > 0);
	const devices = $derived(audioDevices(hardware));

	function toggleSpdif(codec: string, on: boolean) {
		const current = config.audio.spdif_passthrough ?? [];
		config.audio.spdif_passthrough = on ? [...current, codec] : current.filter((c) => c !== codec);
	}
</script>

{#snippet options(values: string[])}
	{#each values as v (v)}
		<option value={v}>{v}</option>
	{/each}
{/snippet}

{#if hardware?.note}
	<p class="flex items-start gap-2 text-xs text-warning">
		<AlertTriangle size={13} class="mt-px shrink-0" />
		{hardware.note}
	</p>
{/if}

<div class="grid grid-cols-1 gap-3 {screenAction || soundAction ? '' : 'sm:grid-cols-2'}">
	{#if android}
		<Field
			label="Display mode"
			forId="{idPrefix}-mode"
			hint="Set once for the player, never switched per film: a change blanks the screen for a few seconds."
		>
			<div class="flex flex-wrap gap-2">
				<Select
					id="{idPrefix}-mode"
					bind:value={config.graphics.display_mode}
					class="min-w-0 flex-1 basis-48"
				>
					<option value="">
						The box's own mode{currentMode(hardware) ? ` (now ${currentMode(hardware)})` : ''}
					</option>
					{#each modes as m (m)}
						<option value={m}>{modeLabel(m)}</option>
					{/each}
					{#if config.graphics.display_mode && !modes.includes(config.graphics.display_mode)}
						<option value={config.graphics.display_mode}>
							{modeLabel(config.graphics.display_mode)} (not offered)
						</option>
					{/if}
				</Select>
				{@render screenAction?.()}
			</div>
		</Field>
		<Field label="Sound" forId="{idPrefix}-dev">
			<div class="flex flex-wrap gap-2">
				<Input
					id="{idPrefix}-dev"
					value={hardware?.audio_devices?.[0]?.description || "The box's HDMI output"}
					disabled
					class="min-w-0 flex-1 basis-48"
				/>
				{@render soundAction?.()}
			</div>
		</Field>
	{:else if isDrm}
		<Field label="Connector" forId="{idPrefix}-conn">
			<div class="flex flex-wrap gap-2">
				<Select
					id="{idPrefix}-conn"
					bind:value={config.graphics.drm_connector}
					class="min-w-0 flex-1 basis-48"
				>
					<option value="">- choose an output -</option>
					{@render options(hardware?.drm_connectors ?? [])}
					{#if config.graphics.drm_connector && !(hardware?.drm_connectors ?? []).includes(config.graphics.drm_connector)}
						<option value={config.graphics.drm_connector}>
							{config.graphics.drm_connector} (not detected)
						</option>
					{/if}
				</Select>
				{@render screenAction?.()}
			</div>
		</Field>
	{:else}
		<Field label="Screen" forId="{idPrefix}-screen">
			<div class="flex flex-wrap gap-2">
				<Select
					id="{idPrefix}-screen"
					value={String(config.graphics.screen)}
					onchange={(e) => (config.graphics.screen = Number((e.target as HTMLSelectElement).value))}
					class="min-w-0 flex-1 basis-48"
				>
					{#each hardware?.screens ?? [] as s (s.index)}
						<option value={String(s.index)}>
							#{s.index}
							{s.name ? `· ${s.name}` : ''}
							{s.w ? `· ${s.w}×${s.h}` : ''}
						</option>
					{/each}
					{#if !(hardware?.screens ?? []).length}
						<option value={String(config.graphics.screen)}>#{config.graphics.screen}</option>
					{/if}
				</Select>
				{@render screenAction?.()}
			</div>
		</Field>
	{/if}

	{#if !android}
		<Field label="Sound" forId="{idPrefix}-dev">
			<div class="flex flex-wrap gap-2">
				<Select
					id="{idPrefix}-dev"
					bind:value={config.audio.device}
					class="min-w-0 flex-1 basis-48"
				>
					<option value="">Auto (mpv default)</option>
					{#each devices as d (d.name)}
						<option value={d.name}>{d.description || d.name}</option>
					{/each}
					{#if config.audio.device && !devices.some((d) => d.name === config.audio.device)}
						<option value={config.audio.device}>{config.audio.device} (not detected)</option>
					{/if}
				</Select>
				{@render soundAction?.()}
			</div>
		</Field>
	{/if}
</div>

{#if android}
	<Toggle
		label="Keep the screen on"
		bind:checked={config.graphics.keep_awake}
		hint="While the player is in front the box never dims or goes to standby."
	/>
{:else}
	<Toggle label="Start the player when the box boots" bind:checked={config.autostart} />
{/if}

<div class="border-t border-border pt-3">
	<button
		type="button"
		class="flex items-center gap-1.5 text-xs font-medium text-muted hover:text-text"
		aria-expanded={showAdvanced}
		onclick={() => (showAdvanced = !showAdvanced)}
	>
		<ChevronRight size={13} class="transition-transform {showAdvanced ? 'rotate-90' : ''}" />
		Advanced
	</button>

	{#if showAdvanced && android}
		<div class="mt-4 space-y-5">
			<div>
				<p class="mb-2 text-xs font-medium text-muted">Picture</p>
				<Toggle
					label="Tunnelled playback"
					bind:checked={config.graphics.tunneling}
					hint="Picture and sound kept in step by the decoder. Try it if lip sync drifts."
				/>
				{#if hardware?.android?.hdr?.length}
					<p class="mt-2 text-xs text-muted">The screen shows {hardware.android.hdr.join(', ')}.</p>
				{/if}
			</div>
			<div class="border-t border-border pt-4">
				<p class="mb-2 text-xs font-medium text-muted">Sound</p>
				<Toggle
					label="Bitstream to the receiver"
					checked={bitstream}
					onchange={(e) =>
						(config.audio.spdif_passthrough = (e.target as HTMLInputElement).checked
							? [...SPDIF_CODECS]
							: [])}
					hint="Dolby and DTS go to the receiver untouched. Off decodes them on the box."
				/>
				{#if hardware?.android}
					<p class="mt-2 text-xs text-muted">
						{hardware.android.passthrough?.length
							? `The receiver takes ${hardware.android.passthrough.join(', ')}.`
							: 'The receiver takes no bitstream formats, so everything is decoded on the box.'}
					</p>
				{/if}
			</div>
		</div>
	{:else if showAdvanced}
		<div class="mt-4 space-y-5">
			<div>
				<p class="mb-2 text-xs font-medium text-muted">Picture</p>
				<div class="grid gap-x-6 gap-y-4 sm:grid-cols-2">
					<Field label="Picture output" forId="{idPrefix}-mode">
						<Select id="{idPrefix}-mode" bind:value={config.graphics.mode} class="w-full">
							<option value="desktop">Desktop session</option>
							<option value="drm">Direct to screen (DRM)</option>
						</Select>
					</Field>
					{#if isDrm}
						<Field label="Pinned mode" forId="{idPrefix}-drmmode">
							<Input
								id="{idPrefix}-drmmode"
								bind:value={config.graphics.drm_mode}
								placeholder="e.g. 3840x2160@60 - blank to let the screen decide"
							/>
						</Field>
					{:else}
						<Field label="X display" forId="{idPrefix}-display">
							<Input
								id="{idPrefix}-display"
								bind:value={config.graphics.display}
								placeholder=":0"
							/>
						</Field>
					{/if}
					<Field label="Video output" forId="{idPrefix}-vo">
						<Select id="{idPrefix}-vo" bind:value={config.graphics.vo} class="w-full">
							{@render options(hardware?.mpv?.vo ?? [config.graphics.vo])}
						</Select>
					</Field>
					<Field label="GPU API" forId="{idPrefix}-api">
						<Select id="{idPrefix}-api" bind:value={config.graphics.gpu_api} class="w-full">
							<option value="">Auto (mpv decides)</option>
							{@render options(hardware?.mpv?.gpu_apis ?? [])}
						</Select>
					</Field>
					<Field label="GPU context" forId="{idPrefix}-ctx">
						<Select id="{idPrefix}-ctx" bind:value={config.graphics.gpu_context} class="w-full">
							{#each GPU_CONTEXTS as c (c)}
								<option value={c}>{c === '' ? 'Auto' : c}</option>
							{/each}
						</Select>
						{#snippet hintSnippet()}
							Vulkan on a direct-to-screen host wants <code>displayvk</code>.
						{/snippet}
					</Field>
					<Field label="Hardware decoding" forId="{idPrefix}-hwdec">
						<Select id="{idPrefix}-hwdec" bind:value={config.graphics.hwdec} class="w-full">
							{@render options(HWDEC)}
						</Select>
					</Field>
				</div>
				<div class="mt-3 flex flex-wrap gap-x-6 gap-y-2">
					<Toggle label="Fullscreen" bind:checked={config.graphics.fullscreen} />
					<Toggle
						label="HDR passthrough"
						bind:checked={config.graphics.hdr_passthrough}
						hint="Send HDR to the display instead of tone-mapping to SDR."
					/>
					<Toggle
						label="On-screen controller"
						bind:checked={config.graphics.osc}
						hint="mpv's own seek bar on mouse-over. Off gives a clean theater screen."
					/>
				</div>
			</div>

			<div class="border-t border-border pt-4">
				<p class="mb-2 text-xs font-medium text-muted">Sound</p>
				<div class="grid gap-x-6 gap-y-4 sm:grid-cols-2">
					<Field label="Channels" forId="{idPrefix}-ch">
						<Select id="{idPrefix}-ch" bind:value={config.audio.channels} class="w-full">
							{@render options(CHANNELS)}
						</Select>
					</Field>
					<Field label="Maximum volume" forId="{idPrefix}-vol" hint="Percent. mpv's volume-max.">
						<Input
							id="{idPrefix}-vol"
							type="number"
							value={String(config.audio.max_volume)}
							oninput={(e) =>
								(config.audio.max_volume = Number((e.target as HTMLInputElement).value) || 0)}
						/>
					</Field>
				</div>
				<div class="mt-3">
					<p class="mb-1.5 text-xs text-muted">
						Bitstream to the receiver - sent untouched instead of being decoded here.
					</p>
					<div class="flex flex-wrap gap-x-5 gap-y-2">
						{#each SPDIF_CODECS as codec (codec)}
							<Toggle
								label={codec}
								checked={(config.audio.spdif_passthrough ?? []).includes(codec)}
								onchange={(e) => toggleSpdif(codec, (e.target as HTMLInputElement).checked)}
							/>
						{/each}
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>
