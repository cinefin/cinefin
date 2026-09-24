// Framework-agnostic title-template canvas drawing/interaction engine.

// Stored verbatim as JSON by the backend (free-form dict), so per-type fields are all optional.
export interface TTElement {
	type: string;
	x: number;
	y: number;
	width?: number;
	height?: number;
	opacity?: number;
	feature_index?: number;
	field?: string;
	font?: string;
	size?: number;
	color?: string;
	align?: string;
	max_width?: number | null;
	fill?: boolean;
	border_width?: number;
	path?: string;
	lock_aspect?: boolean;
	/** Transient editor-only flag: resize to the image's natural size on next load. */
	_autoResize?: boolean;
}

export interface TTTemplateConfig {
	canvas: { width: number; height: number };
	elements: TTElement[];
}

export interface TTBounds {
	x: number;
	y: number;
	width: number;
	height: number;
}

export interface TTFeature {
	title: string;
	director: string;
	year: string;
	certification: string;
	runtime: string;
	poster: string;
}

export interface TTPreviewData {
	programme_name: string;
	features: TTFeature[];
}

interface TTGuide {
	axis: 'v' | 'h';
	pos: number;
}

interface TTMarquee {
	x0: number;
	y0: number;
	x1: number;
	y1: number;
	additive: boolean;
}

type TTResizeHandle = 'nw' | 'ne' | 'sw' | 'se';

export type TTAlignMode = 'left' | 'centerH' | 'right' | 'top' | 'middle' | 'bottom';

export interface EditorHost {
	onChange(): void;
	/** markDirty fired — hide a stale server-rendered preview. */
	onEdited(): void;
	onContextMenu(clientX: number, clientY: number, hit: number): void;
}

export function emptyTemplateConfig(): TTTemplateConfig {
	return {
		canvas: { width: 1920, height: 1080 },
		elements: []
	};
}

export class TitleCanvasEditor {
	config: TTTemplateConfig;
	selectedElementIndex: number | null;
	selectedIndices: number[];
	isMarquee: boolean;
	marquee: TTMarquee | null;
	marqueeMoved: boolean;
	dragStartPositions: Array<{ el: TTElement; x: number; y: number }>;
	alignAreaMode: 'selection' | 'canvas';
	zoom: number;
	canvas: HTMLCanvasElement;
	ctx: CanvasRenderingContext2D;
	isDragging: boolean;
	isResizing: boolean;
	dragStartPos: { x: number; y: number };
	elementStartPos: { x: number; y: number };
	elementStartSize: { width: number; height: number };
	resizeHandle: TTResizeHandle | null;
	aspectRatio: number;
	imageCache: Record<string, HTMLImageElement>;
	previewData: TTPreviewData | null;
	undoStack: string[];
	redoStack: string[];
	isDirty: boolean;
	activeGuides: TTGuide[];

	#host: EditorHost;
	#listeners: Array<[keyof HTMLElementEventMap, (e: Event) => void]> = [];

	constructor(canvas: HTMLCanvasElement, host: EditorHost) {
		this.config = emptyTemplateConfig();
		this.#host = host;

		this.selectedElementIndex = null;
		this.selectedIndices = [];
		this.isMarquee = false;
		this.marquee = null;
		this.marqueeMoved = false;
		this.dragStartPositions = [];
		this.alignAreaMode = 'selection';
		this.zoom = 0.4;
		this.canvas = canvas;
		this.ctx = canvas.getContext('2d')!;

		this.isDragging = false;
		this.isResizing = false;
		this.dragStartPos = { x: 0, y: 0 };
		this.elementStartPos = { x: 0, y: 0 };
		this.elementStartSize = { width: 0, height: 0 };
		this.resizeHandle = null;
		this.aspectRatio = 1;

		this.imageCache = {};

		this.previewData = null;

		this.undoStack = [];
		this.redoStack = [];
		this.isDirty = false;
		this.activeGuides = [];

		const on = <K extends keyof HTMLElementEventMap>(
			type: K,
			handler: (e: HTMLElementEventMap[K]) => void
		) => {
			const h = handler as (e: Event) => void;
			this.canvas.addEventListener(type, h);
			this.#listeners.push([type, h]);
		};
		on('mousedown', (e) => this.onMouseDown(e));
		on('mousemove', (e) => this.onMouseMove(e));
		on('mouseup', () => this.onMouseUp());
		on('mouseleave', () => this.onMouseUp());
		on('contextmenu', (e) => this.onContextMenu(e));
	}

	destroy() {
		for (const [type, h] of this.#listeners) this.canvas.removeEventListener(type, h);
		this.#listeners = [];
	}

	get elements(): TTElement[] {
		return this.config.elements;
	}

	get selectedElement(): TTElement | null {
		return this.selectedElementIndex !== null
			? (this.config.elements[this.selectedElementIndex] ?? null)
			: null;
	}

	/** Clears both selection channels — a stale multi-selection would index a nonexistent element. */
	loadConfig(config: TTTemplateConfig) {
		this.config = config;
		this.setSelection([]);
		this.undoStack = [];
		this.redoStack = [];
		this.isDirty = false;
		this.render();
	}

	setPreviewData(data: TTPreviewData | null) {
		this.previewData = data;
		this.render();
	}

	calculateOptimalZoom(containerWidth: number) {
		this.zoom = Math.max(0.2, Math.min(1.0, Math.min(0.9, (containerWidth - 40) / 1920)));
		this.updateZoom();
	}

	snapshot() {
		const s = JSON.stringify(this.config.elements);
		if (this.undoStack[this.undoStack.length - 1] === s) return;
		this.undoStack.push(s);
		if (this.undoStack.length > 60) this.undoStack.shift();
		this.redoStack = [];
	}

	undo() {
		if (!this.undoStack.length) return;
		this.redoStack.push(JSON.stringify(this.config.elements));
		this.config.elements = JSON.parse(this.undoStack.pop()!) as TTElement[];
		this.clampSelection();
		this.render();
		this.markDirty();
	}

	redo() {
		if (!this.redoStack.length) return;
		this.undoStack.push(JSON.stringify(this.config.elements));
		this.config.elements = JSON.parse(this.redoStack.pop()!) as TTElement[];
		this.clampSelection();
		this.render();
		this.markDirty();
	}

	clampSelection() {
		const n = this.config.elements.length;
		this.selectedIndices = this.selectedIndices.filter((i) => i < n);
		this.selectedElementIndex = this.selectedIndices.length
			? this.selectedIndices[this.selectedIndices.length - 1]
			: null;
	}

	markDirty() {
		this.#host.onEdited();
		this.isDirty = true;
		this.#host.onChange();
	}

	handleKeyDown(e: KeyboardEvent): void {
		const ctrl = e.ctrlKey || e.metaKey;
		if (ctrl && e.key.toLowerCase() === 'z') {
			e.preventDefault();
			if (e.shiftKey) this.redo();
			else this.undo();
			return;
		}
		if (ctrl && e.key.toLowerCase() === 'y') {
			e.preventDefault();
			this.redo();
			return;
		}
		if (ctrl && e.key.toLowerCase() === 'd') {
			e.preventDefault();
			this.duplicateSelected();
			return;
		}

		if (!this.selectedIndices.length) {
			return;
		}

		const elements = this.config.elements;
		const selected = this.selectedIndices.map((i) => elements[i]);

		switch (e.key) {
			case 'Delete':
			case 'Backspace':
				e.preventDefault();
				this.deleteSelected();
				break;
			case 'Escape':
				this.selectElement(null);
				break;
			case 'ArrowUp':
			case 'ArrowDown':
			case 'ArrowLeft':
			case 'ArrowRight': {
				e.preventDefault();
				if (!e.repeat) this.snapshot();
				const step = e.shiftKey ? 10 : 1;
				const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0;
				const dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0;
				selected.forEach((element) => {
					element.x = Math.max(0, Math.round(element.x + dx));
					element.y = Math.max(0, Math.round(element.y + dy));
				});
				this.render();
				this.markDirty();
				break;
			}
		}
	}

	addElement(type: string) {
		this.snapshot();
		const element = this.createDefaultElement(type);
		this.config.elements.push(element);
		this.setSelection([this.config.elements.length - 1]);
		this.render();
		this.markDirty();
	}

	createDefaultElement(type: string): TTElement {
		const baseElement = { type: type, x: 100, y: 100 };

		switch (type) {
			case 'poster':
				return { ...baseElement, feature_index: 0, width: 300, height: 450, opacity: 1.0 };
			case 'text':
				return {
					...baseElement,
					field: 'title',
					feature_index: 0,
					font: 'Arial',
					size: 48,
					color: '#FFFFFF',
					opacity: 1.0
				};
			case 'rectangle':
				return {
					...baseElement,
					width: 200,
					height: 100,
					color: '#FFFFFF',
					fill: true,
					opacity: 1.0
				};
			case 'image':
				return { ...baseElement, path: '', width: 200, height: 200, opacity: 1.0 };
			default:
				return baseElement;
		}
	}

	deleteElement(index: number) {
		this.snapshot();
		this.config.elements.splice(index, 1);
		this.setSelection(
			this.selectedIndices.filter((i) => i !== index).map((i) => (i > index ? i - 1 : i))
		);
		this.render();
		this.markDirty();
	}

	deleteSelected() {
		if (!this.selectedIndices.length) return;
		this.snapshot();
		const remove = new Set(this.selectedIndices);
		this.config.elements = this.config.elements.filter((_, i) => !remove.has(i));
		this.setSelection([]);
		this.render();
		this.markDirty();
	}

	moveElement(index: number, direction: number) {
		const elements = this.config.elements;
		const newIndex = index + direction;
		if (newIndex < 0 || newIndex >= elements.length) return;

		this.snapshot();
		[elements[index], elements[newIndex]] = [elements[newIndex], elements[index]];
		this.setSelection([newIndex]);
		this.render();
		this.markDirty();
	}

	duplicateSelected() {
		if (!this.selectedIndices.length) return;
		this.snapshot();
		const elements = this.config.elements;
		const clones = this.selectedIndices.map((i) => {
			const clone: TTElement = JSON.parse(JSON.stringify(elements[i])) as TTElement;
			clone.x = Math.min(1920 - 20, (clone.x || 0) + 20);
			clone.y = Math.min(1080 - 20, (clone.y || 0) + 20);
			return clone;
		});
		elements.push(...clones);
		this.setSelection(clones.map((_, i) => elements.length - clones.length + i));
		this.render();
		this.markDirty();
	}

	setSelection(indices: number[]) {
		const n = this.config.elements.length;
		this.selectedIndices = [...new Set(indices)].filter((i) => i >= 0 && i < n);
		this.selectedElementIndex = this.selectedIndices.length
			? this.selectedIndices[this.selectedIndices.length - 1]
			: null;
	}

	selectElement(index: number | null, additive = false) {
		if (index === null) {
			this.setSelection([]);
		} else if (additive) {
			const at = this.selectedIndices.indexOf(index);
			if (at >= 0) {
				const arr = [...this.selectedIndices];
				arr.splice(at, 1);
				this.setSelection(arr);
			} else {
				this.setSelection([...this.selectedIndices, index]);
			}
		} else {
			this.setSelection([index]);
		}
		this.render();
	}

	updateElementProperty(property: string, value: unknown) {
		if (this.selectedElementIndex === null) return;
		const element = this.config.elements[this.selectedElementIndex];

		if (property === 'max_width') {
			value = value === '' || value == null ? null : parseInt(String(value)) || null;
		} else if (['x', 'y', 'width', 'height', 'size', 'feature_index'].includes(property)) {
			value = parseInt(String(value)) || 0;
		} else if (['opacity'].includes(property)) {
			value = parseFloat(String(value)) || 1.0;
		} else if (property === 'fill') {
			value = value === 'true' || value === true;
		}

		if (
			element.lock_aspect &&
			(property === 'width' || property === 'height') &&
			element.width &&
			element.height
		) {
			const ratio = element.width / element.height;
			if (property === 'width') {
				element.width = value as number;
				element.height = Math.max(1, Math.round((value as number) / ratio));
			} else {
				element.height = value as number;
				element.width = Math.max(1, Math.round((value as number) * ratio));
			}
			this.render();
			this.markDirty();
			return;
		}

		if (property === 'path' && element.type === 'image') {
			if (element.path && this.imageCache[element.path]) {
				delete this.imageCache[element.path];
			}
			if (value) {
				element._autoResize = true;
			}
		}

		(element as unknown as Record<string, unknown>)[property] = value;
		this.render();
		this.markDirty();
	}

	toggleAspectLock() {
		if (this.selectedElementIndex === null) return;
		const el = this.config.elements[this.selectedElementIndex];
		el.lock_aspect = !el.lock_aspect;
		this.markDirty();
	}

	centerElementHorizontally() {
		if (this.selectedElementIndex === null) return;
		const element = this.config.elements[this.selectedElementIndex];
		const bounds = this.getElementBounds(element);

		this.snapshot();
		element.x = Math.round((1920 - bounds.width) / 2);

		this.render();
		this.markDirty();
	}

	centerElementVertically() {
		if (this.selectedElementIndex === null) return;
		const element = this.config.elements[this.selectedElementIndex];
		const bounds = this.getElementBounds(element);

		this.snapshot();
		element.y = Math.round((1080 - bounds.height) / 2);

		this.render();
		this.markDirty();
	}

	getCanvasCoords(e: MouseEvent) {
		const rect = this.canvas.getBoundingClientRect();
		const x = (e.clientX - rect.left) * (1920 / rect.width);
		const y = (e.clientY - rect.top) * (1080 / rect.height);
		return { x, y };
	}

	getElementBounds(element: TTElement): TTBounds {
		if (element.type === 'text') {
			const size = element.size || 48;
			this.ctx.font = `${size}px ${element.font || 'Arial'}`;
			const text = this.getTextPreview(element);
			if (element.max_width) {
				const lines = this.wrapText(text, element.max_width);
				const lineHeight = Math.round(size * 1.2);
				return {
					x: element.x,
					y: element.y,
					width: element.max_width,
					height: Math.max(1, lines.length) * lineHeight
				};
			}
			const w = this.ctx.measureText(text).width;
			return { x: element.x, y: element.y, width: Math.max(20, w), height: size };
		}
		const width = element.width || 100;
		const height = element.height || 50;
		return { x: element.x, y: element.y, width, height };
	}

	hitTest(x: number, y: number, bounds: TTBounds): boolean {
		return (
			x >= bounds.x &&
			x <= bounds.x + bounds.width &&
			y >= bounds.y &&
			y <= bounds.y + bounds.height
		);
	}

	getResizeHandle(x: number, y: number, element: TTElement): TTResizeHandle | null {
		if (!element.width || !element.height) return null;

		const handleSize = 40;
		const bounds = this.getElementBounds(element);

		if (Math.abs(x - bounds.x) < handleSize && Math.abs(y - bounds.y) < handleSize) return 'nw';
		if (Math.abs(x - (bounds.x + bounds.width)) < handleSize && Math.abs(y - bounds.y) < handleSize)
			return 'ne';
		if (
			Math.abs(x - bounds.x) < handleSize &&
			Math.abs(y - (bounds.y + bounds.height)) < handleSize
		)
			return 'sw';
		if (
			Math.abs(x - (bounds.x + bounds.width)) < handleSize &&
			Math.abs(y - (bounds.y + bounds.height)) < handleSize
		)
			return 'se';

		return null;
	}

	onContextMenu(e: MouseEvent) {
		e.preventDefault();
		const coords = this.getCanvasCoords(e);
		const elements = this.config.elements;
		let hit: number | null = null;
		for (let i = elements.length - 1; i >= 0; i--) {
			if (this.hitTest(coords.x, coords.y, this.getElementBounds(elements[i]))) {
				hit = i;
				break;
			}
		}
		if (hit === null) return;
		if (!this.selectedIndices.includes(hit)) this.setSelection([hit]);
		this.render();
		this.#host.onContextMenu(e.clientX, e.clientY, hit);
	}

	onMouseDown(e: MouseEvent) {
		const coords = this.getCanvasCoords(e);
		const elements = this.config.elements;

		if (this.selectedIndices.length === 1) {
			const element = elements[this.selectedElementIndex!];
			const handle = this.getResizeHandle(coords.x, coords.y, element);

			if (handle) {
				this.snapshot();
				this.isResizing = true;
				this.resizeHandle = handle;
				this.dragStartPos = coords;
				this.elementStartPos = { x: element.x, y: element.y };
				this.elementStartSize = {
					width: element.width || 100,
					height: element.height || 50
				};
				this.aspectRatio = this.elementStartSize.width / this.elementStartSize.height;
				e.preventDefault();
				e.stopPropagation();
				return;
			}
		}

		// Element click (top-most first)
		for (let i = elements.length - 1; i >= 0; i--) {
			const bounds = this.getElementBounds(elements[i]);
			if (this.hitTest(coords.x, coords.y, bounds)) {
				if (e.shiftKey) {
					this.selectElement(i, true);
					return;
				}
				// Plain click keeps the group if it's already selected, else select only this
				if (!this.selectedIndices.includes(i)) {
					this.setSelection([i]);
					this.render();
				}
				this.snapshot();
				this.isDragging = true;
				this.dragStartPos = coords;
				this.dragStartPositions = this.selectedIndices.map((idx) => ({
					el: elements[idx],
					x: elements[idx].x,
					y: elements[idx].y
				}));
				return;
			}
		}

		// Empty space begins a marquee (rubber-band) selection
		this.isMarquee = true;
		this.marqueeMoved = false;
		this.marquee = { x0: coords.x, y0: coords.y, x1: coords.x, y1: coords.y, additive: e.shiftKey };
	}

	onMouseMove(e: MouseEvent) {
		const coords = this.getCanvasCoords(e);
		const elements = this.config.elements;

		if (this.isResizing && this.selectedElementIndex !== null) {
			const element = elements[this.selectedElementIndex];
			const dx = coords.x - this.dragStartPos.x;
			const dy = coords.y - this.dragStartPos.y;
			const sw = this.elementStartSize.width,
				sh = this.elementStartSize.height;
			const sx = this.elementStartPos.x,
				sy = this.elementStartPos.y;
			const handle = this.resizeHandle;

			// Free resize per handle: the dragged corner moves, opposite corner anchors
			let w = sw + (handle === 'nw' || handle === 'sw' ? -dx : dx);
			let h = sh + (handle === 'nw' || handle === 'ne' ? -dy : dy);
			w = Math.max(20, w);
			h = Math.max(20, h);

			if (element.lock_aspect) {
				if (Math.abs(dx) > Math.abs(dy * this.aspectRatio)) {
					h = Math.round(w / this.aspectRatio);
				} else {
					w = Math.round(h * this.aspectRatio);
				}
				w = Math.max(20, w);
				h = Math.max(20, h);
			}

			element.width = Math.round(w);
			element.height = Math.round(h);
			if (handle === 'nw' || handle === 'sw') element.x = Math.round(sx + (sw - element.width));
			if (handle === 'nw' || handle === 'ne') element.y = Math.round(sy + (sh - element.height));

			this.render();
			return;
		}

		if (this.isDragging && this.dragStartPositions.length) {
			let dx = coords.x - this.dragStartPos.x;
			let dy = coords.y - this.dragStartPos.y;
			this.dragStartPositions.forEach(({ el, x, y }) => {
				const b = this.getElementBounds(el);
				dx = Math.max(dx, -x);
				dx = Math.min(dx, 1920 - b.width - x);
				dy = Math.max(dy, -y);
				dy = Math.min(dy, 1080 - b.height - y);
			});
			// Shift bypasses snapping
			this.activeGuides = [];
			if (!e.shiftKey) {
				const snapped = this.applySnapping(dx, dy);
				dx = snapped.dx;
				dy = snapped.dy;
			}
			this.dragStartPositions.forEach(({ el, x, y }) => {
				el.x = Math.round(x + dx);
				el.y = Math.round(y + dy);
			});
			this.render();
			return;
		}

		if (this.isMarquee) {
			this.marquee!.x1 = coords.x;
			this.marquee!.y1 = coords.y;
			if (
				Math.abs(this.marquee!.x1 - this.marquee!.x0) > 3 ||
				Math.abs(this.marquee!.y1 - this.marquee!.y0) > 3
			) {
				this.marqueeMoved = true;
			}
			this.render();
			return;
		}

		let cursor = 'default';
		if (this.selectedIndices.length === 1) {
			const handle = this.getResizeHandle(coords.x, coords.y, elements[this.selectedElementIndex!]);
			if (handle) cursor = handle === 'nw' || handle === 'se' ? 'nwse-resize' : 'nesw-resize';
		}
		if (cursor === 'default') {
			for (let i = elements.length - 1; i >= 0; i--) {
				if (this.hitTest(coords.x, coords.y, this.getElementBounds(elements[i]))) {
					cursor = this.selectedIndices.includes(i) ? 'move' : 'pointer';
					break;
				}
			}
		}
		this.canvas.style.cursor = cursor;
	}

	// Snaps the dragged group; records guide lines in this.activeGuides for the overlay to draw.
	applySnapping(dx: number, dy: number): { dx: number; dy: number } {
		const THRESHOLD = 10; // canvas units
		const elements = this.config.elements;
		const draggedSet = new Set(this.dragStartPositions.map((p) => p.el));

		let gx1 = Infinity,
			gy1 = Infinity,
			gx2 = -Infinity,
			gy2 = -Infinity;
		this.dragStartPositions.forEach(({ el, x, y }) => {
			const b = this.getElementBounds(el);
			gx1 = Math.min(gx1, x + dx);
			gy1 = Math.min(gy1, y + dy);
			gx2 = Math.max(gx2, x + dx + b.width);
			gy2 = Math.max(gy2, y + dy + b.height);
		});
		const gcx = (gx1 + gx2) / 2,
			gcy = (gy1 + gy2) / 2;

		// Candidate lines: canvas edges + centre, then other elements
		const vCandidates = [0, 960, 1920];
		const hCandidates = [0, 540, 1080];
		elements.forEach((el) => {
			if (draggedSet.has(el)) return;
			const b = this.getElementBounds(el);
			vCandidates.push(b.x, b.x + b.width / 2, b.x + b.width);
			hCandidates.push(b.y, b.y + b.height / 2, b.y + b.height);
		});

		const snapAxis = (
			candidates: number[],
			edges: number[]
		): { delta: number; line: number } | null => {
			let best: { delta: number; line: number } | null = null;
			candidates.forEach((line) => {
				edges.forEach((edge) => {
					const delta = line - edge;
					if (
						Math.abs(delta) <= THRESHOLD &&
						(best === null || Math.abs(delta) < Math.abs(best.delta))
					) {
						best = { delta, line };
					}
				});
			});
			return best;
		};

		const vSnap = snapAxis(vCandidates, [gx1, gcx, gx2]);
		const hSnap = snapAxis(hCandidates, [gy1, gcy, gy2]);
		if (vSnap) {
			dx += vSnap.delta;
			this.activeGuides.push({ axis: 'v', pos: vSnap.line });
		}
		if (hSnap) {
			dy += hSnap.delta;
			this.activeGuides.push({ axis: 'h', pos: hSnap.line });
		}
		return { dx, dy };
	}

	onMouseUp() {
		if (this.isDragging || this.isResizing) this.markDirty();

		if (this.isMarquee) {
			if (this.marqueeMoved) {
				const m = this.marquee!;
				const x = Math.min(m.x0, m.x1),
					y = Math.min(m.y0, m.y1);
				const x2 = Math.max(m.x0, m.x1),
					y2 = Math.max(m.y0, m.y1);
				const hits: number[] = [];
				this.config.elements.forEach((el, i) => {
					const b = this.getElementBounds(el);
					if (b.x < x2 && b.x + b.width > x && b.y < y2 && b.y + b.height > y) hits.push(i);
				});
				this.setSelection(m.additive ? [...this.selectedIndices, ...hits] : hits);
			} else if (!this.marquee!.additive) {
				this.setSelection([]);
			}
			this.isMarquee = false;
			this.marquee = null;
			this.marqueeMoved = false;
			this.render();
		}

		this.isDragging = false;
		this.isResizing = false;
		this.resizeHandle = null;
		this.dragStartPositions = [];
		if (this.activeGuides.length) {
			this.activeGuides = [];
			this.render();
		}
	}

	render() {
		this.renderCanvas();
		this.renderSelectionOverlay();
		this.#host.onChange();
	}

	renderCanvas() {
		this.ctx.fillStyle = '#000000';
		this.ctx.fillRect(0, 0, 1920, 1080);

		this.config.elements.forEach((element) => {
			this.renderElement(element);
		});
	}

	renderElement(element: TTElement) {
		this.ctx.save();
		if (element.opacity !== undefined) {
			this.ctx.globalAlpha = element.opacity;
		}

		switch (element.type) {
			case 'poster':
				this.renderPoster(element);
				break;
			case 'text':
				this.renderText(element);
				break;
			case 'rectangle':
				this.renderRectangle(element);
				break;
			case 'image':
				this.renderImage(element);
				break;
		}

		this.ctx.restore();
	}

	renderPoster(element: TTElement) {
		if (this.previewData) {
			const feat = this.previewData.features[element.feature_index || 0];
			if (feat && feat.poster) {
				const img = this.loadImage(feat.poster);
				if (img && img.complete && img.naturalWidth > 0) {
					this.ctx.drawImage(img, element.x, element.y, element.width!, element.height!);
					return;
				}
			}
		}

		this.ctx.strokeStyle = '#666';
		this.ctx.lineWidth = 3;
		this.ctx.strokeRect(element.x, element.y, element.width!, element.height!);

		this.ctx.strokeStyle = '#444';
		this.ctx.lineWidth = 1;
		this.ctx.beginPath();
		this.ctx.moveTo(element.x, element.y);
		this.ctx.lineTo(element.x + element.width!, element.y + element.height!);
		this.ctx.moveTo(element.x + element.width!, element.y);
		this.ctx.lineTo(element.x, element.y + element.height!);
		this.ctx.stroke();

		this.ctx.fillStyle = '#666';
		this.ctx.font = '20px Arial';
		this.ctx.textAlign = 'center';
		this.ctx.fillText(
			`Poster ${element.feature_index || 0}`,
			element.x + element.width! / 2,
			element.y + element.height! / 2
		);
	}

	renderText(element: TTElement) {
		const size = element.size || 48;
		this.ctx.fillStyle = element.color || '#FFFFFF';
		this.ctx.font = `${size}px ${element.font || 'Arial'}`;
		this.ctx.textAlign = 'left';
		this.ctx.textBaseline = 'top';

		const text = this.getTextPreview(element);
		const maxWidth = element.max_width;
		const align = element.align || 'left';

		if (maxWidth) {
			const lines = this.wrapText(text, maxWidth);
			const lineHeight = Math.round(size * 1.2);
			lines.forEach((line, i) => {
				const lineWidth = this.ctx.measureText(line).width;
				let lx = element.x;
				if (align === 'center') lx = element.x + (maxWidth - lineWidth) / 2;
				else if (align === 'right') lx = element.x + (maxWidth - lineWidth);
				this.ctx.fillText(line, lx, element.y + i * lineHeight);
			});
		} else {
			this.ctx.fillText(text, element.x, element.y);
		}
	}

	wrapText(text: string, maxWidth: number): string[] {
		// ctx.font must already be set by the caller
		const words = String(text).split(/\s+/).filter(Boolean);
		if (!words.length) return [''];
		const lines = [];
		let current = words[0];
		for (let i = 1; i < words.length; i++) {
			const candidate = current + ' ' + words[i];
			if (this.ctx.measureText(candidate).width <= maxWidth) {
				current = candidate;
			} else {
				lines.push(current);
				current = words[i];
			}
		}
		lines.push(current);
		return lines;
	}

	getTextPreview(element: TTElement): string {
		if (this.previewData) {
			if (element.field === 'programme_name') {
				return this.previewData.programme_name || 'Programme';
			}
			const feat = this.previewData.features[element.feature_index || 0];
			if (feat) {
				const value = feat[element.field as keyof TTFeature];
				if (value != null && value !== '') return String(value);
			}
		}

		const labels: Record<string, string> = {
			title: 'Movie Title',
			director: 'Director Name',
			year: '2024',
			certification: 'PG-13',
			runtime: '120 min',
			programme_name: 'Programme Name'
		};
		return labels[element.field!] || element.field || 'Text';
	}

	renderRectangle(element: TTElement) {
		this.ctx.fillStyle = element.color || '#FFFFFF';
		this.ctx.strokeStyle = element.color || '#FFFFFF';
		this.ctx.lineWidth = element.border_width || 1;

		if (element.fill) {
			this.ctx.fillRect(element.x, element.y, element.width!, element.height!);
		} else {
			this.ctx.strokeRect(element.x, element.y, element.width!, element.height!);
		}
	}

	renderImage(element: TTElement) {
		if (element.path && element.path.trim()) {
			const img = this.loadImage(element.path);
			if (img && img.complete && img.naturalWidth > 0) {
				this.ctx.save();
				this.ctx.drawImage(img, element.x, element.y, element.width!, element.height!);
				this.ctx.restore();
			} else {
				this.drawImagePlaceholder(element, 'Loading...');
			}
		} else {
			this.drawImagePlaceholder(element, 'No Image');
		}
	}

	drawImagePlaceholder(element: TTElement, text: string) {
		this.ctx.strokeStyle = '#f39c12';
		this.ctx.lineWidth = 3;
		this.ctx.strokeRect(element.x, element.y, element.width!, element.height!);

		this.ctx.fillStyle = '#f39c12';
		this.ctx.font = '30px Arial';
		this.ctx.textAlign = 'center';
		this.ctx.fillText('🖼', element.x + element.width! / 2, element.y + element.height! / 2 - 20);
		this.ctx.font = '16px Arial';
		this.ctx.fillText(text, element.x + element.width! / 2, element.y + element.height! / 2 + 15);
	}

	loadImage(path: string): HTMLImageElement {
		if (this.imageCache[path]) {
			return this.imageCache[path];
		}

		const img = new Image();
		img.onload = () => {
			// Auto-resize to the image's natural size, once, only when _autoResize is set
			const elements = this.config.elements;
			for (let i = 0; i < elements.length; i++) {
				const el = elements[i];
				if (el.type === 'image' && el.path === path && el._autoResize === true) {
					el.width = img.naturalWidth;
					el.height = img.naturalHeight;
					delete el._autoResize;
					break;
				}
			}
			this.render();
		};
		img.onerror = () => {
			console.error('Failed to load image:', path);
			delete this.imageCache[path];
		};
		img.src = path;

		this.imageCache[path] = img;
		return img;
	}

	renderSelectionOverlay() {
		const elements = this.config.elements;
		this.ctx.save();

		if (this.activeGuides.length) {
			this.ctx.strokeStyle = '#6B8CAE';
			this.ctx.lineWidth = 2;
			this.ctx.setLineDash([8, 6]);
			this.activeGuides.forEach(({ axis, pos }) => {
				this.ctx.beginPath();
				if (axis === 'v') {
					this.ctx.moveTo(pos, 0);
					this.ctx.lineTo(pos, 1080);
				} else {
					this.ctx.moveTo(0, pos);
					this.ctx.lineTo(1920, pos);
				}
				this.ctx.stroke();
			});
		}

		this.ctx.strokeStyle = '#5D8A66';
		this.ctx.lineWidth = 2;
		this.ctx.setLineDash([5, 5]);
		this.selectedIndices.forEach((idx) => {
			const el = elements[idx];
			if (!el) return;
			const b = this.getElementBounds(el);
			this.ctx.strokeRect(b.x, b.y, b.width, b.height);
		});

		if (this.selectedIndices.length === 1) {
			const element = elements[this.selectedElementIndex!];
			if (element && element.width && element.height) {
				const bounds = this.getElementBounds(element);
				this.ctx.fillStyle = '#5D8A66';
				this.ctx.strokeStyle = '#FFFFFF';
				this.ctx.lineWidth = 2;
				this.ctx.setLineDash([]);
				const handleSize = 12;
				const corners = [
					[bounds.x, bounds.y],
					[bounds.x + bounds.width, bounds.y],
					[bounds.x, bounds.y + bounds.height],
					[bounds.x + bounds.width, bounds.y + bounds.height]
				];
				corners.forEach(([x, y]) => {
					this.ctx.fillRect(x - handleSize / 2, y - handleSize / 2, handleSize, handleSize);
					this.ctx.strokeRect(x - handleSize / 2, y - handleSize / 2, handleSize, handleSize);
				});
			}
		}

		if (this.isMarquee && this.marquee && this.marqueeMoved) {
			const m = this.marquee;
			const x = Math.min(m.x0, m.x1),
				y = Math.min(m.y0, m.y1);
			const w = Math.abs(m.x1 - m.x0),
				h = Math.abs(m.y1 - m.y0);
			this.ctx.setLineDash([4, 4]);
			this.ctx.strokeStyle = '#6B8CAE';
			this.ctx.lineWidth = 2;
			this.ctx.fillStyle = 'rgba(107, 140, 174, 0.12)';
			this.ctx.fillRect(x, y, w, h);
			this.ctx.strokeRect(x, y, w, h);
		}

		this.ctx.restore();
	}

	selectionBounds() {
		const bs = this.selectedIndices.map((i) => this.getElementBounds(this.config.elements[i]));
		const minX = Math.min(...bs.map((b) => b.x));
		const minY = Math.min(...bs.map((b) => b.y));
		const maxX = Math.max(...bs.map((b) => b.x + b.width));
		const maxY = Math.max(...bs.map((b) => b.y + b.height));
		return { minX, minY, maxX, maxY, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 };
	}

	get alignArea() {
		if (this.alignAreaMode === 'canvas') {
			return { minX: 0, minY: 0, maxX: 1920, maxY: 1080, cx: 960, cy: 540 };
		}
		return this.selectionBounds();
	}

	align(mode: TTAlignMode) {
		if (!this.selectedIndices.length) return;
		this.snapshot();
		const a = this.alignArea;
		this.selectedIndices.forEach((i) => {
			const el = this.config.elements[i];
			const b = this.getElementBounds(el);
			switch (mode) {
				case 'left':
					el.x = Math.round(a.minX);
					break;
				case 'centerH':
					el.x = Math.round(a.cx - b.width / 2);
					break;
				case 'right':
					el.x = Math.round(a.maxX - b.width);
					break;
				case 'top':
					el.y = Math.round(a.minY);
					break;
				case 'middle':
					el.y = Math.round(a.cy - b.height / 2);
					break;
				case 'bottom':
					el.y = Math.round(a.maxY - b.height);
					break;
			}
			el.x = Math.max(0, el.x);
			el.y = Math.max(0, el.y);
		});
		this.render();
		this.markDirty();
	}

	distribute(axis: 'h' | 'v', by: 'centers' | 'gaps' = 'centers') {
		if (this.selectedIndices.length < 2) return;
		this.snapshot();
		const horiz = axis === 'h';
		const items = this.selectedIndices.map((i) => {
			const el = this.config.elements[i];
			const b = this.getElementBounds(el);
			return { el, start: horiz ? b.x : b.y, size: horiz ? b.width : b.height };
		});

		let lo: number, hi: number;
		if (this.alignAreaMode === 'canvas') {
			lo = 0;
			hi = horiz ? 1920 : 1080;
		} else {
			lo = Math.min(...items.map((i) => i.start));
			hi = Math.max(...items.map((i) => i.start + i.size));
		}

		const setPos = (it: { el: TTElement; start: number; size: number }, pos: number) => {
			pos = Math.max(0, Math.round(pos));
			if (horiz) it.el.x = pos;
			else it.el.y = pos;
		};

		if (by === 'gaps') {
			const sorted = [...items].sort((p, q) => p.start - q.start);
			const sumSizes = sorted.reduce((s, it) => s + it.size, 0);
			const gap = sorted.length > 1 ? (hi - lo - sumSizes) / (sorted.length - 1) : 0;
			let cur = lo;
			sorted.forEach((it) => {
				setPos(it, cur);
				cur += it.size + gap;
			});
		} else {
			const sorted = [...items].sort((p, q) => p.start + p.size / 2 - (q.start + q.size / 2));
			let c0: number, c1: number;
			if (this.alignAreaMode === 'canvas') {
				c0 = lo + sorted[0].size / 2;
				c1 = hi - sorted[sorted.length - 1].size / 2;
			} else {
				c0 = sorted[0].start + sorted[0].size / 2;
				c1 = sorted[sorted.length - 1].start + sorted[sorted.length - 1].size / 2;
			}
			const step = sorted.length > 1 ? (c1 - c0) / (sorted.length - 1) : 0;
			sorted.forEach((it, idx) => setPos(it, c0 + step * idx - it.size / 2));
		}

		this.render();
		this.markDirty();
	}

	setAlignArea(value: 'selection' | 'canvas') {
		this.alignAreaMode = value;
		this.#host.onChange();
	}

	changeZoom(delta: number) {
		this.zoom = Math.max(0.1, Math.min(2, this.zoom + delta));
		this.updateZoom();
	}

	updateZoom() {
		// Scale via CSS size only — the 1920x1080 buffer stays crisp (no transform, no phantom space)
		this.canvas.style.width = 1920 * this.zoom + 'px';
		this.canvas.style.height = 1080 * this.zoom + 'px';
		this.#host.onChange();
	}

	getElementTitle(element: TTElement): string {
		switch (element.type) {
			case 'poster':
				return `Feature ${element.feature_index || 0} Poster`;
			case 'text':
				return `${element.field || 'text'} (${element.size}px)`;
			case 'rectangle':
				return `Rectangle ${element.width}x${element.height}`;
			case 'image':
				return element.path || 'Image (no path)';
			default:
				return element.type;
		}
	}
}
