/**
 * Multipart upload with progress events — a thin XHR wrapper, since openapi-fetch has no
 * upload-progress hook. Same request conventions as $lib/api/client.ts (same-origin credentials,
 * X-CSRFToken, X-Requested-With); resolves the unwrapped `data` payload or throws an ApiError.
 */
import { ApiError, getCsrfToken, type ErrorEnvelope } from '$lib/api/client';

export interface UploadProgressEvent {
	/** 0–100 (upload transfer only; server processing follows at 100). */
	percent: number;
	loaded: number;
	total: number;
}

export function uploadWithProgress<T>(
	url: string,
	file: File,
	fields: Record<string, string> = {},
	onProgress?: (e: UploadProgressEvent) => void,
	fieldName = 'file'
): Promise<T> {
	const formData = new FormData();
	formData.append(fieldName, file);
	for (const [key, value] of Object.entries(fields)) formData.append(key, value);

	return new Promise<T>((resolve, reject) => {
		const xhr = new XMLHttpRequest();

		xhr.upload.addEventListener('progress', (event) => {
			if (event.lengthComputable && onProgress) {
				onProgress({
					percent: (event.loaded / event.total) * 100,
					loaded: event.loaded,
					total: event.total
				});
			}
		});

		xhr.addEventListener('load', () => {
			if (xhr.status >= 200 && xhr.status < 300) {
				try {
					const body = JSON.parse(xhr.responseText) as { data?: T };
					resolve((body.data ?? (body as unknown)) as T);
				} catch {
					reject(new ApiError('Unexpected server response', xhr.status));
				}
				return;
			}
			let message = `Upload failed (${xhr.status || 'network'})`;
			let errorCode: string | null = null;
			try {
				const env = JSON.parse(xhr.responseText) as ErrorEnvelope;
				message = env.error || env.message || message;
				errorCode = env.error_code ?? null;
			} catch {
				/* non-JSON body — keep the generic message */
			}
			reject(new ApiError(message, xhr.status, errorCode));
		});

		xhr.addEventListener('error', () => reject(new ApiError('Upload failed', 0)));
		xhr.addEventListener('abort', () => reject(new ApiError('Upload cancelled', 0)));

		xhr.open('POST', url);
		xhr.withCredentials = false; // same-origin: cookies ride along by default
		xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
		const token = getCsrfToken();
		if (token) xhr.setRequestHeader('X-CSRFToken', token);
		xhr.send(formData);
	});
}
