/** The outcome of a settings check (connection tests, saves), shown by CheckResult. */
export type CheckState = {
	state: 'pending' | 'ok' | 'error' | 'warn';
	message: string;
} | null;
