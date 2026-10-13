<script lang="ts">
	import type { ActionData } from './$types';
	let { form }: { form: ActionData } = $props();
</script>

<svelte:head><title>lfm · acceso</title></svelte:head>

<main class="mx-auto flex min-h-dvh max-w-sm flex-col justify-center gap-6 px-6">
	<div>
		<h1 class="text-3xl font-bold tracking-tight">lfm</h1>
		<p class="text-muted mt-1">Tu LaLiga Fantasy, con memoria.</p>
	</div>
	<form method="POST" class="card flex flex-col gap-3 p-4">
		<label class="text-muted text-sm" for="password">Clave de acceso</label>
		<input
			id="password"
			name="password"
			type="password"
			autocomplete="current-password"
			class="bg-surface-2 border-line focus:border-accent rounded-xl border px-3 py-3 outline-none"
			required
		/>
		{#if form?.wrong}<p class="text-down text-sm">Clave incorrecta.</p>{/if}
		<button class="bg-accent rounded-xl py-3 font-semibold text-black">Entrar</button>
	</form>
</main>
