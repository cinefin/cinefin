<script lang="ts">
	import type { KioskController } from './controller.svelte';

	interface Props {
		kiosk: KioskController;
	}
	let { kiosk }: Props = $props();
</script>

<div class="night">
	<div class="night-clock">{kiosk.headerClockText}</div>
</div>
