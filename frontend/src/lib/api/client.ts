/**
 * The typed API client: openapi-fetch over the generated `paths` from types.gen.ts.
 * Same-origin credentials; X-CSRFToken sent on every unsafe method (ignored unless
 * security.auth_enabled is on, so sending unconditionally is always correct); X-Requested-With
 * marks API calls. baseUrl is '' because the schema's paths already carry the /api/v2 prefix.
 */
import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from './types.gen';

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE']);

/** Read Django's CSRF token from the csrftoken cookie. */
export function getCsrfToken(): string | null {
	const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
	return match ? decodeURIComponent(match[1]) : null;
}

const csrfMiddleware: Middleware = {
	onRequest({ request }) {
		request.headers.set('X-Requested-With', 'XMLHttpRequest');
		if (!SAFE_METHODS.has(request.method)) {
			const token = getCsrfToken();
			if (token) request.headers.set('X-CSRFToken', token);
		}
		return request;
	}
};

// Routes that must not bounce to /login on a 401: the login page, the first-run wizard (auth
// isn't live yet) and the kiosk wall (auth-exempt, can't log in). Matched against the SPA path.
const NO_AUTH_REDIRECT = ['/app/setup', '/app/kiosk', '/login'];
let redirectingToLogin = false;

/** On a 401 (expired/absent session while the auth gate is on), send the browser to /login with
 *  a ?next= back. Guarded against the exempt routes and against firing more than once. */
const authRedirectMiddleware: Middleware = {
	onResponse({ response }) {
		if (response.status === 401 && typeof window !== 'undefined' && !redirectingToLogin) {
			const path = window.location.pathname;
			if (!NO_AUTH_REDIRECT.some((p) => path.startsWith(p))) {
				redirectingToLogin = true;
				const next = encodeURIComponent(window.location.pathname + window.location.search);
				window.location.assign(`/login/?next=${next}`);
			}
		}
		return response;
	}
};

export const api = createClient<paths>({
	baseUrl: '',
	credentials: 'same-origin'
});
api.use(csrfMiddleware);
api.use(authRedirectMiddleware);

/** The API's error envelope (ErrorResponseSchema): { success: false, error, error_code, details }. */
export interface ErrorEnvelope {
	success?: boolean;
	error?: string;
	error_code?: string | null;
	message?: string | null;
	details?: Record<string, unknown> | null;
}

export class ApiError extends Error {
	status: number;
	errorCode: string | null;
	details: Record<string, unknown> | null;

	constructor(
		message: string,
		status: number,
		errorCode: string | null = null,
		details: Record<string, unknown> | null = null
	) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
		this.errorCode = errorCode;
		this.details = details;
	}
}

export function toApiError(error: unknown, response?: Response): ApiError {
	if (error instanceof ApiError) return error;
	const status = response?.status ?? 0;
	if (error && typeof error === 'object') {
		const env = error as ErrorEnvelope;
		return new ApiError(
			env.error || env.message || `Request failed (${status || 'network'})`,
			status,
			env.error_code ?? null,
			env.details ?? null
		);
	}
	if (error instanceof Error) return new ApiError(error.message, status);
	return new ApiError(`Request failed (${status || 'network'})`, status);
}

/**
 * Unwrap a successful `{ success, message, data }` envelope, or throw a typed ApiError. Every
 * list/detail endpoint returns this envelope, so pages get the typed payload directly.
 */
export async function unwrap<T>(
	pending: PromiseLike<{ data?: { data?: T }; error?: unknown; response: Response }>
): Promise<T> {
	const result = await pending;
	if (result.error !== undefined || !result.data) {
		throw toApiError(result.error, result.response);
	}
	return result.data.data as T;
}

/**
 * Typed fetch for the plain-Django JSON views outside the Ninja schema (e.g. /system/update-check).
 * Same credentials/CSRF as `api`. Not for /api/v2/ paths — those are typed, go through `api`.
 */
export async function fetchJson<T>(path: string, init: RequestInit = {}): Promise<T> {
	const headers = new Headers(init.headers);
	headers.set('X-Requested-With', 'XMLHttpRequest');
	const method = (init.method ?? 'GET').toUpperCase();
	if (!SAFE_METHODS.has(method)) {
		const token = getCsrfToken();
		if (token) headers.set('X-CSRFToken', token);
	}
	let response: Response;
	try {
		response = await fetch(path, { credentials: 'same-origin', ...init, headers });
	} catch (e) {
		throw toApiError(e);
	}
	if (!response.ok) throw new ApiError(`Request failed (${response.status})`, response.status);
	return (await response.json()) as T;
}
