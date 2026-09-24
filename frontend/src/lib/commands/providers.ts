// Command providers are data from GET /commands/providers (built-ins + contrib plugins, see
// cinefin/plugins.py) — this module turns their field schemas into form state and back.
import {
	Bell,
	Blinds,
	Fan,
	Globe,
	House,
	Lightbulb,
	Music,
	Plug,
	Power,
	Projector,
	Radio,
	Speaker,
	SquareTerminal,
	Tv,
	Wifi,
	Zap
} from '@lucide/svelte';
import type { Component } from 'svelte';
import type { IconProps } from '@lucide/svelte';
import type { components } from '$lib/api/types.gen';

export type ProviderInfo = components['schemas']['ProviderSchema'];
export type ProviderField = components['schemas']['ProviderFieldSchema'];
export type Suggestion = components['schemas']['SuggestionSchema'];
/** Every field edits as a string; booleans as 'true' / ''. */
export type FormValues = Record<string, string>;

/** The icon names a provider may declare (`CommandProvider.icon`); anything else renders as Zap. */
const ICONS: Record<string, Component<IconProps>> = {
	bell: Bell,
	blinds: Blinds,
	fan: Fan,
	globe: Globe,
	house: House,
	lightbulb: Lightbulb,
	music: Music,
	plug: Plug,
	power: Power,
	projector: Projector,
	radio: Radio,
	speaker: Speaker,
	terminal: SquareTerminal,
	tv: Tv,
	wifi: Wifi,
	zap: Zap
};

export function providerIcon(name: string | null | undefined): Component<IconProps> {
	return (name && ICONS[name]) || Zap;
}

/** Stored config (or {} for a new command, which picks up field defaults) → editable strings. */
export function toFormValues(fields: ProviderField[], config: Record<string, unknown>): FormValues {
	const values: FormValues = {};
	for (const f of fields) {
		const v = config[f.key] ?? f.default;
		if (f.type === 'boolean') values[f.key] = v ? 'true' : '';
		else if (f.type === 'json')
			values[f.key] =
				v && typeof v === 'object' && Object.keys(v as object).length
					? JSON.stringify(v, null, 2)
					: '';
		else values[f.key] = v == null ? '' : String(v);
	}
	return values;
}

/** Editable strings → config, or the first problem to show the user. */
export function fromFormValues(
	fields: ProviderField[],
	values: FormValues
): { config: Record<string, unknown> } | { error: string } {
	const config: Record<string, unknown> = {};
	for (const f of fields) {
		const v = values[f.key];
		if (f.type === 'boolean') {
			config[f.key] = v === 'true';
			continue;
		}
		const text = f.type === 'secret' ? (v ?? '') : (v ?? '').trim();
		if (!text) {
			if (f.required) return { error: `${f.label} is required` };
			if (f.type === 'json') config[f.key] = {};
			continue;
		}
		if (f.type === 'json') {
			try {
				config[f.key] = JSON.parse(text);
			} catch {
				return { error: `${f.label} is not valid JSON` };
			}
		} else if (f.type === 'number') {
			const n = Number(text);
			if (Number.isNaN(n)) return { error: `${f.label} must be a number` };
			config[f.key] = n;
		} else config[f.key] = text;
	}
	return { config };
}

/** A field's autocomplete options, narrowed by its `scoped_by` field (all of them if none match). */
export function suggestionsFor(
	field: ProviderField,
	values: FormValues,
	suggestions: Record<string, Suggestion[]>
): Suggestion[] {
	const all = suggestions[field.key] ?? [];
	let list = all;
	const scope = field.scoped_by ? (values[field.scoped_by] ?? '').trim().toLowerCase() : '';
	if (scope) {
		const scoped = all.filter((s) => s.scope === scope);
		if (scoped.length) list = scoped;
	}
	const seen = new Set<string>();
	return list.filter((s) => !seen.has(s.value) && seen.add(s.value));
}
