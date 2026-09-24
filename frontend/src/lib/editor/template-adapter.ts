// Trailer rules keep count in `count` and toggles in `match_genres`/`match_certification`/`match_year`;
// the wire's `trailer_count`/`match_genre` naming is restored on save.
import type { components } from '$lib/api/types.gen';
import type { BlockContent, EditorBlock, EditorContext, PaletteEntry } from './types';
import { HELP, commandSummary } from './types';

export type TemplateItemIn = components['schemas']['TemplateItemSchema'];

export const TEMPLATE_PALETTE: PaletteEntry[] = [
	{ type: 'feature', desc: 'Main movie slot' },
	{ type: 'trailer_rule', desc: 'Auto-select trailers', help: HELP.trailer_rule },
	{ type: 'trailer', desc: 'A specific trailer' },
	{ type: 'bumper', desc: 'A clip or a random pick from a tag' },
	{ type: 'audio_bumper', desc: 'Matches a feature’s audio format' },
	{ type: 'command', desc: 'A system action' },
	{ type: 'certification', desc: 'Rating card' }
];

export function defaultTemplateContent(type: string): BlockContent {
	switch (type) {
		case 'feature':
			return { feature_number: null, credits_command_id: null };
		case 'trailer_rule':
			return {
				bound_to_feature: null,
				count: 3,
				match_genres: true,
				match_certification: true,
				match_year: false,
				year_delta: 5,
				trailer_tag_id: null
			};
		case 'command':
			return { command_id: null, name: null, hold_black: false };
		case 'bumper':
			return { bumper_id: null, title: null, tag_id: null, tag_name: null, count: 1 };
		case 'trailer':
			return { trailer_id: null, title: null };
		case 'certification':
			return { certification_feature: null };
		case 'audio_bumper':
			return { bound_to_feature: null };
		default:
			return {};
	}
}

export function templateItemsToBlocks(items: TemplateItemIn[], uid: () => string): EditorBlock[] {
	return items.map((item, index) => ({
		uid: uid(),
		type: item.item_type,
		order: item.order ?? index,
		content: {
			feature_number: item.feature_number ?? null,
			credits_command_id: item.credits_command?.id ?? null,
			bound_to_feature: item.bound_to_feature ?? null,
			count: item.item_type === 'trailer_rule' ? (item.trailer_count ?? 3) : (item.count ?? 1),
			match_genres: item.match_genre ?? true,
			match_certification: item.match_certification ?? true,
			match_year: item.match_year ?? false,
			year_delta: item.year_delta ?? 5,
			trailer_tag_id: item.trailer_tag?.id ?? null,
			certification_feature: item.certification_feature ?? null,
			command_id: item.command?.id ?? null,
			name: item.command?.name ?? null,
			hold_black: item.hold_black ?? false,
			bumper_id: item.bumper?.id ?? null,
			trailer_id: item.trailer?.id ?? null,
			title: item.bumper?.title ?? item.trailer?.title ?? null,
			tag_id: item.tag?.id ?? null,
			tag_name: item.tag?.name ?? null
		},
		details: {
			duration: item.bumper?.duration ?? null,
			year: item.trailer?.year ?? null,
			content_rating: item.trailer?.content_rating ?? null
		}
	}));
}

export function templateBlockError(block: EditorBlock): string | null {
	switch (block.type) {
		case 'feature':
			return block.content.feature_number ? null : 'Assign a feature number';
		case 'trailer_rule':
			return block.content.bound_to_feature ? null : 'Choose which feature these trail';
		case 'command':
			return block.content.command_id ? null : 'Choose a command';
		case 'bumper':
			if (block.content.tag_id) return null;
			return block.content.bumper_id ? null : 'Choose a clip or a tag';
		case 'trailer':
			return block.content.trailer_id ? null : 'Choose a trailer';
		case 'audio_bumper':
			return block.content.bound_to_feature ? null : 'Choose which feature';
		case 'certification':
			return block.content.certification_feature ? null : 'Choose which feature to rate';
		default:
			return null;
	}
}

export function templateBlockTitle(block: EditorBlock): string {
	const c = block.content;
	switch (block.type) {
		case 'feature':
			return `Feature ${c.feature_number || '?'}`;
		case 'trailer_rule':
			return `${c.count || 3} Trailers for Feature ${c.bound_to_feature || '?'}`;
		case 'command':
			return c.name || 'Select command';
		case 'bumper':
			if (c.tag_id || c.tag_name) {
				const countText = (c.count ?? 1) > 1 ? ` (${c.count}x)` : '';
				return `Random user media${c.tag_name ? `: ${c.tag_name}` : ''}${countText}`;
			}
			return c.title || 'Select user media';
		case 'trailer':
			return c.title || 'Select trailer';
		case 'certification':
			return `Certification for Feature ${c.certification_feature || '?'}`;
		case 'audio_bumper':
			return `Audio user media for Feature ${c.bound_to_feature || '?'}`;
		default:
			return 'Unknown item';
	}
}

export function templateBlockSummary(block: EditorBlock, ctx: EditorContext): string {
	const c = block.content;
	const d = block.details;
	switch (block.type) {
		case 'feature':
			return 'Main movie content';
		case 'trailer_rule': {
			const filters: string[] = [];
			if (c.match_genres) filters.push('Genre');
			if (c.match_certification) filters.push('Rating');
			if (c.match_year) filters.push(`Year ±${c.year_delta || 5}`);
			const tag = ctx.trailerTags.find((t) => t.id === c.trailer_tag_id);
			const tagSuffix = tag ? ` · Tag: ${tag.name}` : '';
			return (filters.length ? `Match: ${filters.join(', ')}` : 'No filters applied') + tagSuffix;
		}
		case 'command': {
			if (!c.command_id) return 'No command selected';
			const cmd = ctx.commands.find((x) => x.id === c.command_id);
			return commandSummary(cmd, !!c.hold_black);
		}
		case 'bumper':
			if (c.tag_id || c.tag_name)
				return c.tag_name ? `Random selection from ${c.tag_name} tag` : 'Random selection from tag';
			return c.bumper_id ? 'Specific media file' : 'No user media selected';
		case 'trailer': {
			if (!c.trailer_id) return 'No trailer selected';
			const parts: string[] = [];
			if (d.year) parts.push(String(d.year));
			if (d.content_rating) parts.push(d.content_rating);
			return parts.length ? parts.join(' · ') : 'Specific trailer';
		}
		case 'certification':
			return 'Auto-selected based on movie rating';
		case 'audio_bumper':
			return c.bound_to_feature
				? `Matches Feature ${c.bound_to_feature}'s audio format`
				: 'Choose which feature this intro matches';
		default:
			return 'Unknown item type';
	}
}

export function blocksToTemplateItems(blocks: EditorBlock[]): Record<string, unknown>[] {
	return blocks.map((block) => {
		const c = block.content;
		const item: Record<string, unknown> = {
			item_type: block.type,
			order: block.order,
			feature_number: c.feature_number ?? null,
			bound_to_feature: c.bound_to_feature ?? null,
			trailer_count: block.type === 'trailer_rule' ? (c.count ?? 3) : 3,
			match_genre: c.match_genres ?? true,
			match_certification: c.match_certification ?? true,
			match_year: c.match_year ?? false,
			year_delta: c.year_delta ?? 5,
			certification_feature: c.certification_feature ?? null,
			count: (block.type === 'trailer_rule' ? 1 : c.count) || 1,
			hold_black: !!c.hold_black
		};
		if (c.command_id) item.command_id = c.command_id;
		if (c.bumper_id) item.bumper_id = c.bumper_id;
		if (c.trailer_id) item.trailer_id = c.trailer_id;
		if (c.tag_id) item.tag_id = c.tag_id;
		if (c.trailer_tag_id) item.trailer_tag_id = c.trailer_tag_id;
		if (c.credits_command_id) item.credits_command_id = c.credits_command_id;
		return item;
	});
}
