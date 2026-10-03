/** A player's launch config (screen and sound), through the per-host proxies. */
import { api, unwrap } from '$lib/api/client';
import { mutate } from '$lib/api/mutate';
import type { components } from '$lib/api/types.gen';

export type Hardware = components['schemas']['HostHardwareSchema'];
type WireConfig = components['schemas']['HostLaunchConfigSchema'];
// The wire schema has graphics/audio optional; normalised so a form has every field.
export type LaunchConfig = Required<WireConfig> & {
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
			display_mode: g.display_mode ?? '',
			keep_awake: g.keep_awake ?? true,
			tunneling: g.tunneling ?? false
		},
		audio: {
			device: a.device ?? '',
			channels: a.channels ?? 'auto',
			spdif_passthrough: a.spdif_passthrough ?? [],
			max_volume: a.max_volume ?? 130
		}
	};
}

/** The host's launch config, and its real device lists (null when it cannot list them). */
export async function loadHostConfig(
	hostId: number
): Promise<{ config: LaunchConfig; hardware: Hardware | null }> {
	const params = { params: { path: { host_id: hostId } } };
	const config = normalise(await unwrap(api.GET('/api/v2/playout/hosts/{host_id}/config', params)));
	// Garnish: without it the selects fall back to the values already set.
	const hardware = await unwrap(api.GET('/api/v2/playout/hosts/{host_id}/hardware', params)).catch(
		() => null
	);
	return { config, hardware };
}

/**
 * Save the host's launch config, restarting its mpv when `restart` is set and
 * the change needs it. Returns whether a restart is still needed.
 */
export async function saveHostConfig(
	hostId: number,
	config: LaunchConfig,
	restart: boolean
): Promise<boolean> {
	const params = { params: { path: { host_id: hostId } } };
	const saved = await unwrap(
		api.PUT('/api/v2/playout/hosts/{host_id}/config', { ...params, body: config })
	);
	if (!saved.restart_required) return false;
	if (!restart) return true;
	await mutate(api.POST('/api/v2/playout/hosts/{host_id}/restart', params));
	return false;
}

/** mpv can list one device name twice (two profiles of the same HDMI sink): keep the first. */
export function audioDevices(hardware: Hardware | null) {
	const seen = new Set<string>();
	return (hardware?.audio_devices ?? []).filter((d) => !seen.has(d.name) && !!seen.add(d.name));
}

/** An Android TV player: one screen and one sound output, the box's HDMI. */
export const isAndroid = (config: LaunchConfig) => config.graphics.mode === 'android';

/** A display mode as the Android player takes it, "3840x2160@23.976". */
function modeValue(w: number, h: number, hz: number) {
	return `${w}x${h}@${Math.round(hz * 1000) / 1000}`;
}

/** A display mode as people read it, "3840×2160 · 23.976 Hz". */
export function modeLabel(value: string) {
	const m = /^(\d+)x(\d+)@([\d.]+)$/.exec(value);
	return m ? `${m[1]}×${m[2]} · ${m[3]} Hz` : value;
}

/** The modes an Android player's display offers, largest first, as display_mode values. */
export function displayModes(hardware: Hardware | null) {
	const modes = [...(hardware?.android?.modes ?? [])].sort(
		(a, b) => (b.w ?? 0) - (a.w ?? 0) || (a.hz ?? 0) - (b.hz ?? 0)
	);
	return [...new Set(modes.map((m) => modeValue(m.w ?? 0, m.h ?? 0, m.hz ?? 0)))];
}

/** What an Android player's display runs at now, e.g. "3840×2160 · 59.94 Hz". */
export function currentMode(hardware: Hardware | null) {
	const s = hardware?.screens?.[0];
	return s?.w ? modeLabel(modeValue(s.w, s.h ?? 0, s.hz ?? 0)) : '';
}

/** One line each for the screen and the sound, as a summary. */
export function describeConfig(config: LaunchConfig, hardware: Hardware | null) {
	const g = config.graphics;
	if (isAndroid(config)) {
		const bitstream = config.audio.spdif_passthrough.length > 0;
		const own = ["HDMI, the box's own mode", currentMode(hardware)].filter(Boolean).join(' · ');
		return {
			screen: g.display_mode ? `HDMI at ${modeLabel(g.display_mode)}` : own,
			sound: `HDMI, ${bitstream ? 'bitstream to the receiver' : 'decoded on the box'}`
		};
	}
	let screen: string;
	if (g.mode === 'drm') {
		screen = g.drm_connector || 'The first connected screen';
		if (g.drm_mode) screen += ` at ${g.drm_mode}`;
	} else {
		const s = hardware?.screens?.find((x) => x.index === g.screen);
		screen = [`Screen ${g.screen}`, s?.name, s?.w ? `${s.w}×${s.h}` : '']
			.filter(Boolean)
			.join(' · ');
	}
	if (g.fullscreen) screen += ', fullscreen';
	const device = audioDevices(hardware).find((d) => d.name === config.audio.device);
	let sound = config.audio.device ? device?.description || config.audio.device : 'Auto';
	if (config.audio.channels !== 'auto') sound += `, ${config.audio.channels}`;
	return { screen, sound };
}
