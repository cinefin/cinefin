/**
 * mutate() — unwrap for action endpoints returning a bare message envelope ({ success, message })
 * instead of the { data } payload. Resolves with the server's message or throws a typed ApiError.
 */
import { toApiError } from './client';

export async function mutate(
	pending: PromiseLike<{ data?: { message?: string | null }; error?: unknown; response: Response }>
): Promise<string | undefined> {
	const result = await pending;
	if (result.error !== undefined || !result.data) {
		throw toApiError(result.error, result.response);
	}
	return result.data.message ?? undefined;
}
