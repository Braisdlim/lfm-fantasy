<script lang="ts">
	import { pct, pctText, signed } from '$lib/format';
	let {
		now,
		before,
		showPct = true,
		size = 'text-sm'
	}: { now: number | null | undefined; before: number | null | undefined; showPct?: boolean; size?: string } = $props();
	const diff = $derived(now != null && before != null ? now - before : null);
	const cls = $derived(diff == null ? 'text-muted' : diff > 0 ? 'text-up' : diff < 0 ? 'text-down' : 'text-muted');
</script>

<span class="num {cls} {size} whitespace-nowrap">
	{signed(diff)}{#if showPct && diff != null}<span class="opacity-70"> · {pctText(pct(now, before))}</span>{/if}
</span>
