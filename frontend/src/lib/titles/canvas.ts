// Title-template editor built on Konva: a fixed 1920×1080 stage of posters, text,
// images and shapes, with drag, corner-resize, snapping, multi-select and undo/redo.
import Konva from 'konva';

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

export type TTAlignMode = 'left' | 'centerH' | 'right' | 'top' | 'middle' | 'bottom';

export interface EditorHost {
	onChange(): void;
	/** markDirty fired — hide a stale server-rendered preview. */
	onEdited(): void;
	onContextMenu(clientX: number, clientY: number, hit: number): void;
}

const CW = 1920;
const CH = 1080;
const SNAP = 10;

// Unbundled sans names resolve to a bundled face so the canvas matches the
// server-rendered card (mirrors BUNDLED_ALIASES in titlegen_service.py).
const FONT_ALIASES: Record<string, string> = {
	Arial: 'Inter',
	Helvetica: 'Inter',
	'sans-serif': 'Inter'
};
function fontFamily(name?: string): string {
	const n = name || 'Inter';
	return FONT_ALIASES[n] ?? n;
}

export function emptyTemplateConfig(): TTTemplateConfig {
	return { canvas: { width: CW, height: CH }, elements: [] };
}

export class TitleCanvasEditor {
	config: TTTemplateConfig;
	selectedElementIndex: number | null = null;
	selectedIndices: number[] = [];
	alignAreaMode: 'selection' | 'canvas' = 'selection';
	zoom = 0.4;
	isDirty = false;
	previewData: TTPreviewData | null = null;
	undoStack: string[] = [];
	redoStack: string[] = [];

	#host: EditorHost;
	#stage: Konva.Stage;
	#content: Konva.Layer;
	#overlay: Konva.Layer;
	#tr: Konva.Transformer;
	#nodes: Konva.Node[] = [];
	#images: Record<string, HTMLImageElement> = {};
	#destroyed = false;

	// Drag state (canvas-space).
	#dragStart: Array<{ node: Konva.Node; x: number; y: number }> = [];
	#dragOrigin = { x: 0, y: 0 };
	// Marquee state.
	#marquee: { x0: number; y0: number; additive: boolean } | null = null;

	constructor(container: HTMLDivElement, host: EditorHost) {
		this.config = emptyTemplateConfig();
		this.#host = host;

		this.#stage = new Konva.Stage({ container, width: CW * this.zoom, height: CH * this.zoom });
		this.#content = new Konva.Layer();
		this.#overlay = new Konva.Layer({ listening: false });
		this.#stage.add(this.#content, this.#overlay);

		const bg = new Konva.Rect({ x: 0, y: 0, width: CW, height: CH, fill: '#000000' });
		this.#content.add(bg);

		this.#tr = new Konva.Transformer({
			rotateEnabled: false,
			keepRatio: false,
			enabledAnchors: ['top-left', 'top-right', 'bottom-left', 'bottom-right'],
			anchorSize: 12,
			anchorStroke: '#FFFFFF',
			anchorFill: '#5D8A66',
			borderStroke: '#5D8A66',
			borderDash: [5, 5],
			boundBoxFunc: (oldBox, newBox) =>
				newBox.width < 20 || newBox.height < 20 ? oldBox : newBox
		});
		this.#content.add(this.#tr);

		this.applyZoom();

		this.#stage.on('mousedown', (e) => this.#onStageDown(e));
		this.#stage.on('mousemove', () => this.#onStageMove());
		this.#stage.on('mouseup', () => this.#onStageUp());
		this.#stage.on('contextmenu', (e) => this.#onContextMenu(e));
	}

	destroy() {
		this.#destroyed = true;
		this.#stage.destroy();
	}

	get elements(): TTElement[] {
		return this.config.elements;
	}

	get selectedElement(): TTElement | null {
		return this.selectedElementIndex !== null
			? (this.config.elements[this.selectedElementIndex] ?? null)
			: null;
	}

	loadConfig(config: TTTemplateConfig) {
		this.config = config;
		this.selectedIndices = [];
		this.selectedElementIndex = null;
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
		this.zoom = Math.max(0.2, Math.min(0.9, (containerWidth - 40) / CW));
		this.applyZoom();
	}

	changeZoom(delta: number) {
		this.zoom = Math.max(0.1, Math.min(2, this.zoom + delta));
		this.applyZoom();
	}

	applyZoom() {
		this.#stage.scale({ x: this.zoom, y: this.zoom });
		this.#stage.size({ width: CW * this.zoom, height: CH * this.zoom });
		this.#host.onChange();
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
		this.#clampSelection();
		this.render();
		this.markDirty();
	}

	redo() {
		if (!this.redoStack.length) return;
		this.undoStack.push(JSON.stringify(this.config.elements));
		this.config.elements = JSON.parse(this.redoStack.pop()!) as TTElement[];
		this.#clampSelection();
		this.render();
		this.markDirty();
	}

	#clampSelection() {
		const n = this.config.elements.length;
		this.setSelection(this.selectedIndices.filter((i) => i < n));
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
		if (!this.selectedIndices.length) return;

		const selected = this.selectedIndices.map((i) => this.config.elements[i]);
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
				selected.forEach((el) => {
					el.x = Math.max(0, Math.round(el.x + dx));
					el.y = Math.max(0, Math.round(el.y + dy));
				});
				this.render();
				this.markDirty();
				break;
			}
		}
	}

	addElement(type: string) {
		this.snapshot();
		this.config.elements.push(this.createDefaultElement(type));
		this.setSelection([this.config.elements.length - 1]);
		this.render();
		this.markDirty();
	}

	createDefaultElement(type: string): TTElement {
		const base = { type, x: 100, y: 100 };
		switch (type) {
			case 'poster':
				return { ...base, feature_index: 0, width: 300, height: 450, opacity: 1.0 };
			case 'text':
				return {
					...base,
					field: 'title',
					feature_index: 0,
					font: 'Inter',
					size: 48,
					color: '#FFFFFF',
					opacity: 1.0
				};
			case 'rectangle':
				return { ...base, width: 200, height: 100, color: '#FFFFFF', fill: true, opacity: 1.0 };
			case 'image':
				return { ...base, path: '', width: 200, height: 200, opacity: 1.0 };
			default:
				return base;
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
		const els = this.config.elements;
		const to = index + direction;
		if (to < 0 || to >= els.length) return;
		this.snapshot();
		[els[index], els[to]] = [els[to], els[index]];
		this.setSelection([to]);
		this.render();
		this.markDirty();
	}

	duplicateSelected() {
		if (!this.selectedIndices.length) return;
		this.snapshot();
		const els = this.config.elements;
		const clones = this.selectedIndices.map((i) => {
			const clone = JSON.parse(JSON.stringify(els[i])) as TTElement;
			clone.x = Math.min(CW - 20, (clone.x || 0) + 20);
			clone.y = Math.min(CH - 20, (clone.y || 0) + 20);
			return clone;
		});
		els.push(...clones);
		this.setSelection(clones.map((_, i) => els.length - clones.length + i));
		this.render();
		this.markDirty();
	}

	setSelection(indices: number[]) {
		const n = this.config.elements.length;
		this.selectedIndices = [...new Set(indices)].filter((i) => i >= 0 && i < n);
		this.selectedElementIndex = this.selectedIndices.length
			? this.selectedIndices[this.selectedIndices.length - 1]
			: null;
		this.#refreshSelection();
	}

	selectElement(index: number | null, additive = false) {
		if (index === null) {
			this.setSelection([]);
		} else if (additive) {
			const at = this.selectedIndices.indexOf(index);
			if (at >= 0) this.setSelection(this.selectedIndices.filter((i) => i !== index));
			else this.setSelection([...this.selectedIndices, index]);
		} else {
			this.setSelection([index]);
		}
	}

	updateElementProperty(property: string, value: unknown) {
		if (this.selectedElementIndex === null) return;
		const el = this.config.elements[this.selectedElementIndex];

		if (property === 'max_width') {
			value = value === '' || value == null ? null : parseInt(String(value)) || null;
		} else if (['x', 'y', 'width', 'height', 'size', 'feature_index'].includes(property)) {
			value = parseInt(String(value)) || 0;
		} else if (property === 'opacity') {
			value = parseFloat(String(value)) || 1.0;
		} else if (property === 'fill') {
			value = value === 'true' || value === true;
		}

		if (
			el.lock_aspect &&
			(property === 'width' || property === 'height') &&
			el.width &&
			el.height
		) {
			const ratio = el.width / el.height;
			if (property === 'width') {
				el.width = value as number;
				el.height = Math.max(1, Math.round((value as number) / ratio));
			} else {
				el.height = value as number;
				el.width = Math.max(1, Math.round((value as number) * ratio));
			}
			this.render();
			this.markDirty();
			return;
		}

		if (property === 'path' && el.type === 'image') {
			if (el.path) delete this.#images[el.path];
			if (value) el._autoResize = true;
		}

		(el as unknown as Record<string, unknown>)[property] = value;
		this.render();
		this.markDirty();
	}

	toggleAspectLock() {
		if (this.selectedElementIndex === null) return;
		const el = this.config.elements[this.selectedElementIndex];
		el.lock_aspect = !el.lock_aspect;
		this.#refreshSelection();
		this.markDirty();
	}

	centerElementHorizontally() {
		if (this.selectedElementIndex === null) return;
		const el = this.config.elements[this.selectedElementIndex];
		this.snapshot();
		el.x = Math.round((CW - this.getElementBounds(el).width) / 2);
		this.render();
		this.markDirty();
	}

	centerElementVertically() {
		if (this.selectedElementIndex === null) return;
		const el = this.config.elements[this.selectedElementIndex];
		this.snapshot();
		el.y = Math.round((CH - this.getElementBounds(el).height) / 2);
		this.render();
		this.markDirty();
	}

	getElementBounds(element: TTElement): TTBounds {
		const i = this.config.elements.indexOf(element);
		const node = i >= 0 ? this.#nodes[i] : null;
		if (element.type === 'text') {
			const w = node ? node.width() : (element.max_width ?? 200);
			const h = node ? node.height() : (element.size ?? 48);
			return { x: element.x, y: element.y, width: Math.max(20, w), height: Math.max(1, h) };
		}
		return { x: element.x, y: element.y, width: element.width || 100, height: element.height || 50 };
	}

	// --- Konva rendering -----------------------------------------------------

	render() {
		if (this.#destroyed) return;
		this.#tr.nodes([]);
		for (const node of this.#nodes) node.destroy();
		this.#nodes = [];

		this.config.elements.forEach((el, i) => {
			const node = this.#makeNode(el, i);
			this.#nodes[i] = node;
			this.#content.add(node as Konva.Shape);
		});
		this.#tr.moveToTop();
		this.#refreshSelection();
	}

	#makeNode(el: TTElement, i: number): Konva.Node {
		const opacity = el.opacity ?? 1;
		let node: Konva.Node;

		if (el.type === 'text') {
			node = new Konva.Text({
				x: el.x,
				y: el.y,
				text: this.#textPreview(el),
				fontSize: el.size || 48,
				fontFamily: fontFamily(el.font),
				fill: el.color || '#FFFFFF',
				opacity,
				align: el.align || 'left',
				...(el.max_width ? { width: el.max_width, wrap: 'word' } : { wrap: 'none' })
			});
		} else if (el.type === 'rectangle') {
			node = new Konva.Rect({
				x: el.x,
				y: el.y,
				width: el.width || 100,
				height: el.height || 50,
				opacity,
				...(el.fill
					? { fill: el.color || '#FFFFFF' }
					: { stroke: el.color || '#FFFFFF', strokeWidth: el.border_width || 1 })
			});
		} else {
			const src = this.#sourceFor(el);
			const img = src ? this.#loadImage(src) : null;
			if (img && img.complete && img.naturalWidth > 0) {
				node = new Konva.Image({
					image: img,
					x: el.x,
					y: el.y,
					width: el.width || 100,
					height: el.height || 50,
					opacity
				});
			} else {
				node = this.#placeholder(el, opacity);
			}
		}

		node.setAttr('elIndex', i);
		node.draggable(true);
		node.on('dragstart', () => this.#onDragStart(i));
		node.on('dragmove', (e) => this.#onDragMove(e));
		node.on('dragend', () => this.#onDragEnd());
		node.on('transformend', () => this.#onTransformEnd(node));
		node.on('click', (e) => this.#onNodeClick(i, e));
		node.on('mouseenter', () => {
			this.#stage.container().style.cursor = this.selectedIndices.includes(i) ? 'move' : 'pointer';
		});
		node.on('mouseleave', () => {
			this.#stage.container().style.cursor = 'default';
		});
		return node;
	}

	#placeholder(el: TTElement, opacity: number): Konva.Group {
		const w = el.width || 100;
		const h = el.height || 50;
		const poster = el.type === 'poster';
		const colour = poster ? '#666' : '#f39c12';
		const label = poster
			? `Poster ${el.feature_index || 0}`
			: el.path
				? 'Loading…'
				: 'No image';
		const g = new Konva.Group({ x: el.x, y: el.y, opacity });
		g.add(
			new Konva.Rect({ width: w, height: h, stroke: colour, strokeWidth: 3, dash: [8, 6] }),
			new Konva.Text({
				width: w,
				y: h / 2 - 10,
				align: 'center',
				text: label,
				fontSize: 20,
				fontFamily: 'Arial',
				fill: colour,
				listening: false
			})
		);
		return g;
	}

	#sourceFor(el: TTElement): string | null {
		if (el.type === 'poster') {
			const feat = this.previewData?.features[el.feature_index || 0];
			return feat?.poster || null;
		}
		return el.path && el.path.trim() ? el.path : null;
	}

	#loadImage(src: string): HTMLImageElement {
		const cached = this.#images[src];
		if (cached) return cached;
		const img = new Image();
		img.onload = () => {
			for (const el of this.config.elements) {
				if (el.type === 'image' && el.path === src && el._autoResize) {
					el.width = img.naturalWidth;
					el.height = img.naturalHeight;
					delete el._autoResize;
					break;
				}
			}
			this.render();
		};
		img.onerror = () => delete this.#images[src];
		img.src = src;
		this.#images[src] = img;
		return img;
	}

	#textPreview(element: TTElement): string {
		if (this.previewData) {
			if (element.field === 'programme_name') return this.previewData.programme_name || 'Programme';
			const feat = this.previewData.features[element.feature_index || 0];
			const value = feat?.[element.field as keyof TTFeature];
			if (value != null && value !== '') return String(value);
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

	// --- Selection & overlay -------------------------------------------------

	#refreshSelection() {
		const single = this.selectedIndices.length === 1;
		const node = single ? this.#nodes[this.selectedIndices[0]] : null;
		const el = single ? this.config.elements[this.selectedIndices[0]] : null;

		if (node && el) {
			this.#tr.nodes([node]);
			this.#tr.resizeEnabled(el.type !== 'text');
			this.#tr.keepRatio(!!el.lock_aspect);
		} else {
			this.#tr.nodes([]);
		}
		this.#drawOverlay();
		this.#host.onChange();
	}

	#drawOverlay(guides: Array<{ axis: 'v' | 'h'; pos: number }> = []) {
		this.#overlay.destroyChildren();

		for (const { axis, pos } of guides) {
			this.#overlay.add(
				new Konva.Line({
					points: axis === 'v' ? [pos, 0, pos, CH] : [0, pos, CW, pos],
					stroke: '#6B8CAE',
					strokeWidth: 2,
					dash: [8, 6]
				})
			);
		}

		// Multi-select: dashed outline per element (single selection is the transformer's job).
		if (this.selectedIndices.length > 1) {
			for (const i of this.selectedIndices) {
				const b = this.getElementBounds(this.config.elements[i]);
				this.#overlay.add(
					new Konva.Rect({
						x: b.x,
						y: b.y,
						width: b.width,
						height: b.height,
						stroke: '#5D8A66',
						strokeWidth: 2,
						dash: [5, 5]
					})
				);
			}
		}

		if (this.#marquee) {
			const p = this.#stage.getRelativePointerPosition();
			if (p) {
				const x = Math.min(this.#marquee.x0, p.x);
				const y = Math.min(this.#marquee.y0, p.y);
				this.#overlay.add(
					new Konva.Rect({
						x,
						y,
						width: Math.abs(p.x - this.#marquee.x0),
						height: Math.abs(p.y - this.#marquee.y0),
						stroke: '#6B8CAE',
						strokeWidth: 2,
						dash: [4, 4],
						fill: 'rgba(107, 140, 174, 0.12)'
					})
				);
			}
		}
	}

	// --- Pointer interaction -------------------------------------------------

	#onNodeClick(i: number, e: Konva.KonvaEventObject<MouseEvent>) {
		// Konva fires 'click' only when no drag happened.
		if (e.evt.shiftKey) this.selectElement(i, true);
		else if (!this.selectedIndices.includes(i)) this.setSelection([i]);
	}

	#onDragStart(i: number) {
		if (!this.selectedIndices.includes(i)) this.setSelection([i]);
		this.snapshot();
		this.#host.onEdited();
		const dragged = this.#nodes[i];
		this.#dragOrigin = { x: dragged.x(), y: dragged.y() };
		this.#dragStart = this.selectedIndices.map((idx) => {
			const n = this.#nodes[idx];
			return { node: n, x: n.x(), y: n.y() };
		});
	}

	#onDragMove(e: Konva.KonvaEventObject<DragEvent>) {
		const idx = (e.target as Konva.Node).getAttr('elIndex') as number;
		let dx = this.#nodes[idx].x() - this.#dragOrigin.x;
		let dy = this.#nodes[idx].y() - this.#dragOrigin.y;

		// Clamp so no element in the group leaves the canvas.
		this.#dragStart.forEach(({ node, x, y }) => {
			const b = this.#nodeSize(node);
			dx = Math.min(Math.max(dx, -x), CW - b.width - x);
			dy = Math.min(Math.max(dy, -y), CH - b.height - y);
		});

		const guides: Array<{ axis: 'v' | 'h'; pos: number }> = [];
		if (!e.evt.shiftKey) {
			const snapped = this.#applySnapping(dx, dy, guides);
			dx = snapped.dx;
			dy = snapped.dy;
		}

		this.#dragStart.forEach(({ node, x, y }) =>
			node.position({ x: Math.round(x + dx), y: Math.round(y + dy) })
		);
		this.#drawOverlay(guides);
	}

	#onDragEnd() {
		this.#dragStart.forEach(({ node }) => {
			const el = this.config.elements[node.getAttr('elIndex') as number];
			el.x = Math.round(node.x());
			el.y = Math.round(node.y());
		});
		this.#dragStart = [];
		this.#drawOverlay();
		this.markDirty();
	}

	#onTransformEnd(node: Konva.Node) {
		const el = this.config.elements[node.getAttr('elIndex') as number];
		const sx = node.scaleX();
		const sy = node.scaleY();
		node.scaleX(1);
		node.scaleY(1);
		el.width = Math.max(20, Math.round((el.width || 100) * sx));
		el.height = Math.max(20, Math.round((el.height || 50) * sy));
		el.x = Math.round(node.x());
		el.y = Math.round(node.y());
		this.render();
		this.markDirty();
	}

	#nodeSize(node: Konva.Node): { width: number; height: number } {
		const el = this.config.elements[node.getAttr('elIndex') as number];
		if (el?.type === 'text') return { width: node.width(), height: node.height() };
		return { width: el?.width || 100, height: el?.height || 50 };
	}

	#applySnapping(
		dx: number,
		dy: number,
		guides: Array<{ axis: 'v' | 'h'; pos: number }>
	): { dx: number; dy: number } {
		const dragged = new Set(this.#dragStart.map((p) => p.node));
		let gx1 = Infinity,
			gy1 = Infinity,
			gx2 = -Infinity,
			gy2 = -Infinity;
		this.#dragStart.forEach(({ node, x, y }) => {
			const b = this.#nodeSize(node);
			gx1 = Math.min(gx1, x + dx);
			gy1 = Math.min(gy1, y + dy);
			gx2 = Math.max(gx2, x + dx + b.width);
			gy2 = Math.max(gy2, y + dy + b.height);
		});
		const gcx = (gx1 + gx2) / 2;
		const gcy = (gy1 + gy2) / 2;

		const vc = [0, CW / 2, CW];
		const hc = [0, CH / 2, CH];
		this.#nodes.forEach((node) => {
			if (dragged.has(node)) return;
			const b = this.#nodeSize(node);
			vc.push(node.x(), node.x() + b.width / 2, node.x() + b.width);
			hc.push(node.y(), node.y() + b.height / 2, node.y() + b.height);
		});

		const snap = (candidates: number[], edges: number[]) => {
			let best: { delta: number; line: number } | null = null;
			for (const line of candidates)
				for (const edge of edges) {
					const delta = line - edge;
					if (Math.abs(delta) <= SNAP && (!best || Math.abs(delta) < Math.abs(best.delta)))
						best = { delta, line };
				}
			return best;
		};

		const v = snap(vc, [gx1, gcx, gx2]);
		const h = snap(hc, [gy1, gcy, gy2]);
		if (v) {
			dx += v.delta;
			guides.push({ axis: 'v', pos: v.line });
		}
		if (h) {
			dy += h.delta;
			guides.push({ axis: 'h', pos: h.line });
		}
		return { dx, dy };
	}

	#onStageDown(e: Konva.KonvaEventObject<MouseEvent>) {
		if (e.target !== this.#stage) return; // a node handles its own press
		const p = this.#stage.getRelativePointerPosition();
		if (!p) return;
		this.#marquee = { x0: p.x, y0: p.y, additive: e.evt.shiftKey };
	}

	#onStageMove() {
		if (this.#marquee) this.#drawOverlay();
	}

	#onStageUp() {
		if (!this.#marquee) return;
		const p = this.#stage.getRelativePointerPosition();
		const m = this.#marquee;
		this.#marquee = null;
		if (!p) {
			this.#drawOverlay();
			return;
		}
		const moved = Math.abs(p.x - m.x0) > 3 || Math.abs(p.y - m.y0) > 3;
		if (moved) {
			const x = Math.min(m.x0, p.x),
				y = Math.min(m.y0, p.y);
			const x2 = Math.max(m.x0, p.x),
				y2 = Math.max(m.y0, p.y);
			const hits: number[] = [];
			this.config.elements.forEach((el, i) => {
				const b = this.getElementBounds(el);
				if (b.x < x2 && b.x + b.width > x && b.y < y2 && b.y + b.height > y) hits.push(i);
			});
			this.setSelection(m.additive ? [...this.selectedIndices, ...hits] : hits);
		} else if (!m.additive) {
			this.setSelection([]);
		} else {
			this.#drawOverlay();
		}
	}

	#onContextMenu(e: Konva.KonvaEventObject<MouseEvent>) {
		e.evt.preventDefault();
		if (e.target === this.#stage) return;
		const i = (e.target as Konva.Node).getAttr('elIndex') as number;
		if (i == null) return;
		if (!this.selectedIndices.includes(i)) this.setSelection([i]);
		this.#host.onContextMenu(e.evt.clientX, e.evt.clientY, i);
	}

	// --- Align / distribute --------------------------------------------------

	selectionBounds() {
		const bs = this.selectedIndices.map((i) => this.getElementBounds(this.config.elements[i]));
		const minX = Math.min(...bs.map((b) => b.x));
		const minY = Math.min(...bs.map((b) => b.y));
		const maxX = Math.max(...bs.map((b) => b.x + b.width));
		const maxY = Math.max(...bs.map((b) => b.y + b.height));
		return { minX, minY, maxX, maxY, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 };
	}

	get alignArea() {
		if (this.alignAreaMode === 'canvas')
			return { minX: 0, minY: 0, maxX: CW, maxY: CH, cx: CW / 2, cy: CH / 2 };
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
			hi = horiz ? CW : CH;
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
			const sum = sorted.reduce((s, it) => s + it.size, 0);
			const gap = sorted.length > 1 ? (hi - lo - sum) / (sorted.length - 1) : 0;
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
