<script lang="ts">
	import { AlertTriangle, ChevronRight, RefreshCw, Save } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { showToast } from '$lib/toast.svelte';
	import type { components } from '$lib/api/types.gen';
	import Button from '$lib/components/ui/Button.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Field from './Field.svelte';
	import Toggle from '$lib/components/ui/Toggle.svelte';

	type Hardware = components['schemas']['HostHardwareSchema'];
	type WireConfig = components['schemas']['HostLaunchConfigSchema'];
	// The wire schema defaults graphics/audio optional; normalise once so the
	// form has every field present.
	type LaunchConfig = Required<WireConfig> & {
		graphics: Required<NonNullable<WireConfig['graphics']>>;
		audio: Required<NonNullable<WireConfig['audio']>>;
	};

	function normalise(wire: WireConfig): LaunchConfig {
		const g = wire.graphics ?? ({} as NonNullable<WireConfig['graphics']>);
		const a = wire.audio ?? ({} as NonNullable<WireConfig['audio']>);
		return {
			autostart: wire.autostart ?? true,
			graphics: {
				mode: g.mode ?? 'desktop',
				vo: g.vo ?? 'gpu-next',
				gpu_api: g.gpu_api ?? '',
				gpu_context: g.gpu_context ?? '',
				hwdec: g.hwdec ?? 'auto',
				screen: g.screen ?? 0,
				drm_connector: g.drm_connector ?? '',
				drm_mode: g.drm_mode ?? '',
				fullscreen: g.fullscreen ?? true,
				hdr_passthrough: g.hdr_passthrough ?? true,
				osc: g.osc ?? false,
				display: g.display ?? '',
				idle_media: g.idle_media ?? ''
			},
			audio: {
				device: a.device ?? '',
				channels: a.channels ?? 'auto',
				spdif_passthrough: a.spdif_passthrough ?? [],
				max_volume: a.max_volume ?? 130
			}
		};
	}

	interface Props {
		hostId: number;
		kind: string;
	}

	const { hostId, kind }: Props = $props();

	const SPDIF_CODECS = ['ac3', 'eac3', 'dts', 'dts-hd', 'truehd'];
	const HWDEC = [
		'auto',
		'auto-safe',
		'auto-copy',
		'no',
		'nvdec',
		'vaapi',
		'videotoolbox',
		'd3d11va'
	];
	const CHANNELS = ['auto', 'stereo', '5.1', '7.1'];
	// gpu_context has no enumeration from the host; "" lets mpv choose.
	const GPU_CONTEXTS = ['', 'displayvk', 'drm', 'wayland', 'x11egl', 'win'];

	let config = $state<LaunchConfig | null>(null);
	let hardware = $state<Hardware | null>(null);
	let loading = $state(true);
	let loadError = $state<string | null>(null);
	let saving = $state(false);
	let restartPending = $state(false);
	let showAdvanced = $state(false);

	async function load() {
		loading = true;
		loadError = null;
		try {
			config = normalise(
				await unwrap(
					api.GET('/api/v2/playout/hosts/{host_id}/config', {
						params: { path: { host_id: hostId } }
					})
				)
			);
			// Hardware is garnish: without it the selects fall back to the values
			// already set, so an mpv-less host still shows an editable form.
			hardware = await unwrap(
				api.GET('/api/v2/playout/hosts/{host_id}/hardware', {
					params: { path: { host_id: hostId } }
				})
			).catch(() => null);
		} catch (e) {
			loadError = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (kind === 'agent') void load();
		else loading = false;
	});

	const isDrm = $derived(config?.graphics?.mode === 'drm');

	function toggleSpdif(codec: string, on: boolean) {
		if (!config) return;
		const current = config.audio.spdif_passthrough ?? [];
		config.audio.spdif_passthrough = on ? [...current, codec] : current.filter((c) => c !== codec);
	}

	async function save(thenRestart: boolean) {
		if (!config) return;
		saving = true;
		try {
			const result = await mutate(
				api.PUT('/api/v2/playout/hosts/{host_id}/config', {
					params: { path: { host_id: hostId } },
					body: config
				})
			);
			const needsRestart = Boolean(
				(result as { data?: { restart_required?: boolean } })?.data?.restart_required
			);
			if (thenRestart && needsRestart) {
				await mutate(api.POST('/api/v2/playout/agent/restart'));
				showToast('Saved - the player is restarting', 'success');
				restartPending = false;
			} else {
				showToast('Host configuration saved', 'success');
				restartPending = needsRestart;
			}
		} catch (e) {
			showToast(e instanceof Error ? e.message : String(e), 'error');
		} finally {
			saving = false;
		}
	}
</script>

{#if kind !== 'agent'}
	<p class="p-3 text-sm text-muted">
		A local mpv host has no agent, so Cinefin cannot configure it. Set its display and audio through
		mpv's own options when you launch it.
	</p>
{:else if loading}
	<div class="p-3"><Spinner size="sm" label="Reading the host's configuration…" /></div>
{:else if loadError}
	<div class="p-3"><ErrorState compact message={loadError} retry={() => void load()} /></div>
{:else if config}
	<div class="max-w-2xl space-y-5 p-3">
		{#if hardware?.note}
			<p class="flex items-start gap-2 text-xs text-warning">
				<AlertTriangle size={13} class="mt-px shrink-0" />
				{hardware.note}
			</p>
		{/if}

		<div class="grid gap-3 sm:grid-cols-2">
			<Field label="Picture output" forId="hc-mode-{hostId}">
				<Select id="hc-mode-{hostId}" bind:value={config.graphics.mode} class="w-full">
					<option value="desktop">Desktop session</option>
					<option value="drm">Direct to screen (DRM)</option>
				</Select>
			</Field>

			{#if isDrm}
				<Field label="Connector" forId="hc-conn-{hostId}">
					<Select id="hc-conn-{hostId}" bind:value={config.graphics.drm_connector} class="w-full">
						<option value="">- choose an output -</option>
						{#each hardware?.drm_connectors ?? [] as c (c)}
							<option value={c}>{c}</option>
						{/each}
						{#if config.graphics.drm_connector && !(hardware?.drm_connectors ?? []).includes(config.graphics.drm_connector)}
							<option value={config.graphics.drm_connector}>
								{config.graphics.drm_connector} (not detected)
							</option>
						{/if}
					</Select>
				</Field>
			{:else}
				<Field label="Screen" forId="hc-screen-{hostId}">
					<Select
						id="hc-screen-{hostId}"
						value={String(config.graphics.screen)}
						onchange={(e) =>
							config && (config.graphics.screen = Number((e.target as HTMLSelectElement).value))}
						class="w-full"
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
				</Field>
			{/if}

			<Field label="Sound output" forId="hc-dev-{hostId}">
				<Select id="hc-dev-{hostId}" bind:value={config.audio.device} class="w-full">
					<option value="">Auto (mpv default)</option>
					{#each hardware?.audio_devices ?? [] as d (d.name)}
						<option value={d.name}>{d.description || d.name}</option>
					{/each}
					{#if config.audio.device && !(hardware?.audio_devices ?? []).some((d) => d.name === config?.audio.device)}
						<option value={config.audio.device}>{config.audio.device} (not detected)</option>
					{/if}
				</Select>
			</Field>
		</div>

		<div class="flex flex-col gap-2.5">
			<Toggle label="Fullscreen" bind:checked={config.graphics.fullscreen} />
			<Toggle
				label="Start the player when the host boots"
				bind:checked={config.autostart}
				hint="The box shows its ident on power-up, with or without Cinefin."
			/>
		</div>

		<div class="border-t border-border pt-3">
			<button
				type="button"
				class="flex items-center gap-1.5 text-xs font-medium text-muted hover:text-text"
				aria-expanded={showAdvanced}
				onclick={() => (showAdvanced = !showAdvanced)}
			>
				<ChevronRight size={13} class="transition-transform {showAdvanced ? 'rotate-90' : ''}" />
				Advanced picture &amp; sound
			</button>

			{#if showAdvanced}
				<div class="mt-4 space-y-5">
					<div>
						<p class="mb-2 text-xs font-medium text-muted">Picture</p>
						<div class="grid gap-x-6 gap-y-4 sm:grid-cols-2">
							{#if isDrm}
								<Field label="Pinned mode" forId="hc-drmmode-{hostId}">
									<Input
										id="hc-drmmode-{hostId}"
										bind:value={config.graphics.drm_mode}
										placeholder="e.g. 3840x2160@60 - blank to let the screen decide"
									/>
								</Field>
							{:else}
								<Field label="X display" forId="hc-display-{hostId}">
									<Input
										id="hc-display-{hostId}"
										bind:value={config.graphics.display}
										placeholder=":0"
									/>
								</Field>
							{/if}
							<Field label="Video output" forId="hc-vo-{hostId}">
								<Select id="hc-vo-{hostId}" bind:value={config.graphics.vo} class="w-full">
									{#each hardware?.mpv?.vo ?? [config.graphics.vo] as v (v)}
										<option value={v}>{v}</option>
									{/each}
								</Select>
							</Field>
							<Field label="GPU API" forId="hc-api-{hostId}">
								<Select id="hc-api-{hostId}" bind:value={config.graphics.gpu_api} class="w-full">
									<option value="">Auto (mpv decides)</option>
									{#each hardware?.mpv?.gpu_apis ?? [] as a (a)}
										<option value={a}>{a}</option>
									{/each}
								</Select>
							</Field>
							<Field label="GPU context" forId="hc-ctx-{hostId}">
								<Select
									id="hc-ctx-{hostId}"
									bind:value={config.graphics.gpu_context}
									class="w-full"
								>
									{#each GPU_CONTEXTS as c (c)}
										<option value={c}>{c === '' ? 'Auto' : c}</option>
									{/each}
								</Select>
								{#snippet hintSnippet()}
									Vulkan on a direct-to-screen host wants <code>displayvk</code>.
								{/snippet}
							</Field>
							<Field label="Hardware decoding" forId="hc-hwdec-{hostId}">
								<Select id="hc-hwdec-{hostId}" bind:value={config.graphics.hwdec} class="w-full">
									{#each HWDEC as h (h)}
										<option value={h}>{h}</option>
									{/each}
								</Select>
							</Field>
						</div>
						<div class="mt-3 flex flex-wrap gap-x-6 gap-y-2">
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
							<Field label="Channels" forId="hc-ch-{hostId}">
								<Select id="hc-ch-{hostId}" bind:value={config.audio.channels} class="w-full">
									{#each CHANNELS as c (c)}
										<option value={c}>{c}</option>
									{/each}
								</Select>
							</Field>
							<Field
								label="Maximum volume"
								forId="hc-vol-{hostId}"
								hint="Percent. mpv's volume-max."
							>
								<Input
									id="hc-vol-{hostId}"
									type="number"
									value={String(config.audio.max_volume)}
									oninput={(e) =>
										config &&
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

		<div class="flex flex-wrap items-center gap-2 border-t border-border pt-3">
			<Button variant="primary" disabled={saving} onclick={() => void save(false)}>
				<Save size={13} /> Save
			</Button>
			<Button disabled={saving} onclick={() => void save(true)}>
				<RefreshCw size={13} /> Save and restart the player
			</Button>
			{#if restartPending}
				<span class="flex items-center gap-1.5 text-xs text-warning">
					<AlertTriangle size={13} /> Saved - takes effect when the player restarts.
				</span>
			{/if}
		</div>
	</div>
{/if}
