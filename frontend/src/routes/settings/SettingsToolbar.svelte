<script lang="ts">
	// The Settings page's sections as a toolbar: an icon over each name, the current one marked.
	import { base } from '$app/paths';
	import { SETTINGS_SECTIONS, type SettingsSection } from '$lib/settings/sections';

	let { current }: { current: SettingsSection } = $props();
</script>

<nav
	aria-label="Settings sections"
	class="-mx-4 -mt-4 mb-6 flex gap-1 overflow-x-auto border-b border-border bg-surface-1/60 px-3 py-2
		md:-mx-6 md:-mt-6 md:px-5"
>
	{#each SETTINGS_SECTIONS as s (s.id)}
		{@const on = s.id === current}
		<a
			href="{base}/settings?tab={s.id}"
			data-sveltekit-replacestate
			data-sveltekit-noscroll
			aria-current={on ? 'page' : undefined}
			class="flex h-[4.5rem] w-24 shrink-0 flex-col items-center justify-center gap-1.5 rounded-[3px]
				text-xs font-medium transition-colors
				{on
				? 'bg-surface-2 text-text shadow-[inset_0_-2px_0_var(--color-accent)]'
				: 'text-muted hover:bg-surface-2/60 hover:text-text'}"
		>
			<s.icon size={20} strokeWidth={1.7} class={on ? 'text-accent' : ''} />
			{s.label}
		</a>
	{/each}
</nav>
