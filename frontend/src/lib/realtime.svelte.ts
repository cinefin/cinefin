/**
 * The single real-time WebSocket the whole SPA shares (/ws/events) — replaces three always-on
 * SSE streams that would each eat one of the browser's ~6 connections per host. Opens on the
 * first subscriber, closes on the last, reconnects with backoff; `onConnect` fires on every
 * (re)connection so a consumer can reconcile against the DB after a gap.
 */
import { browser } from '$app/environment';

export interface RealtimeMessage {
	channel: string;
	[key: string]: unknown;
}

interface Sub {
	channel: string;
	onMessage: (msg: RealtimeMessage) => void;
	onConnect?: () => void;
}

class Realtime {
	/** True while the socket is open. */
	connected = $state(false);

	#subs = new Set<Sub>();
	#ws: WebSocket | null = null;
	#retry: ReturnType<typeof setTimeout> | null = null;
	#backoff = 1000;

	subscribe(sub: Sub): () => void {
		this.#subs.add(sub);
		if (this.#subs.size === 1) this.#open();
		else if (this.connected) sub.onConnect?.();
		return () => {
			this.#subs.delete(sub);
			if (this.#subs.size === 0) this.#close();
		};
	}

	#open(): void {
		if (!browser || this.#ws) return;
		const proto = location.protocol === 'https:' ? 'wss' : 'ws';
		const ws = new WebSocket(`${proto}://${location.host}/ws/events`);
		this.#ws = ws;
		ws.onopen = () => {
			this.#backoff = 1000;
			this.connected = true;
			for (const s of this.#subs) s.onConnect?.();
		};
		ws.onmessage = (e) => {
			let msg: RealtimeMessage;
			try {
				msg = JSON.parse(e.data);
			} catch {
				return;
			}
			if (msg.channel === 'ping') return;
			for (const s of this.#subs) if (s.channel === msg.channel) s.onMessage(msg);
		};
		ws.onclose = () => {
			this.connected = false;
			this.#ws = null;
			if (this.#subs.size) this.#reopenLater();
		};
		ws.onerror = () => {
			try {
				ws.close();
			} catch {
				/* onclose handles the retry */
			}
		};
	}

	#reopenLater(): void {
		if (this.#retry) return;
		this.#retry = setTimeout(() => {
			this.#retry = null;
			if (this.#subs.size) this.#open();
		}, this.#backoff);
		this.#backoff = Math.min(this.#backoff * 2, 30_000);
	}

	#close(): void {
		if (this.#retry) {
			clearTimeout(this.#retry);
			this.#retry = null;
		}
		this.connected = false;
		if (this.#ws) {
			const ws = this.#ws;
			this.#ws = null;
			ws.onclose = null; // deliberate close — don't reconnect
			ws.close();
		}
	}
}

export const realtime = new Realtime();
