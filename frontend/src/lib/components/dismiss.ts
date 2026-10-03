import type { Attachment } from 'svelte/attachments';

/** `{@attach dismiss(close)}` on a popover's root: an outside click or Escape calls `close`. */
export function dismiss(close: () => void): Attachment<HTMLElement> {
	return (node) => {
		const onClick = (e: MouseEvent) => {
			if (!node.contains(e.target as Node)) close();
		};
		const onKeydown = (e: KeyboardEvent) => {
			if (e.key === 'Escape') close();
		};
		window.addEventListener('click', onClick);
		window.addEventListener('keydown', onKeydown);
		return () => {
			window.removeEventListener('click', onClick);
			window.removeEventListener('keydown', onKeydown);
		};
	};
}
