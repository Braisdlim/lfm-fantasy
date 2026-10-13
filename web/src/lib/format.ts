// Formato de cifras y fechas en español. Todo lo que se muestra pasa por aquí.

const es = 'es-ES';

export function money(n: number | null | undefined, digits = 1): string {
	if (n == null || Number.isNaN(n)) return '–';
	const abs = Math.abs(n);
	if (abs >= 1e6) return `${(n / 1e6).toLocaleString(es, { minimumFractionDigits: digits, maximumFractionDigits: digits })} M`;
	if (abs >= 1e3) return `${Math.round(n / 1e3).toLocaleString(es)} k`;
	// Sin la unidad, «se lo lleva 114 por debajo del valor» no dice nada: ¿114 qué?
	return `${n.toLocaleString(es)} €`;
}

export function signed(n: number | null | undefined, digits = 1): string {
	if (n == null) return '–';
	return (n > 0 ? '+' : n < 0 ? '−' : '') + money(Math.abs(n), digits);
}

export function pct(now: number | null | undefined, before: number | null | undefined): number | null {
	if (now == null || before == null || !before) return null;
	return ((now - before) / before) * 100;
}

export function pctText(p: number | null): string {
	if (p == null) return '';
	return `${p > 0 ? '+' : p < 0 ? '−' : ''}${Math.abs(p).toLocaleString(es, { maximumFractionDigits: 1 })} %`;
}

export const POS: Record<number, string> = { 1: 'POR', 2: 'DEF', 3: 'MED', 4: 'DEL', 5: 'ENT' };
export const POS_LONG: Record<number, string> = {
	1: 'Portero',
	2: 'Defensa',
	3: 'Centrocampista',
	4: 'Delantero',
	5: 'Entrenador'
};

/** En plural, para frases como "defensas que rinden más de lo que cuestan". */
export const POS_PLURAL: Record<number, string> = {
	1: 'porteros',
	2: 'defensas',
	3: 'centrocampistas',
	4: 'delanteros',
	5: 'entrenadores'
};

export const POS_BADGE: Record<number, string> = {
	1: 'bg-emerald-600 text-white',
	2: 'bg-blue-600 text-white',
	3: 'bg-amber-600 text-white',
	4: 'bg-rose-600 text-white',
	5: 'bg-purple-600 text-white'
};

export const POS_BORDER: Record<number, string> = {
	1: 'border-emerald-500/80',
	2: 'border-blue-500/80',
	3: 'border-amber-500/80',
	4: 'border-rose-500/80',
	5: 'border-purple-500/80'
};

export const STATUS: Record<string, { label: string; cls: string; dot: string }> = {
	ok: { label: 'Disponible', cls: 'text-up', dot: 'bg-up' },
	injured: { label: 'Lesionado', cls: 'text-down', dot: 'bg-down' },
	doubtful: { label: 'Duda', cls: 'text-warn', dot: 'bg-warn' },
	suspended: { label: 'Sancionado', cls: 'text-down', dot: 'bg-down' },
	out_of_league: { label: 'Fuera de LaLiga', cls: 'text-muted', dot: 'bg-muted' }
};

export const ACTIVITY: Record<number, string> = {
	1: 'compró a',
	4: 'blindó a',
	6: 'cobró la jornada',
	7: 'alineación incorrecta',
	9: 'se unió a la liga',
	31: 'fichó del mercado a',
	32: 'clausuló a',
	33: 'vendió a'
};

export function hoursUntil(iso: string | null | undefined, now = Date.now()): number | null {
	if (!iso) return null;
	return (new Date(iso).getTime() - now) / 36e5;
}

/** "en 2 d 5 h", "en 40 min", "hace 3 h" */
export function relative(iso: string | null | undefined, now = Date.now()): string {
	const h = hoursUntil(iso, now);
	if (h == null) return '–';
	const future = h >= 0;
	const abs = Math.abs(h);
	let s: string;
	if (abs < 1) s = `${Math.max(1, Math.round(abs * 60))} min`;
	else if (abs < 48) s = `${Math.floor(abs)} h`;
	else s = `${Math.floor(abs / 24)} d ${Math.round(abs % 24)} h`;
	return future ? `en ${s}` : `hace ${s}`;
}

export function dayText(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short' }): string {
	if (!iso) return '–';
	return new Date(iso).toLocaleDateString(es, { timeZone: 'Europe/Madrid', ...opts });
}

export function timeText(iso: string | null | undefined): string {
	if (!iso) return '–';
	return new Date(iso).toLocaleString(es, {
		timeZone: 'Europe/Madrid',
		weekday: 'short',
		day: 'numeric',
		month: 'short',
		hour: '2-digit',
		minute: '2-digit'
	});
}

export function clauseState(lockedUntil: string | null | undefined, shielded: boolean | null | undefined, now = Date.now()) {
	if (shielded) return { label: 'Blindado', cls: 'text-accent', open: false };
	const h = hoursUntil(lockedUntil, now);
	if (h == null) return { label: '–', cls: 'text-muted', open: false };
	if (h <= 0) return { label: 'Abierta', cls: 'text-down', open: true };
	if (h <= 72) return { label: `Se abre ${relative(lockedUntil, now)}`, cls: 'text-warn', open: false };
	return { label: `Bloqueada ${relative(lockedUntil, now)}`, cls: 'text-muted', open: false };
}

// Los dos mercados son cosas distintas (docs/plan-app.md §A3)
export const KIND_LEAGUE = 'marketPlayerLeague'; // lo vende la liga: puja ciega, todos cierran a la vez
export const KIND_TEAM = 'marketPlayerTeam'; // lo vende un manager: oferta directa, plazo propio

/** Lo que el sistema paga al comprarte un jugador, medido en 75 ventas reales de la liga:
 *  entre el 90 % y el 111 % de su valor, con media del 103 %. Sirve de marco para leer
 *  cualquier "% sobre valor" (docs/plan-app.md §B1). */
export const SYSTEM_OFFER_BAND = { min: 0.9, avg: 1.03, max: 1.11 };

/** Diferencia por debajo de la cual precio y valor se consideran el mismo número. */
export const AT_VALUE = 0.005;

/** Cómo de razonable es un precio comparado con el valor oficial. */
export function priceVerdict(price: number, value: number): { cls: string; text: string; atValue: boolean } {
	const r = price / value;
	if (Math.abs(r - 1) < AT_VALUE) return { cls: 'text-muted', text: 'a su valor exacto', atValue: true };
	if (r < 1) return { cls: 'text-up', text: 'por debajo de su valor', atValue: false };
	if (r <= SYSTEM_OFFER_BAND.max) return { cls: 'text-muted', text: 'dentro de lo que paga el sistema', atValue: false };
	if (r <= 1.25) return { cls: 'text-warn', text: 'por encima de lo que paga el sistema', atValue: false };
	return { cls: 'text-down', text: 'muy por encima de su valor', atValue: false };
}

/** Último movimiento real del valor: cuánto cambió y hace cuántos días.
 *  `spark` viene ordenada de más antigua a más reciente. Si lleva días plano, lo dice. */
export function lastMove(spark: number[] | null | undefined): { days: number; amount: number } | null {
	if (!spark || spark.length < 2) return null;
	for (let i = spark.length - 1; i > 0; i--) {
		const d = spark[i] - spark[i - 1];
		if (d !== 0) return { days: spark.length - 1 - i, amount: d };
	}
	return { days: spark.length - 1, amount: 0 };
}

/** Compacto para la columna estrecha: "+1,2 M hoy", "−800 k hace 3 d", "plano 5 d". */
export function moveText(spark: number[] | null | undefined): string {
	const m = lastMove(spark);
	if (!m) return '';
	if (m.amount === 0) return `plano ${m.days} d`;
	const cuando = m.days === 0 ? 'hoy' : m.days === 1 ? 'ayer' : `hace ${m.days} d`;
	return `${signed(m.amount)} ${cuando}`;
}

/** Frase completa para el panel explicativo. */
export function moveSentence(spark: number[] | null | undefined): string {
	const m = lastMove(spark);
	if (!m) return '';
	const cuando = m.days === 0 ? 'hoy' : m.days === 1 ? 'ayer' : `hace ${m.days} días`;
	if (m.amount === 0) return `Su valor no se mueve desde hace ${m.days} días.`;
	return `Su último movimiento fue ${cuando}: ${m.amount > 0 ? 'subió' : 'bajó'} ${money(Math.abs(m.amount))}.`;
}

export type PlayerTrend = {
	diff1d: number;
	pct1d: number | null;
	streakDays: number;
	streakAmount: number;
	streakLabel: string;
	badgeCls: string;
	dailyPace: number;
	isHot: boolean;
	isDropping: boolean;
};

/**
 * Describe los movimientos observados del valor a partir del historial (spark).
 * Calcula cuántos días consecutivos lleva subiendo o bajando, el acumulado en euros
 * No proyecta precios: las estimaciones proceden del recomendador contrastado.
 */
export function playerTrend(
	spark: number[] | null | undefined,
	value?: number | null,
	value_1d?: number | null
): PlayerTrend {
	const val = value ?? (spark && spark.length ? spark[spark.length - 1] : 0);
	const prevVal = value_1d ?? (spark && spark.length >= 2 ? spark[spark.length - 2] : null);
	const diff1d = prevVal != null ? val - prevVal : 0;
	const pct1d = prevVal != null && prevVal > 0 ? (diff1d / prevVal) * 100 : null;

	const cleanSpark = (spark ?? []).filter((x) => x > 0);
	if (cleanSpark.length < 2) {
		const label =
			diff1d > 0
				? `Sube hoy (+${money(diff1d)})`
				: diff1d < 0
					? `Baja hoy (${signed(diff1d)})`
					: 'Sin variación hoy';
		return {
			diff1d,
			pct1d,
			streakDays: diff1d > 0 ? 1 : diff1d < 0 ? -1 : 0,
			streakAmount: diff1d,
			streakLabel: label,
			badgeCls:
				diff1d > 0
					? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
					: diff1d < 0
						? 'text-rose-400 bg-rose-500/10 border-rose-500/20'
						: 'text-muted bg-surface-2 border-line',
			dailyPace: diff1d,
			isHot: diff1d > 0 && (pct1d ?? 0) >= 1.5,
			isDropping: diff1d < 0
		};
	}

	let streakDays = 0;
	let streakAmount = 0;
	const n = cleanSpark.length;
	const lastDiff = cleanSpark[n - 1] - cleanSpark[n - 2];
	const isRising = lastDiff > 0;
	const isFalling = lastDiff < 0;

	if (isRising || isFalling) {
		for (let i = n - 1; i > 0; i--) {
			const d = cleanSpark[i] - cleanSpark[i - 1];
			if (isRising && d > 0) {
				streakDays++;
				streakAmount += d;
			} else if (isFalling && d < 0) {
				streakDays++;
				streakAmount += d;
			} else {
				break;
			}
		}
	}

	const signedDays = isRising ? streakDays : isFalling ? -streakDays : 0;
	const dailyPace = streakDays > 0 ? Math.round(streakAmount / streakDays) : diff1d;

	let streakLabel = 'Sin cambios';
	let badgeCls = 'text-muted bg-surface-2 border-line';
	if (isRising) {
		if (streakDays >= 3) {
			streakLabel = `▲ ${streakDays}d subiendo (+${money(streakAmount)})`;
			badgeCls = 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30';
		} else if (streakDays === 2) {
			streakLabel = `▲ 2d subiendo (+${money(streakAmount)})`;
			badgeCls = 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
		} else {
			streakLabel = `▲ Sube hoy (+${money(diff1d)})`;
			badgeCls = 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
		}
	} else if (isFalling) {
		if (streakDays >= 3) {
			streakLabel = `▼ ${streakDays}d bajando (${signed(streakAmount)})`;
			badgeCls = 'text-rose-400 bg-rose-500/15 border-rose-500/30';
		} else if (streakDays === 2) {
			streakLabel = `▼ 2d bajando (${signed(streakAmount)})`;
			badgeCls = 'text-rose-400 bg-rose-500/10 border-rose-500/20';
		} else {
			streakLabel = `▼ Baja hoy (${signed(diff1d)})`;
			badgeCls = 'text-rose-400 bg-rose-500/10 border-rose-500/20';
		}
	}


	return {
		diff1d,
		pct1d,
		streakDays: signedDays,
		streakAmount,
		streakLabel,
		badgeCls,
		dailyPace,
		isHot: isRising && (streakDays >= 3 || (pct1d ?? 0) >= 1.5),
		isDropping: isFalling && streakDays >= 2
	};
}

/** La cláusula frente al valor, dicha en euros y en castellano.
 *
 *  `gap` es siempre `valor − cláusula`, tal y como lo devuelve la consulta. Ese número aparecía en
 *  cinco sitios de la app con cinco redacciones distintas y ninguna se entendía: un «0» pelado, un
 *  «−1,7 M sobre valor» que se leía como si fuera un descuento cuando era un sobrecoste, y un
 *  «por encima del valor» fijo que nunca enseñaba la cifra. Una sola función y una sola frase.
 *
 *  `quien` cambia el punto de vista, que es lo que da sentido al signo:
 *   - `'rival'`: cláusulas **tuyas**. Cuanto más cara sea respecto al valor, más protegido estás.
 *   - `'yo'`: cláusulas **ajenas**. Lo que te costaría a ti pagarlas.
 */
export function clauseVsValue(
	gap: number,
	quien: 'rival' | 'yo',
	/** El valor del jugador, para poder juzgar si la diferencia es relevante o ruido. */
	value?: number | null
): { cls: string; text: string } {
	const sobrecoste = -gap; // lo que se paga por encima del valor
	// El corte era de **un euro**, así que una diferencia de 114 € sobre 5,8 M se anunciaba como
	// «se lo lleva 114 por debajo del valor», que asusta y no significa nada. Con el valor delante
	// se aplica el mismo criterio que el resto de la app: por debajo del 0,5 %, es el mismo número.
	const ruido = value ? Math.abs(gap) < value * AT_VALUE : Math.abs(gap) < 1;
	if (ruido) return { cls: 'text-muted', text: 'cuesta justo su valor' };
	if (quien === 'rival') {
		return sobrecoste > 0
			? { cls: 'text-up', text: `a un rival le cuesta ${money(sobrecoste)} de más` }
			: { cls: 'text-down', text: `se lo lleva ${money(gap)} por debajo del valor` };
	}
	return sobrecoste > 0
		? { cls: 'text-muted', text: `pagas ${money(sobrecoste)} de más` }
		: { cls: 'text-up', text: `pagas ${money(gap)} menos de lo que vale` };
}

/** La misma idea que `clauseVsValue` pero para la columna estrecha de las listas, donde la frase
 *  entera se parte en tres renglones y deja la fila con cinco líneas de alto. Se conserva la regla
 *  de que ningún número va sin su palabra. */
export function clauseVsValueShort(
	gap: number,
	value?: number | null
): { cls: string; text: string } {
	const sobrecoste = -gap;
	const ruido = value ? Math.abs(gap) < value * AT_VALUE : Math.abs(gap) < 1;
	if (ruido) return { cls: 'text-muted', text: 'a su valor' };
	return sobrecoste > 0
		? { cls: 'text-up', text: `${money(sobrecoste)} de más` }
		: { cls: 'text-down', text: `${money(gap)} menos` };
}

/** Número en castellano: coma decimal. La media de puntos salía como «10.67» y «6.5», con punto
 *  inglés, junto a importes que sí usaban coma («+2,6 M») en la misma línea. */
export function num(x: number | null | undefined, decimals = 1): string {
	if (x == null) return '–';
	return x.toLocaleString('es-ES', { maximumFractionDigits: decimals });
}

/** El verbo sin complemento, para cuando ya se sabe de quién se habla.
 *  En la ficha del jugador salía «braisdlim blindó a» y ahí se acababa la frase. */
export function activityVerb(type: number): string {
	return (ACTIVITY[type] ?? '').replace(/ a$/, '');
}

/** Como `num`, pero sin dejar caer el decimal: 1 goles esperados se lee mal, 1,0 goles no. */
export function fixed(x: number | null | undefined, decimals = 1): string {
	if (x == null) return '–';
	return x.toLocaleString('es-ES', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

// Ruido de nombre de club que no distingue a nadie, y palabras que se repiten entre clubes.
const CLUB_NOISE = /^(FC|CF|RC|RCD|CD|UD|SD|CA|C\.A\.|R\.|AD|Club|de|del)$/i;
// «Atlético» no está aquí a propósito: si lo estuviera, «Atlético de Madrid» se quedaría en
// «Madrid» y chocaría con el Real Madrid.
const CLUB_GENERIC = /^(Deportivo|Real)$/i;

/**
 * Nombre corto de un club, para rejillas y frases donde el nombre entero no cabe.
 *
 * Tiene que distinguir: quitando prefijos sin más, «Deportivo Alavés» y «RC Deportivo» se
 * quedaban los dos en «Deportivo», y la frase «gana el Deportivo el 55 %» significaba cosas
 * distintas en dos tarjetas de la misma pantalla. Por eso, si lo que queda empieza por una
 * palabra que comparten varios clubes, manda la siguiente.
 */
export function shortClub(name: string | null | undefined): string {
	if (!name) return '–';
	const words = name.split(/\s+/).filter((w) => !CLUB_NOISE.test(w));
	if (!words.length) return name;
	if (words.length > 1 && CLUB_GENERIC.test(words[0])) return words[1];
	return words[0];
}

/**
 * Devuelve el nombre más legible y natural del jugador para la interfaz móvil.
 * Evita abreviaturas feas con inicial y punto (ej: "V. Rosier" -> "Valentin Rosier", "G. Villar" -> "Gonzalo Villar"),
 * pero conserva apodos deportivos limpios ("Juan Iglesias", "Turrientes", "Arda Güler").
 */
export function playerName(p: { name?: string | null; nickname?: string | null }): string {
	const nick = (p.nickname ?? '').trim();
	const full = (p.name ?? '').trim();

	if (!nick && !full) return '–';
	if (!nick) return full;
	if (!full) return nick;

	// Si el nickname empieza por una inicial con punto ("V. Rosier", "G. Villar", "Á. Valles")
	// y el name no tiene punto y es más completo ("Valentin Rosier", "Gonzalo Villar"):
	const nickHasDot = /^[A-ZÁÉÍÓÚ]\.\s+/i.test(nick);
	const fullHasDot = /^[A-ZÁÉÍÓÚ]\.\s+/i.test(full);
	if (nickHasDot && !fullHasDot && full.length > nick.length) {
		return full;
	}

	// Si el nombre completo es larguísimo (más de 3 palabras, ej: "Juan Antonio Iglesias Sánchez")
	// y el apodo es corto y limpio (ej: "Juan Iglesias"):
	if (full.split(/\s+/).length > 3 && nick.split(/\s+/).length <= 2) {
		return nick;
	}

	// Si el apodo no tiene punto, es el nombre preferido en Fantasy
	if (!nickHasDot) {
		return nick;
	}

	return !fullHasDot ? full : nick;
}

/** Mapeo de jerarquía de FútbolFantasy a categoría oficial y estilos.
 *  FútbolFantasy divide la jerarquía en 7 grupos oficiales:
 *  60 = Dios (top estrellas mundiales / top 3 de LaLiga)
 *  50 = Clave (titulares indiscutibles)
 *  40 = Importante (titulares habituales de peso)
 *  30 = Rotación (jugadores que alternan titularidad)
 *  25 = Revulsivo (habituales saliendo desde el banquillo)
 *  20 = Reserva (suplentes habituales)
 *  <= 10 = Descarte (sin minutos / fuera de planes)
 */
export function hierarchyInfo(h: number | null | undefined): {
	label: string;
	icon: string;
	subtitle: string;
	cls: string;
	badgeCls: string;
} {
	if (h == null) {
		return { label: '–', icon: '•', subtitle: 'Sin dato', cls: 'text-muted', badgeCls: 'bg-surface-2 border-line text-muted' };
	}
	if (h >= 60) {
		return {
			label: 'Dios',
			icon: '',
			subtitle: 'Top de LaLiga',
			cls: 'text-yellow-300',
			badgeCls: 'bg-gradient-to-r from-amber-500/25 via-yellow-500/25 to-amber-500/25 border-amber-400/60 text-yellow-200 shadow-sm'
		};
	}
	if (h >= 50) {
		return {
			label: 'Clave',
			icon: '',
			subtitle: 'Indiscutible',
			cls: 'text-amber-300',
			badgeCls: 'bg-amber-500/15 border-amber-500/40 text-amber-300'
		};
	}
	if (h >= 40) {
		return {
			label: 'Importante',
			icon: '',
			subtitle: 'Titular habitual',
			cls: 'text-amber-400',
			badgeCls: 'bg-amber-500/10 border-amber-500/30 text-amber-300'
		};
	}
	if (h >= 30) {
		return {
			label: 'Rotación',
			icon: '',
			subtitle: 'Alterna titularidad',
			cls: 'text-sky-400',
			badgeCls: 'bg-sky-500/10 border-sky-500/30 text-sky-300'
		};
	}
	if (h >= 25) {
		return {
			label: 'Revulsivo',
			icon: '',
			subtitle: 'Impacto banquillo',
			cls: 'text-purple-400',
			badgeCls: 'bg-purple-500/10 border-purple-500/30 text-purple-300'
		};
	}
	if (h >= 20) {
		return {
			label: 'Reserva',
			icon: '',
			subtitle: 'Suplente habitual',
			cls: 'text-muted',
			badgeCls: 'bg-surface-2 border-line text-muted'
		};
	}
	return {
		label: 'Descarte',
		icon: '✕',
		subtitle: 'Sin minutos',
		cls: 'text-muted',
		badgeCls: 'bg-surface-2 border-line text-muted'
	};
}

/** Mapeo de forma de FútbolFantasy (-1 a +3) a flecha y estilo. */
export function formInfo(f: number | null | undefined): { label: string; arrow: string; cls: string; iconCls: string } {
	if (f == null) return { label: '–', arrow: '•', cls: 'text-muted', iconCls: 'text-muted' };
	const val = Number(f);
	if (val >= 1.5) return { label: `+${val.toFixed(1)}`, arrow: '↗', cls: 'text-up', iconCls: 'text-up' };
	if (val >= 0.5) return { label: val.toFixed(1), arrow: '→', cls: 'text-warn', iconCls: 'text-warn' };
	return { label: val.toFixed(1), arrow: '↘', cls: 'text-down', iconCls: 'text-down' };
}

/** Riesgo de lesión y estado general de disponibilidad. */
export function injuryRisk(
	av: { injured?: boolean | null; suspended?: boolean | null; booking_risk?: boolean | null } | null | undefined,
	status?: string
): {
	label: string;
	cls: string;
	statusText: string;
	statusCls: string;
} {
	if (av?.injured || status === 'injured') {
		return { label: 'Alto', cls: 'text-down', statusText: 'Lesionado', statusCls: 'text-down bg-down/10 border-down/30' };
	}
	if (av?.suspended || status === 'suspended') {
		return { label: 'Sancionado', cls: 'text-down', statusText: 'Sancionado', statusCls: 'text-down bg-down/10 border-down/30' };
	}
	if (status === 'doubtful') {
		return { label: 'Medio', cls: 'text-warn', statusText: 'Duda física / molestias', statusCls: 'text-warn bg-warn/10 border-warn/30' };
	}
	if (av?.booking_risk) {
		return { label: 'Medio', cls: 'text-warn', statusText: 'Apercibido (4 amarillas)', statusCls: 'text-warn bg-warn/10 border-warn/30' };
	}
	if (status === 'out_of_league') {
		return { label: '–', cls: 'text-muted', statusText: 'Fuera de LaLiga', statusCls: 'text-muted bg-surface-2 border-line' };
	}
	return { label: 'Bajo', cls: 'text-up', statusText: 'Disponible para competir', statusCls: 'text-up bg-up/10 border-up/30' };
}

/** Resultado de un partido jugado (Victoria, Empate, Derrota). */
export function matchResult(localScore: number | null, visitorScore: number | null, isHome: boolean): {
	code: 'V' | 'E' | 'D';
	label: string;
	cls: string;
	badgeCls: string;
} {
	if (localScore == null || visitorScore == null) return { code: 'E', label: 'Empate', cls: 'text-muted', badgeCls: 'bg-surface-2 text-muted border-line' };
	const myScore = isHome ? localScore : visitorScore;
	const oppScore = isHome ? visitorScore : localScore;
	if (myScore > oppScore) return { code: 'V', label: 'Victoria', cls: 'text-up', badgeCls: 'bg-up/15 text-up border-up/30' };
	if (myScore < oppScore) return { code: 'D', label: 'Derrota', cls: 'text-down', badgeCls: 'bg-down/15 text-down border-down/30' };
	return { code: 'E', label: 'Empate', cls: 'text-warn', badgeCls: 'bg-warn/15 text-warn border-warn/30' };
}

/** Formato corto dd/mm para tarjetas de partidos. */
export function matchDay(iso: string | null | undefined): string {
	if (!iso) return '–';
	return new Date(iso).toLocaleDateString(es, { timeZone: 'Europe/Madrid', day: '2-digit', month: '2-digit' });
}

/** Formato corto HH:MMh para hora de inicio de partidos. */
export function matchTime(iso: string | null | undefined): string {
	if (!iso) return '–';
	return (
		new Date(iso).toLocaleTimeString(es, {
			timeZone: 'Europe/Madrid',
			hour: '2-digit',
			minute: '2-digit'
		}) + 'h'
	);
}

// --- Fixture Difficulty Rating (FDR) -------------------------------------------------------------
export type FDRMode = 'general' | 'attack' | 'defense';
export type FDRLevel = 1 | 2 | 3 | 4 | 5;

export const FDR_STYLES: Record<FDRLevel, { label: string; short: string; cls: string; pill: string; badge: string }> = {
	1: {
		label: 'Muy favorable',
		short: '1 Muy favorable',
		cls: 'bg-emerald-600/30 text-emerald-300 border-emerald-500/40 font-bold',
		pill: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
		badge: 'bg-emerald-600 text-white'
	},
	2: {
		label: 'Favorable',
		short: '2 Favorable',
		cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
		pill: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25',
		badge: 'bg-emerald-500 text-white'
	},
	3: {
		label: 'Neutral',
		short: '3 Neutral',
		cls: 'bg-surface-2 text-muted border-line',
		pill: 'bg-surface-2 text-muted border-line',
		badge: 'bg-neutral-600 text-neutral-200'
	},
	4: {
		label: 'Difícil',
		short: '4 Difícil',
		cls: 'bg-rose-500/15 text-rose-400 border-rose-500/25',
		pill: 'bg-rose-500/10 text-rose-400 border-rose-500/25',
		badge: 'bg-rose-500 text-white'
	},
	5: {
		label: 'Muy difícil',
		short: '5 Muy difícil',
		cls: 'bg-rose-600/30 text-rose-300 border-rose-500/40 font-bold',
		pill: 'bg-rose-500/20 text-rose-300 border-rose-500/40',
		badge: 'bg-rose-600 text-white'
	}
};

export function calculateFDR(
	xgFor: number,
	xgAgainst: number,
	cleanSheet: number,
	mode: FDRMode = 'general'
): { level: FDRLevel; score: number; label: string; cls: string } {
	let level: FDRLevel = 3;
	let score = 3;

	if (mode === 'attack') {
		if (xgFor >= 1.8) {
			level = 1;
			score = 1;
		} else if (xgFor >= 1.45) {
			level = 2;
			score = 2;
		} else if (xgFor >= 1.15) {
			level = 3;
			score = 3;
		} else if (xgFor >= 0.85) {
			level = 4;
			score = 4;
		} else {
			level = 5;
			score = 5;
		}
	} else if (mode === 'defense') {
		if (cleanSheet >= 0.38 || xgAgainst <= 0.85) {
			level = 1;
			score = 1;
		} else if (cleanSheet >= 0.28 || xgAgainst <= 1.15) {
			level = 2;
			score = 2;
		} else if (cleanSheet >= 0.20 || xgAgainst <= 1.45) {
			level = 3;
			score = 3;
		} else if (cleanSheet >= 0.12 || xgAgainst <= 1.75) {
			level = 4;
			score = 4;
		} else {
			level = 5;
			score = 5;
		}
	} else {
		const diff = xgFor - xgAgainst;
		if (diff >= 0.75) {
			level = 1;
			score = 1;
		} else if (diff >= 0.25) {
			level = 2;
			score = 2;
		} else if (diff >= -0.25) {
			level = 3;
			score = 3;
		} else if (diff >= -0.75) {
			level = 4;
			score = 4;
		} else {
			level = 5;
			score = 5;
		}
	}

	return {
		level,
		score,
		label: FDR_STYLES[level].label,
		cls: FDR_STYLES[level].cls
	};
}

export function fdrAvgBadge(avg: number): { text: string; cls: string } {
	const text = avg.toFixed(1);
	if (avg <= 1.8) return { text, cls: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40' };
	if (avg <= 2.6) return { text, cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/25' };
	if (avg <= 3.4) return { text, cls: 'bg-surface-2 text-muted border border-line' };
	if (avg <= 4.2) return { text, cls: 'bg-rose-500/10 text-rose-400 border border-rose-500/25' };
	return { text, cls: 'bg-rose-500/20 text-rose-300 border border-rose-500/40 font-bold' };
}
