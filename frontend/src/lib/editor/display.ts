import type { EditorBlock, EditorContext } from './types';
import {
	programmeBlockError,
	programmeBlockSummary,
	programmeBlockTitle
} from './programme-adapter';
import { templateBlockError, templateBlockSummary, templateBlockTitle } from './template-adapter';

export function blockTitle(block: EditorBlock, ctx: EditorContext): string {
	return ctx.mode === 'programme' ? programmeBlockTitle(block) : templateBlockTitle(block);
}

export function blockSummary(block: EditorBlock, ctx: EditorContext): string {
	return ctx.mode === 'programme'
		? programmeBlockSummary(block, ctx)
		: templateBlockSummary(block, ctx);
}

export function blockError(block: EditorBlock, ctx: EditorContext): string | null {
	return ctx.mode === 'programme' ? programmeBlockError(block) : templateBlockError(block);
}
