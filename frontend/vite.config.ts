import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		// Dev convenience: `vite dev` proxies API + media calls to the Django
		// dev server, so the SPA at localhost:5173/app talks to real data.
		proxy: {
			'/api': 'http://localhost:8000',
			'/media': 'http://localhost:8000',
			'/stream': 'http://localhost:8000',
			// The title-card @font-face files are Django static assets.
			'/static': 'http://localhost:8000'
		}
	}
});
