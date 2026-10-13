<script lang="ts">
	// Barra de resultado. No lleva números dentro: a 375 px no caben tres cifras legibles dentro de
	// las franjas, y quedaban montadas unas sobre otras. Los números van en la frase de al lado.
	let { local, draw, visitor }: { local: number; draw: number; visitor: number } = $props();
	const w = (x: number) => `${Math.max(0, Math.round(x * 1000) / 10)}%`;
</script>

<div class="bg-surface-2 flex h-1.5 overflow-hidden rounded-full" aria-hidden="true">
	<div class="bg-accent" style="width: {w(local)}"></div>
	<div class="bg-muted/50" style="width: {w(draw)}"></div>
	<div class="bg-warn" style="width: {w(visitor)}"></div>
</div>
