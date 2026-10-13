<script lang="ts">
	import { page } from '$app/state';
	const quotaExceeded = $derived(page.error?.code === 'DATABASE_QUOTA_EXCEEDED');
</script>

<svelte:head><title>lfm · No se pudo cargar</title></svelte:head>

<section class="mx-auto max-w-md py-12">
	<h1 class="text-2xl font-semibold">{quotaExceeded ? 'Base de datos suspendida' : page.status === 404 ? 'No encontramos esta página' : 'No pudimos cargar los datos'}</h1>
	<p class="text-muted mt-3 text-sm leading-relaxed">
		{quotaExceeded ? 'Neon ha bloqueado el acceso por una cuota agotada. Hay que recuperar el servicio desde su panel; recargar la página no desbloquea la base de datos.' : page.status === 404 ? 'El enlace puede haber cambiado. Vuelve al inicio para seguir consultando tu liga.' : 'La conexión con los datos ha fallado. Vuelve a intentarlo en unos segundos.'}
	</p>
	{#if quotaExceeded}
		<p class="text-muted mt-3 text-sm leading-relaxed">Cuando Neon vuelva a aceptar conexiones, podrás consultar los datos de nuevo. Mientras tanto, las actualizaciones también están detenidas.</p>
	{/if}
	<div class="mt-6 flex flex-wrap gap-3">
		<button class="bg-accent text-bg min-h-11 rounded-lg px-4 text-sm font-semibold" onclick={() => window.location.reload()}>{quotaExceeded ? 'Comprobar de nuevo' : 'Volver a intentar'}</button>
		<a href="/" class="border-line min-h-11 rounded-lg border px-4 py-3 text-sm">Ir al inicio</a>
	</div>
</section>
