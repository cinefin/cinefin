import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// SPA mode: no prerendered pages (ssr=false in the root layout), every
		// unknown /app/* path falls back to index.html and the client router
		// takes over. Django serves the build — see cinefin/views.py spa_view.
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: 'index.html',
			precompress: false,
			strict: true
		}),
		paths: {
			// The SPA mounts at /app/ next to the legacy server-rendered UI.
			base: '/app',
			// Absolute asset URLs (/app/_app/…) — the fallback index.html is
			// served for arbitrarily deep paths, so relative URLs would break.
			relative: false
		}
	}
};

export default config;
