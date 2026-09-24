/** Toast store — the SPA's transient action-feedback surface; rendered by <Toasts />. */

export type ToastKind = 'success' | 'error' | 'info' | 'warning';

export interface Toast {
	id: number;
	message: string;
	kind: ToastKind;
}

const DEFAULT_MS = 4500;

class ToastStore {
	list = $state<Toast[]>([]);
	#next = 1;

	show(message: string, kind: ToastKind = 'info', ms = DEFAULT_MS): void {
		const id = this.#next++;
		this.list = [...this.list, { id, message, kind }];
		setTimeout(() => this.dismiss(id), ms);
	}

	dismiss(id: number): void {
		this.list = this.list.filter((t) => t.id !== id);
	}
}

export const toasts = new ToastStore();

export function showToast(message: string, kind: ToastKind = 'info'): void {
	toasts.show(message, kind);
}
