// The two node built-ins the unit tests (`npm run test:unit`, node --test) use, typed just
// enough for svelte-check: the app ships no @types/node.
declare module 'node:test' {
	export function test(name: string, fn: () => void | Promise<void>): void;
}
declare module 'node:assert/strict' {
	const assert: {
		equal(actual: unknown, expected: unknown, message?: string): void;
		deepEqual(actual: unknown, expected: unknown, message?: string): void;
	};
	export default assert;
}
