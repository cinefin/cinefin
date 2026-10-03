/**
 * The single real-time WebSocket the whole SPA shares (/ws/events) — replaces three always-on
 * SSE streams that would each eat one of the browser's ~6 connections per host. Opens on the
 * first subscriber, closes on the last, reconnects with backoff; `onConnect` fires on every
 * (re)connection so a consumer can reconcile against the DB after a gap. The server pings every
 * 15 s, so a socket silent for SILENCE_MS is taken for dead (a half-open link never closes).
 */
import { browser } from '$app/environment';

export interface RealtimeMessage {
	channel: string;
	[key: string]: unknown;
}

const SILENCE_MS = 40_000;
// Lost this long before `down`: a quick reconnect shouldn't flash the whole app.
const GRACE_MS = 4_000;

interface Sub {
	channel: string;
	onMessage: (msg: RealtimeMessage) => void;
	onConnect?: () => void;
}

class Realtime {
	/** True while the socket is open. */
	connected = $state(false);
	/** Cinefin can't be reached: the socket has been closed or silent for a few seconds. */
	down = $state(false);
	/** When the server was last heard from, set when the link is lost. */
	lastSeen = $state<number | null>(null);

	#subs = new Set<Sub>();
	#ws: WebSocket | null = null;
	#retry: ReturnType<typeof setTimeout> | null = null;
	#backoff = 1000;
	#lastRx = 0;
	#lostAt: ReturnType<typeof setTimeout> | null = null;
	#watchdog: ReturnType<typeof setInterval> | null = null;

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
			this.#lastRx = Date.now();
			this.connected = true;
			this.#found();
			this.#watchdog ??= setInterval(() => {
				if (this.#ws && this.connected && Date.now() - this.#lastRx > SILENCE_MS) this.#lost();
			}, 5_000);
			for (const s of this.#subs) s.onConnect?.();
		};
		ws.onmessage = (e) => {
			this.#lastRx = Date.now();
			let msg: RealtimeMessage;
			try {
				msg = JSON.parse(e.data);
			} catch {
				return;
			}
			if (msg.channel === 'ping') return;
			for (const s of this.#subs) if (s.channel === msg.channel) s.onMessage(msg);
		};
		ws.onclose = () => this.#lost();
		ws.onerror = () => {
			try {
				ws.close();
			} catch {
				/* onclose handles the retry */
			}
		};
	}

	/** The link is gone (closed, or silent too long): drop it, retry, and say so after GRACE_MS. */
	#lost(): void {
		const ws = this.#ws;
		this.#ws = null;
		this.connected = false;
		if (ws) {
			ws.onclose = null;
			ws.close();
		}
		if (!this.#lostAt && !this.down) {
			this.lastSeen = this.#lastRx || null;
			this.#lostAt = setTimeout(() => (this.down = true), GRACE_MS);
		}
		if (this.#subs.size) this.#reopenLater();
	}

	#found(): void {
		if (this.#lostAt) clearTimeout(this.#lostAt);
		this.#lostAt = null;
		this.down = false;
		this.lastSeen = null;
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
		if (this.#watchdog) clearInterval(this.#watchdog);
		this.#watchdog = null;
		this.#found();
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
