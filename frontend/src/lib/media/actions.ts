import { toApiError } from '$lib/api/client';
import { showToast, toastFailure } from '$lib/toast.svelte';

/** Run a user action; on failure toast "<prefix>: <reason>". Resolves with its result, or
 *  undefined when it failed. */
export async function act<T>(prefix: string, fn: () => Promise<T>): Promise<T | undefined> {
	try {
		return await fn();
	} catch (e) {
		toastFailure(prefix, e);
	}
}

/** As act(), but toasts the API's own message (else `fallback`) on failure. */
export async function actMsg<T>(fallback: string, fn: () => Promise<T>): Promise<T | undefined> {
	try {
		return await fn();
	} catch (e) {
		showToast(toApiError(e).message || fallback, 'error');
	}
}
