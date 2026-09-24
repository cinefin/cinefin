/** Transient feedback for user-initiated actions; rendered with <ActionNotice>. */
export interface Notice {
	kind: 'success' | 'error';
	text: string;
}

export class NoticeState {
	current = $state<Notice | null>(null);

	#timer: ReturnType<typeof setTimeout> | undefined;

	show(kind: Notice['kind'], text: string, dismissAfterMs = 5000): void {
		clearTimeout(this.#timer);
		this.current = { kind, text };
		this.#timer = setTimeout(() => (this.current = null), dismissAfterMs);
	}

	dismiss(): void {
		clearTimeout(this.#timer);
		this.current = null;
	}
}
