// Payload types for the Settings page where the generated OpenAPI types are loose
// (untyped dict fields / responses without schemas) — mirrored from the backend, never guessed.

/** GET /playout/host/config data (HostConfigResponse.data is an untyped dict). */
export interface HostConfig {
	graphics: {
		mode: string;
		vo: string;
		gpu_api: string;
		gpu_context: string;
		hwdec: string;
		screen: number;
		drm_connector: string;
		drm_mode: string;
		fullscreen: boolean;
		hdr_passthrough: boolean;
		osc: boolean;
		display: string;
		[extra: string]: unknown;
	};
	audio: {
		device: string;
		channels: string;
		spdif_passthrough: string[];
		max_volume: number;
		[extra: string]: unknown;
	};
	[extra: string]: unknown;
}

/** The trailers.* settings namespace (GET/POST /trailers/settings are untyped). */
export interface TrailerSettingsPayload {
	tmdb_api_key?: string | null;
	download_quality?: string;
	rating_lookup_enabled?: boolean;
	upcoming_months_ahead?: number;
	filename_template?: string | null;
	folder_template?: string | null;
	[extra: string]: unknown;
}

export interface TrailerSettingsData {
	settings: TrailerSettingsPayload;
	naming_tokens: { token: string; description: string }[];
	dependencies?: Record<string, boolean>;
	supported_qualities?: string[];
}

export type CheckState = {
	state: 'pending' | 'ok' | 'error' | 'warn';
	message: string;
} | null;
