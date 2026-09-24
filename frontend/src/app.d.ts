// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		/** Shallow-routing state. `movie`: the film open in the library drawer
		 *  (null = closed; absent = an entry the library page never touched). */
		interface PageState {
			movie?: number | null;
			/** A SidePanel pushed this entry: Back closes the drawer. */
			sidePanel?: boolean;
		}
		// interface Platform {}
	}
}

export {};
