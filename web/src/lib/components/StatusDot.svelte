<script lang="ts">
	import { STATUS } from '$lib/format';
	let { status, class: cls = '' }: { status: string | null | undefined; class?: string } = $props();
	const s = $derived(STATUS[status ?? ''] ?? STATUS.ok);
</script>

<span class="bg-bg inline-block h-3.5 w-3.5 rounded-full p-0.5 {cls}" title={s.label}>
	<span class="block h-full w-full rounded-full {s.dot}"></span>
</span>
