/** Per-device display preferences (localStorage) + the runtime accent colour (a server setting). */

const DENSITY_KEY = 'cpx-display-density';
const THEME_KEY = 'cpx-display-theme';
const ACCENT_CACHE_KEY = 'cpx-accent-cache';
const RAIL_KEY = 'cpx-display-nav-rail';

export type Density = '100' | '90' | '80';
export type Theme = 'dark' | 'dim' | 'light';

export const THEMES: { value: Theme; label: string }[] = [
	{ value: 'dark', label: 'Dark' },
	{ value: 'dim', label: 'Dim' },
	{ value: 'light', label: 'Light' }
];
export const DENSITIES: { value: Density; label: string }[] = [
	{ value: '100', label: '100%' },
	{ value: '90', label: '90%' },
	{ value: '80', label: '80%' }
];

function read(key: string): string | null {
	try {
		return localStorage.getItem(key);
	} catch {
		return null;
	}
}

function write(key: string, value: string | null) {
	try {
		if (value === null) localStorage.removeItem(key);
		else localStorage.setItem(key, value);
	} catch {
		/* private mode etc — prefs just don't persist */
	}
}

const ACCENT_RE = /^#[0-9a-fA-F]{6}$/;

class DisplayStore {
	density = $state<Density>(
		(['90', '80'].find((d) => d === read(DENSITY_KEY)) as Density) ?? '100'
	);
	theme = $state<Theme>((['dim', 'light'].find((t) => t === read(THEME_KEY)) as Theme) ?? 'dark');
	rail = $state(read(RAIL_KEY) === '1');

	setDensity(density: Density) {
		this.density = density;
		write(DENSITY_KEY, density);
		this.apply();
	}

	toggleRail() {
		this.rail = !this.rail;
		write(RAIL_KEY, this.rail ? '1' : null);
	}

	setTheme(theme: Theme) {
		this.theme = theme;
		write(THEME_KEY, theme);
		this.apply();
	}

	apply() {
		const el = document.documentElement;
		el.classList.remove('density-90', 'density-80');
		if (this.density !== '100') el.classList.add(`density-${this.density}`);
		el.classList.remove('theme-dim', 'theme-light');
		if (this.theme !== 'dark') el.classList.add(`theme-${this.theme}`);
	}

	/** Apply the server accent (or clear to default). `cache: false` (previews) so an
	 *  abandoned pick never pollutes the boot colour. */
	applyAccent(color: string | null | undefined, { cache = true } = {}) {
		const el = document.documentElement;
		if (color && ACCENT_RE.test(color)) {
			el.style.setProperty('--color-accent', color);
			if (cache) write(ACCENT_CACHE_KEY, color);
		} else {
			el.style.removeProperty('--color-accent');
			if (cache) write(ACCENT_CACHE_KEY, null);
		}
	}

	restoreCachedAccent() {
		this.applyAccent(read(ACCENT_CACHE_KEY), { cache: false });
	}

	boot() {
		this.apply();
		const cached = read(ACCENT_CACHE_KEY);
		if (cached && ACCENT_RE.test(cached)) {
			document.documentElement.style.setProperty('--color-accent', cached);
		}
	}
}

export const display = new DisplayStore();
