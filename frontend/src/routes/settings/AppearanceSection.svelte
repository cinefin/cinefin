<script lang="ts">
	import { Image, Pipette, RotateCcw, Upload, X } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { uploadWithProgress } from '$lib/upload';
	import { showToast } from '$lib/toast.svelte';
	import { DEFAULT_ACCENT, type SettingsStore } from '$lib/settings/form.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Field from './Field.svelte';
	import { display } from '$lib/display.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	interface Props {
		store: SettingsStore;
		confirm: ConfirmDialog['confirm'];
	}
	let { store, confirm }: Props = $props();

	let logoInput: HTMLInputElement | undefined = $state();

	async function onLogoPicked() {
		const file = logoInput?.files?.[0];
		if (logoInput) logoInput.value = '';
		if (!file) return;
		try {
			const res = await uploadWithProgress<{ logo_url?: string | null }>(
				'/api/v2/settings/branding/logo',
				file,
				{},
				undefined,
				'logo'
			);
			store.webLogoUrl = res?.logo_url ?? null;
			showToast('Web logo uploaded', 'success');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to upload logo', 'error');
		}
	}

	async function removeLogo() {
		if (
			!(await confirm(
				'Remove the web logo? The login screen returns to the theater name / default mark.',
				{ confirmLabel: 'Remove' }
			))
		) {
			return;
		}
		try {
			await unwrap(api.DELETE('/api/v2/settings/branding/logo'));
			store.webLogoUrl = null;
			showToast('Web logo removed', 'success');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to remove logo', 'error');
		}
	}

	const SWATCHES: { color: string; label: string }[] = [
		{ color: DEFAULT_ACCENT, label: 'Cinefin blue (default)' },
		{ color: '#C0504D', label: 'Theater red' },
		{ color: '#C89B3C', label: 'Amber' },
		{ color: '#4C8C6A', label: 'Emerald' },
		{ color: '#3E8E9E', label: 'Teal' },
		{ color: '#8A6BB0', label: 'Violet' },
		{ color: '#B0607F', label: 'Rose' }
	];

	const customSelected = $derived(
		!SWATCHES.some((s) => s.color.toLowerCase() === store.main.accent_color.toLowerCase())
	);

	function pickSwatch(color: string) {
		store.main.accent_color = color;
		store.accentCleared = false;
	}

	function resetAccent() {
		store.accentCleared = true;
		store.main.accent_color = DEFAULT_ACCENT;
	}

	// Previews never write the boot cache; leaving the section settles it — a
	// saved value re-applies with caching, an abandoned edit reverts.
	$effect(() => {
		display.applyAccent(store.accentCleared ? null : store.main.accent_color, { cache: false });
	});
	$effect(() => {
		return () => {
			if (store.isDirty('accent_color')) display.restoreCachedAccent();
			else display.applyAccent(store.accentCleared ? null : store.main.accent_color);
		};
	});
</script>

<div class="space-y-4">
	<Card title="Web logo">
		<div class="flex flex-wrap items-center gap-4">
			<div
				class="flex h-16 w-40 items-center justify-center overflow-hidden rounded-md border border-border bg-surface-2"
			>
				{#if store.webLogoUrl}
					<img src={store.webLogoUrl} alt="Web logo" class="max-h-full max-w-full object-contain" />
				{:else}
					<Image size={22} class="text-faint" />
				{/if}
			</div>
			<div class="min-w-0 flex-1 space-y-2">
				<div class="flex flex-wrap items-center gap-2">
					<Button onclick={() => logoInput?.click()}><Upload size={14} /> Choose image</Button>
					{#if store.webLogoUrl}
						<Button variant="danger" onclick={removeLogo}><X size={14} /> Remove</Button>
					{/if}
				</div>
				<p class="text-xs text-faint">
					Shown on the login screen (the theater name is used if no logo is set). Uploads
					immediately. PNG, JPG or GIF, max 2 MB.
				</p>
			</div>
		</div>
		<input
			type="file"
			bind:this={logoInput}
			accept="image/png,image/jpeg,image/gif"
			hidden
			onchange={onLogoPicked}
		/>
	</Card>

	<Card title="Colours &amp; clock">
		<div class="space-y-5">
			<Field
				label="Accent colour"
				hint="Re-tints buttons, links and highlights across the app on every device. Saved with the other settings."
				dirty={store.isDirty('accent_color')}
				error={store.errorFor('accent_color')}
			>
				<div class="flex flex-wrap items-center gap-2">
					{#each SWATCHES as sw (sw.color)}
						<button
							type="button"
							class="h-8 w-8 rounded-md border-2 transition-[filter] hover:brightness-110
								{(
								sw.color === DEFAULT_ACCENT
									? store.accentCleared
									: !store.accentCleared &&
										store.main.accent_color.toLowerCase() === sw.color.toLowerCase()
							)
								? 'border-text'
								: 'border-transparent'}"
							style="background: {sw.color}"
							title={sw.label}
							aria-label={sw.label}
							onclick={() => (sw.color === DEFAULT_ACCENT ? resetAccent() : pickSwatch(sw.color))}
						></button>
					{/each}
					<label
						class="relative flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border-2 bg-surface-2
							{!store.accentCleared && customSelected ? 'border-text' : 'border-border-strong'}"
						title="Custom colour"
						aria-label="Custom colour"
					>
						<input
							type="color"
							class="absolute inset-0 h-full w-full cursor-pointer opacity-0"
							value={store.main.accent_color}
							oninput={(e) => pickSwatch((e.currentTarget as HTMLInputElement).value)}
						/>
						<Pipette size={14} class="pointer-events-none text-muted" />
					</label>
					<Button size="sm" onclick={resetAccent}><RotateCcw size={13} /> Default</Button>
				</div>
			</Field>

			<Field
				label="Clock format"
				forId="set-display-time-format"
				hint="Applies to showtimes and clocks across the web UI. Tickets have their own format setting."
				dirty={store.isDirty('display_time_format')}
				error={store.errorFor('display_time_format')}
			>
				<Select
					id="set-display-time-format"
					bind:value={store.main.display_time_format}
					class="max-w-sm"
				>
					<option value="24h">24-hour (19:30)</option>
					<option value="12h">12-hour (7:30 PM)</option>
				</Select>
			</Field>
		</div>
	</Card>
</div>
