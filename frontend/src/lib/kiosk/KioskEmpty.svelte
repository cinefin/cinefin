<script lang="ts">
	interface Props {
		title: string;
		sub: string;
	}
	let { title, sub }: Props = $props();
</script>

<div class="kiosk-empty">
	<div class="empty-mark" aria-hidden="true"><span></span><span></span><span></span></div>
	<h2>{title}</h2>
	<p>{sub}</p>
</div>
