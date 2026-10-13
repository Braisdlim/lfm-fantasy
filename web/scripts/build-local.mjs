// Compila cliente y servidor sin crear los symlinks de Vercel, que en Windows
// requieren permisos especiales. El despliegue sigue usando `npm run build`.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const result = spawnSync(process.execPath, [fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url)), 'build'], {
	cwd: fileURLToPath(new URL('..', import.meta.url)),
	stdio: 'inherit',
	env: { ...process.env, LFM_LOCAL_BUILD: '1' }
});
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
