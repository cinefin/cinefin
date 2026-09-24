// Payload types for the Settings page where the generated OpenAPI types are loose
// (untyped dict fields / responses without schemas) — mirrored from the backend, never guessed.

export interface TicketElement {
	type: string;
	align?: string;
	size?: string | number;
	bold?: boolean;
	invert?: boolean;
	content?: string;
	scale?: string;
	mode?: string;
	lines?: number;
	/** image elements: 'file' prints a library image (`file`), unset prints the logo. */
	source?: string;
	file?: string;
	[key: string]: unknown;
}

export interface TicketDesignMeta {
	element_types: string[];
	tokens: string[];
	alignments: string[];
	sizes: string[];
	rating_scales: string[];
}

export interface TicketOpStyle {
	align?: string;
	size?: string;
	bold?: boolean;
	invert?: boolean;
}
export type TicketPreviewOp =
	| ({ type: 'text'; value: string } & TicketOpStyle)
	| ({
			type: 'image';
			kind: string;
			width_px: number;
			height_px: number;
			url: string;
	  } & TicketOpStyle)
	| ({ type: 'qr'; url: string; size: number } & TicketOpStyle)
	| ({ type: 'barcode'; value: string } & TicketOpStyle);

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
		idle_media: string;
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
