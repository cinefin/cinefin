<script lang="ts">
	/**
	 * Add a player: find it on the network (or by address) and name it, pair it
	 * with the code on its screen, check its screen and sound with the test card
	 * and test sound, then finish (status line, active player). Settings ›
	 * Playout shows it in a Dialog; the setup wizard's "Connect the player" step
	 * shows it inline. `start` opens it at Pair for a player that needs pairing
	 * again.
	 */
	import { onDestroy, untrack } from 'svelte';
	import { ArrowLeft, ArrowRight, Check, MonitorPlay, RefreshCw, Volume2 } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import type { components } from '$lib/api/types.gen';
	import Button from '$lib/components/ui/Button.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Toggle from '$lib/components/ui/Toggle.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Logo from '$lib/components/shell/Logo.svelte';
	import Stepper from '$lib/programmes/create-Stepper.svelte';
	import Field from '$lib/settings/Field.svelte';
	import CodeInput from './CodeInput.svelte';
	import HostConfigFields from './HostConfigFields.svelte';
	import {
		describeConfig,
		loadHostConfig,
		saveHostConfig,
		type Hardware,
		type LaunchConfig
	} from './host-config';
	import {
		CODE_LENGTH,
		STEPS,
		nameFromAddress,
		pairError,
		soundingAt,
		stepEnabled,
		type SoundStep,
		type StepId
	} from './wizard';

	type Found = components['schemas']['DiscoveredPlayerSchema'];
	type Host = components['schemas']['PlayoutHostSchema'];

	interface Props {
		/** A known player to pair again: the wizard opens at Pair. */
		start?: { base_url: string; name: string };
		/** Called as soon as pairing succeeds (the host exists from then on). */
		onpaired?: (host: Host) => void;
		/** Called by Finish, with the host as it now is. */
		onfinish: (host: Host) => void;
		/** Shows a Cancel button on the first step. */
		oncancel?: () => void;
	}
	let { start, onpaired, onfinish, oncancel }: Props = $props();

	let step = $state<StepId>(untrack(() => (start ? 'pair' : 'find')));
	let host = $state<Host | null>(null);

	// ── Find and name ────────────────────────────────────────────────────
	let found = $state<Found[] | null>(null);
	let scanning = $state(false);
	// Kept as picked, so a later scan that misses it does not drop the choice.
	let picked = $state<Found | null>(null);
	let address = $state(untrack(() => start?.base_url ?? ''));
	let name = $state(untrack(() => start?.name ?? ''));
	let nameEdited = untrack(() => !!start);

	const target = $derived(picked ? picked.base_url : address.trim());
	const chosen = $derived(!!target && !!name.trim());

	async function scan() {
		scanning = true;
		try {
			found = await unwrap(api.GET('/api/v2/playout/discover'));
		} catch {
			found = found ?? [];
		} finally {
			scanning = false;
		}
	}

	// Keep looking while on this step: a player appears a few seconds after it starts.
	$effect(() => {
		if (step !== 'find') return;
		let stopped = false;
		let timer: ReturnType<typeof setTimeout>;
		const loop = async () => {
			await scan();
			if (!stopped) timer = setTimeout(loop, 5000);
		};
		untrack(() => void loop());
		return () => {
			stopped = true;
			clearTimeout(timer);
		};
	});

	function pick(p: Found) {
		picked = p;
		address = '';
		if (!nameEdited) name = p.name;
	}

	function typeAddress() {
		picked = null;
		if (!nameEdited) name = nameFromAddress(address);
	}

	// ── Pair ─────────────────────────────────────────────────────────────
	let code = $state('');
	let pairing = $state(false);
	let pairMessage = $state('');
	let codeInput = $state<CodeInput>();

	async function pair() {
		if (pairing) return;
		if (code.length !== CODE_LENGTH) {
			pairMessage = "Enter the 6-digit code from the player's screen.";
			return;
		}
		pairing = true;
		pairMessage = '';
		try {
			host = await unwrap(
				api.POST('/api/v2/playout/hosts/pair', {
					body: { base_url: target, code, name: name.trim() }
				})
			);
			showStatus = host.show_status ?? true;
			makeActive = host.is_active;
			onpaired?.(host);
			go('screen');
		} catch (e) {
			pairMessage = pairError(e);
			code = '';
			codeInput?.focus();
		} finally {
			pairing = false;
		}
	}

	// ── Screen and sound ─────────────────────────────────────────────────
	let config = $state<LaunchConfig | null>(null);
	let hardware = $state<Hardware | null>(null);
	let savedConfig = $state('');
	let configError = $state<string | null>(null);
	let applying = $state(false);
	let cardOn = $state(false);
	let cardBusy = $state(false);
	let checkMessage = $state('');
	let sounding = $state<'left' | 'right' | null>(null);
	let soundPlaying = $state(false);
	let soundTimer: ReturnType<typeof setInterval> | undefined;

	const dirty = $derived(!!config && JSON.stringify(config) !== savedConfig);

	async function loadConfig() {
		if (!host) return;
		configError = null;
		try {
			({ config, hardware } = await loadHostConfig(host.id));
			savedConfig = JSON.stringify(config);
		} catch (e) {
			configError = e instanceof Error ? e.message : String(e);
		}
	}

	$effect(() => {
		if (step === 'screen' && !untrack(() => config)) void untrack(loadConfig);
	});

	const hostPath = () => ({ params: { path: { host_id: host!.id } } });

	async function setCard(on: boolean) {
		if (!host) return;
		cardBusy = true;
		checkMessage = '';
		try {
			const r = await unwrap(
				api.POST('/api/v2/playout/hosts/{host_id}/testcard', { ...hostPath(), body: { on } })
			);
			cardOn = r.on;
		} catch (e) {
			if (on) checkMessage = e instanceof Error ? e.message : 'The player did not answer.';
			else cardOn = false;
		} finally {
			cardBusy = false;
		}
	}

	async function playSound() {
		if (!host || soundPlaying) return;
		checkMessage = '';
		soundPlaying = true;
		try {
			const r = await unwrap(api.POST('/api/v2/playout/hosts/{host_id}/testsound', hostPath()));
			const sequence = r.sequence as SoundStep[];
			const began = performance.now();
			const tick = () => {
				const elapsed = performance.now() - began;
				sounding = soundingAt(sequence, elapsed);
				if (elapsed >= (r.duration_ms ?? 0)) stopSound();
			};
			tick();
			soundTimer = setInterval(tick, 100);
		} catch (e) {
			checkMessage = e instanceof Error ? e.message : 'The player did not answer.';
			soundPlaying = false;
		}
	}

	function stopSound() {
		clearInterval(soundTimer);
		sounding = null;
		soundPlaying = false;
	}

	// Save the choices and restart the player, so the test card and the test
	// sound show them.
	async function apply(): Promise<boolean> {
		if (!host || !config) return false;
		applying = true;
		checkMessage = '';
		try {
			await saveHostConfig(host.id, config, true);
			savedConfig = JSON.stringify(config);
			if (cardOn) void setCard(true); // the restarted player draws it again
			return true;
		} catch (e) {
			checkMessage = e instanceof Error ? e.message : 'Could not save.';
			return false;
		} finally {
			applying = false;
		}
	}

	// ── Finish ───────────────────────────────────────────────────────────
	let showStatus = $state(true);
	let makeActive = $state(false);
	let finishing = $state(false);
	let finishMessage = $state('');
	const summary = $derived(config ? describeConfig(config, hardware) : null);

	async function finish() {
		if (!host) return;
		finishing = true;
		finishMessage = '';
		try {
			if (showStatus !== host.show_status) {
				host = await unwrap(
					api.PATCH('/api/v2/playout/hosts/{host_id}', {
						...hostPath(),
						body: { show_status: showStatus }
					})
				);
			}
			if (makeActive && !host.is_active) {
				host = await unwrap(api.POST('/api/v2/playout/hosts/{host_id}/activate', hostPath()));
			}
			onfinish(host);
		} catch (e) {
			finishMessage = e instanceof Error ? e.message : 'Could not finish.';
		} finally {
			finishing = false;
		}
	}

	// ── Moving between steps ─────────────────────────────────────────────
	function go(next: StepId) {
		// The test card is for this step only.
		if (step === 'screen' && next !== 'screen' && cardOn) void setCard(false);
		step = next;
		if (next === 'pair') {
			pairMessage = '';
			code = '';
			setTimeout(() => codeInput?.focus());
		}
	}

	async function next() {
		if (step === 'find' && chosen) go('pair');
		else if (step === 'pair') await pair();
		else if (step === 'screen' && (!dirty || (await apply()))) go('finish');
		else if (step === 'finish') await finish();
	}

	// Opened to pair a known player again: straight to the code.
	$effect(() => {
		if (start) untrack(() => codeInput?.focus());
	});

	onDestroy(() => {
		clearInterval(soundTimer);
		if (cardOn) void setCard(false);
	});

	const current = $derived(STEPS.findIndex((s) => s.id === step));
	const steps = $derived(
		STEPS.map((s, i) => ({
			...s,
			enabled: stepEnabled(s.id, { chosen, paired: !!host }),
			done: i < current
		}))
	);
	const nextLabel = $derived(
		step === 'pair'
			? pairing
				? 'Pairing…'
				: 'Pair'
			: step === 'finish'
				? finishing
					? 'Finishing…'
					: 'Finish'
				: applying
					? 'Saving…'
					: 'Next'
	);
	const nextDisabled = $derived(
		(step === 'find' && !chosen) ||
			(step === 'pair' && (pairing || code.length !== CODE_LENGTH)) ||
			(step === 'screen' && (applying || !config)) ||
			(step === 'finish' && finishing)
	);
</script>

<div class="space-y-5">
	<Stepper {steps} current={step} compact onselect={(id) => go(id as StepId)} />

	{#if step === 'find'}
		<section class="space-y-4">
			<div>
				<h3 class="text-base font-medium">Find the player</h3>
				<p class="mt-1 text-sm text-muted">
					Start <code class="font-mono text-[0.8rem]">cinefin-playout</code> on the machine connected
					to your screen. When it is ready, the screen shows the Cinefin ident and a pairing code.
				</p>
			</div>

			<div class="space-y-2">
				<div class="flex items-center justify-between gap-3">
					<p class="text-xs font-medium text-muted">Found on your network</p>
					<Button size="sm" variant="ghost" disabled={scanning} onclick={() => void scan()}>
						<RefreshCw size={13} />
						{scanning ? 'Looking…' : 'Look again'}
					</Button>
				</div>
				{#if found === null}
					<Spinner size="sm" label="Looking for players…" />
				{:else}
					<ul class="space-y-1.5">
						{#each found as p (p.id)}
							{@const elsewhere = p.paired && p.host_id == null}
							{@const added = p.paired && p.host_id != null}
							{@const on = p.id === picked?.id}
							<li>
								<button
									type="button"
									disabled={p.paired}
									aria-pressed={on}
									class="flex w-full items-center gap-3 border px-3 py-2.5 text-left
										disabled:cursor-not-allowed
										{on
										? 'border-accent bg-surface-2'
										: 'border-border bg-surface-1 enabled:hover:border-border-strong'}"
									onclick={() => pick(p)}
								>
									<span class="min-w-0 flex-1">
										<span class="block text-sm font-medium {p.paired ? 'text-muted' : ''}"
											>{p.name}</span
										>
										<span class="block font-mono text-xs break-all text-faint">
											{p.base_url}{p.version ? ` · ${p.version}` : ''}
										</span>
									</span>
									{#if elsewhere}
										<span class="shrink-0 text-xs text-muted">Paired elsewhere</span>
									{:else if added}
										<StatusLamp colour="green" quiet>Added</StatusLamp>
									{:else if on}
										<Check size={16} class="shrink-0 text-accent" />
									{/if}
								</button>
							</li>
						{/each}
					</ul>
					<p class="text-xs text-muted">
						{found.length
							? 'Still looking. A player appears here a few seconds after it starts.'
							: 'None yet. A player appears here a few seconds after it starts. If Cinefin runs in Docker it cannot see the network: add the player by address.'}
					</p>
				{/if}
			</div>

			<Field label="Or add it by address, as shown under the pairing code" forId="wiz-address">
				<Input
					id="wiz-address"
					bind:value={address}
					oninput={typeAddress}
					placeholder="10.0.0.5 or http://10.0.0.5:8089"
					class="font-mono"
				/>
			</Field>

			<Field
				label="Player name"
				forId="wiz-name"
				hint="Shown in Cinefin, and on the player's test card and status line."
			>
				<Input
					id="wiz-name"
					bind:value={name}
					oninput={() => (nameEdited = true)}
					placeholder="Living room"
				/>
			</Field>
		</section>
	{:else if step === 'pair'}
		<section class="space-y-4">
			<div>
				<h3 class="text-base font-medium">Enter the code on the screen</h3>
				<p class="mt-1 text-sm text-muted">
					{name.trim() || 'The player'} shows a six-digit code over the Cinefin ident.
				</p>
			</div>
			<div class="flex flex-col gap-5 sm:flex-row sm:items-start">
				<div class="min-w-0 flex-1 space-y-3">
					<CodeInput
						bind:this={codeInput}
						bind:value={code}
						invalid={!!pairMessage}
						disabled={pairing}
						oncomplete={() => void pair()}
					/>
					{#if pairMessage}
						<p class="text-sm text-danger" role="alert">{pairMessage}</p>
					{:else}
						<p class="text-xs text-muted">
							The code changes every 5 minutes and after a wrong try. The screen always shows the
							current one.
						</p>
					{/if}
				</div>
				<!-- What the screen shows: the ident with the pairing box over it. -->
				<figure class="w-full max-w-60 shrink-0 space-y-1.5" aria-hidden="true">
					<div
						class="relative flex aspect-video flex-col items-center justify-center gap-[8%] overflow-hidden border border-border bg-black [--color-text:white]"
					>
						<Logo markClass="h-6" wordmark />
						<div
							class="flex w-[70%] items-center gap-2 border border-white/30 bg-white/5 px-2 py-1.5 text-white"
						>
							<span class="font-mono text-sm leading-none">••• •••</span>
							<span class="h-4 w-px bg-white/30"></span>
							<span class="text-[0.45rem] leading-tight text-white/70"
								>In Cinefin, go to Settings › Playout and enter this code</span
							>
						</div>
					</div>
					<figcaption class="text-xs text-faint">What the screen shows</figcaption>
				</figure>
			</div>
		</section>
	{:else if step === 'screen'}
		<section class="space-y-4">
			<div>
				<h3 class="text-base font-medium">Screen and sound</h3>
				<p class="mt-1 text-sm text-muted">
					Paired with {host?.name}. Check the picture and sound now; you can change these later in
					Settings › Playout.
				</p>
			</div>
			{#if configError}
				<ErrorState compact message={configError} retry={() => void loadConfig()} />
			{:else if !config}
				<Spinner size="sm" label="Reading the player's screens and sound outputs…" />
			{:else}
				<HostConfigFields bind:config {hardware} idPrefix="wiz">
					{#snippet screenAction()}
						<Button
							disabled={cardBusy}
							class={cardOn ? 'border-success/50 text-success' : ''}
							onclick={() => void setCard(!cardOn)}
						>
							<MonitorPlay size={14} />
							<span aria-live="polite">{cardOn ? 'Test card on · Hide' : 'Show test card'}</span>
						</Button>
					{/snippet}
					{#snippet soundAction()}
						<Button disabled={soundPlaying} onclick={() => void playSound()}>
							<Volume2 size={14} />
							{soundPlaying ? 'Playing…' : 'Play test sound'}
						</Button>
					{/snippet}
				</HostConfigFields>

				<div
					class="flex flex-wrap items-center gap-3 border border-border bg-surface-2 px-3 py-2.5"
				>
					<p class="min-w-0 flex-1 text-xs text-muted">
						{cardOn
							? "The screen shows a test card with this player's name. Check it is the right screen and the corner marks are not cut off."
							: 'The test card shows the player name and corner marks on the screen.'}
						The test sound plays on the left, then the right.
					</p>
					<div class="flex gap-1.5" aria-live="polite">
						{#each ['left', 'right'] as side (side)}
							<span
								class="border px-2 py-1 text-xs {sounding === side
									? 'border-accent bg-accent/15 text-text'
									: 'border-border text-faint'}"
							>
								{side === 'left' ? 'Left' : 'Right'}<span class="sr-only"
									>{sounding === side ? ' sounding' : ''}</span
								>
							</span>
						{/each}
					</div>
				</div>
				{#if dirty}
					<div class="flex flex-wrap items-center gap-2">
						<Button disabled={applying} onclick={() => void apply()}>
							<RefreshCw size={13} />
							{applying ? 'Restarting…' : 'Apply and restart the player'}
						</Button>
						<span class="text-xs text-muted">So the test card and test sound use your choices.</span
						>
					</div>
				{/if}
				{#if checkMessage}
					<p class="text-sm text-danger" role="alert">{checkMessage}</p>
				{/if}
			{/if}
		</section>
	{:else if step === 'finish'}
		<section class="space-y-4">
			<div>
				<h3 class="text-base font-medium">Finish</h3>
				<p class="mt-1 text-sm text-muted">{host?.name} is ready.</p>
			</div>
			<div class="space-y-3">
				<Toggle
					label="Show the status line on standby"
					bind:checked={showStatus}
					hint="The cinema name, this player's name and its connection, over the ident."
				/>
				<Toggle
					label="Use as the active player"
					bind:checked={makeActive}
					disabled={host?.is_active}
					hint={host?.is_active
						? 'It is your only player, so Cinefin already plays through it.'
						: 'Cinefin plays through one player at a time. Switching stops anything playing on the current one.'}
				/>
			</div>
			{#if summary}
				<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 border-t border-border pt-3 text-sm">
					<dt class="text-muted">Display</dt>
					<dd>{summary.screen}</dd>
					<dt class="text-muted">Sound</dt>
					<dd>{summary.sound}</dd>
				</dl>
			{/if}
			{#if finishMessage}
				<p class="text-sm text-danger" role="alert">{finishMessage}</p>
			{/if}
		</section>
	{/if}

	<div class="flex items-center justify-between gap-2 border-t border-border pt-4">
		{#if step === 'pair' && !start}
			<Button variant="ghost" onclick={() => go('find')}><ArrowLeft size={14} /> Back</Button>
		{:else if step === 'finish'}
			<Button variant="ghost" onclick={() => go('screen')}><ArrowLeft size={14} /> Back</Button>
		{:else if step === 'find' && oncancel}
			<Button variant="ghost" onclick={oncancel}>Cancel</Button>
		{:else}
			<span></span>
		{/if}
		<Button variant="primary" disabled={nextDisabled} onclick={() => void next()}>
			{#if step === 'finish'}<Check size={14} />{/if}
			{nextLabel}
			{#if step !== 'finish'}<ArrowRight size={14} />{/if}
		</Button>
	</div>
</div>
