// Exercise the real seeded application, without game accounts or production data.
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const base = process.env.DEMO_URL ?? 'http://localhost:5173';
const capture = process.env.CAPTURE_SCREENSHOTS === '1';
const output = fileURLToPath(new URL('../../docs/screenshots/', import.meta.url));
if (capture) await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1100, height: 960 }, deviceScaleFactor: 1 });
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
let checked = 0;

async function screenshot(name) {
	if (!capture) return;
	const bounds = await page.locator('main').boundingBox();
	await page.screenshot({ path: `${output}/${name}.png`, clip: {
		x: Math.floor(bounds.x), y: 0, width: Math.ceil(bounds.width), height: page.viewportSize().height
	} });
}

async function visit(path, screenshot) {
	const response = await page.goto(`${base}${path}`, { waitUntil: 'networkidle' });
	assert.equal(response.status(), 200, `GET ${path}`);
	assert.match(await page.locator('main').innerText(), /datos deportivos reales/);
	assert.equal(await page.locator('h1').count(), 1, `heading on ${path}`);
	checked++;
	if (screenshot) await screenshotPage(screenshot);
}

const screenshotPage = screenshot;

try {
	await visit('/', 'home');
	await visit('/mercado', 'market');
	await visit('/plantilla');
	await page.getByRole('button', { name: /Once ·/ }).click();
	await page.getByRole('heading', { name: 'Tu once', exact: true }).waitFor();
	assert.match(await page.locator('main').innerText(), /última alineación capturada/);
	await page.setViewportSize({ width: 1100, height: 1280 });
	await screenshot('eleven');
	await page.setViewportSize({ width: 1100, height: 960 });
	const squadLinks = await page.locator('main a[href^="/jugador/"]').evaluateAll((links) =>
		links.map((link) => ({ href: link.getAttribute('href'), name: link.textContent })));
	const examplePlayer = squadLinks.find((link) => /Pedri|Mbapp|Vinicius|Güler|Moleiro/.test(link.name)) ?? squadLinks[0];
	assert.ok(examplePlayer, 'real player in the squad');
	await visit(examplePlayer.href, 'player');
	await visit('/jornada');
	await visit('/liga');
	await visit('/liga/demo-team-2');
	await visit('/diario');
	await visit('/seguimiento');
	await visit(`/comparar?a=${squadLinks[0].href.split('/').at(-1)}&b=${squadLinks[1].href.split('/').at(-1)}`);
	await visit('/buscar');
	await page.getByRole('searchbox').first().fill('Mbapp');
	await page.getByRole('link').filter({ hasText: /Mbapp/ }).first().waitFor();
	await visit('/planificar');
	await page.getByRole('button', { name: 'Añadir', exact: true }).first().click();
	await page.getByText(/Ventas supuestas/).waitFor();
	assert.match(await page.locator('main').innerText(), /Saldo tras el plan/);
	await screenshot('planner');
	const mutation = await page.request.post(`${base}/seguimiento`, { form: { player_id: 'demo-049' } });
	assert.equal(mutation.status(), 405, 'demo rejects persistence');
	await page.setViewportSize({ width: 390, height: 844 });
	await visit('/', 'mobile');
	const dimensions = await page.evaluate(() => ({ width: document.documentElement.clientWidth,
		content: document.documentElement.scrollWidth }));
	assert.equal(dimensions.content, dimensions.width, 'mobile has no horizontal overflow');
	assert.deepEqual(errors, [], 'no client runtime errors');
	console.log(JSON.stringify({ routes: checked, readOnly: true, mobileOverflow: false, clientErrors: 0 }));
} finally {
	await browser.close();
}
