<script lang="ts">
	let { title, sub }: { title: string; sub: string } = $props();
</script>

<div class="kiosk-empty">
	<div class="empty-mark" aria-hidden="true"><span></span><span></span><span></span></div>
	<h2>{title}</h2>
	<p>{sub}</p>
</div>
