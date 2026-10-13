// Todas las consultas de la app. Solo lectura sobre las tablas que rellena el job Python.
// Convención: bigint/numeric se devuelven como float8 y las fechas como texto ISO (UTC) para que
// el driver HTTP de Neon no tenga que adivinar tipos.
import { clearQueryCache, q } from './db';
import { money, num, signed } from '$lib/format';
import { env } from '$env/dynamic/private';

// Solo previsiones recientes: 100 % puede ser un once confirmado de otro partido.
const START_PROB = (alias = 'av') => `(CASE WHEN ${alias}.fetched_at >= now() - interval '26 hours'
 AND ${alias}.start_prob >= 0 AND ${alias}.start_prob < 1 THEN ${alias}.start_prob::float8 END)`;

const ISO = (col: string) => `to_char(${col} AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')`;

export type PlayerCard = {
	player_id: string;
	name: string;
	nickname: string | null;
	position_id: number;
	team_id: string;
	club: string;
	club_slug: string | null;
	badge_url: string | null;
	image_url: string | null;
	value: number;
	value_1d: number | null;
	value_7d: number | null;
	value_30d: number | null;
	status: string;
	points_total: number;
	average_points: number | null;
	spark: number[];
	next_match: { date: string; home: boolean; opponent: string } | null;
};

export type PlayerAvailability = {
	fetched_at: string | null;
	source_url: string | null;
	start_prob: number | null;
	injured: boolean | null;
	suspended: boolean | null;
	booking_risk: boolean | null;
	minutes: number | null;
	games: number | null;
};

export type PlayerSeasonStats = {
	form: number | null;
	hierarchy: number | null;
	goals: number | null;
	assists: number | null;
	yellows: number | null;
	reds: number | null;
	games: number | null;
	games_as_sub: number | null;
	games_subbed_off: number | null;
	minutes: number | null;
};

export type PlayerMatch = {
	match_id: string;
	week: number;
	match_date: string;
	local_team_id: string;
	visitor_team_id: string;
	local_name: string;
	local_slug: string | null;
	local_badge: string | null;
	visitor_name: string;
	visitor_slug: string | null;
	visitor_badge: string | null;
	local_score: number | null;
	visitor_score: number | null;
	is_home: boolean;
	total_points: number | null;
	mins_played: number | null;
	xg_local?: number | null;
	xg_visitor?: number | null;
	p_local?: number | null;
	p_draw?: number | null;
	p_visitor?: number | null;
	cs_local?: number | null;
	cs_visitor?: number | null;
};

// Fragmento común: ficha de valor de un jugador a la última fecha de la API
const PLAYER_CARD = `
	p.player_id, p.name, p.nickname, p.position_id, p.team_id, t.name AS club, t.slug AS club_slug, t.badge_url AS badge_url, p.image_url,
	v.market_value::float8 AS value,
	-- NULLIF porque un cero **no es un valor, es un dato que falta**: el backfill dejó 7.453 filas a
	-- cero (a 2026-09-09, 126 jugadores tenían el valor de hace 30 días a cero). Sin esto la ficha
	-- restaba contra cero y anunciaba como subida de 30 días el valor entero del jugador.
	NULLIF(v1.market_value, 0)::float8 AS value_1d,
	NULLIF(v7.market_value, 0)::float8 AS value_7d,
	NULLIF(v30.market_value, 0)::float8 AS value_30d,
	v.status, v.points_total, v.average_points::float8 AS average_points,
	(SELECT COALESCE(array_agg(s.market_value::float8 ORDER BY s.day), '{}')
	   FROM player_value_daily s WHERE s.player_id = p.player_id AND s.day > d.day - 30
	     AND s.market_value > 0) AS spark,
	(SELECT jsonb_build_object('date', ${ISO('m.match_date')}, 'home', m.local_team_id = p.team_id,
	        'opponent', CASE WHEN m.local_team_id = p.team_id THEN tv.name ELSE tl.name END)
	   FROM matches m JOIN teams tl ON tl.team_id = m.local_team_id JOIN teams tv ON tv.team_id = m.visitor_team_id
	  WHERE (m.local_team_id = p.team_id OR m.visitor_team_id = p.team_id) AND m.match_date > now()
	  ORDER BY m.match_date LIMIT 1) AS next_match`;

const PLAYER_JOINS = `
	FROM players p
	JOIN teams t ON t.team_id = p.team_id
	CROSS JOIN d
	JOIN player_value_daily v ON v.player_id = p.player_id AND v.day = d.day
	-- Solo contra el día exacto y de la **misma fuente**: si falta, NULL y la app dice «sin dato».
	-- Nunca contra «el último que haya» ni mezclando la serie de FútbolFantasy con la de la API.
	LEFT JOIN player_value_daily v1 ON v1.player_id = p.player_id AND v1.day = d.day - 1 AND v1.source = v.source
	LEFT JOIN player_value_daily v7 ON v7.player_id = p.player_id AND v7.day = d.day - 7 AND v7.source = v.source
	LEFT JOIN player_value_daily v30 ON v30.player_id = p.player_id AND v30.day = d.day - 30 AND v30.source = v.source`;

const LATEST_DAY = `WITH d AS (SELECT max(day) AS day FROM player_value_daily WHERE source = 'laliga_api')`;

/**
 * Plantilla vigente de cada equipo: la última foto de ese equipo, no la última fecha de la tabla.
 * El job ligero guarda solo mi plantilla cada hora con el día nuevo (desde las 00:20) y el diario
 * no recoge las de los rivales hasta las 19:25. Filtrar por `max(day)` global dejaba a los rivales
 * sin jugadores casi todo el día: «Puedes clausular» salía vacío y los dueños desaparecían.
 * Un jugador que ya sale en una foto más reciente de otro equipo (lo acabo de fichar o clausular)
 * se quita de la foto vieja para que no tenga dos dueños.
 */
const SQUAD_NOW = `(SELECT sn.* FROM league_squad_daily sn
	WHERE sn.day = (SELECT max(sm.day) FROM league_squad_daily sm WHERE sm.league_id = sn.league_id AND sm.team_id = sn.team_id)
	  AND NOT EXISTS (SELECT 1 FROM league_squad_daily sx WHERE sx.player_id = sn.player_id AND sx.day > sn.day))`;

export async function latestDay(): Promise<string | null> {
	const rows = await q(`SELECT max(day)::text AS day FROM player_value_daily WHERE source = 'laliga_api'`);
	return (rows[0]?.day as string) ?? null;
}

export type Freshness = {
	availability: string | null;
	availability_stale: boolean;
	market: string | null; // última lectura del mercado (job ligero, cada hora)
	squad: string | null; // última lectura de plantillas
	values_day: string | null; // día de los valores de mercado (cambian una vez al día)
	values_expected: string | null; // el día cuyos valores ya ha publicado LaLiga (00:15 de Madrid)
	last_job: string | null;
	cycle_end: string | null; // cierre del ciclo vigente (el último con jugadores de la liga)
	market_state: string | null; // cómo vino la última captura del mercado: ok | rotating | empty
	market_state_at: string | null;
};

/** Cuándo se leyó cada cosa. El valor de mercado cambia una vez al día; el mercado y las
 *  plantillas, cada hora. Por eso la app muestra la antigüedad por pantalla y no una sola fecha. */
export async function freshness(): Promise<Freshness> {
	const rows = await q(`
		SELECT ${ISO('(SELECT max(last_seen_at) FROM market_offer)')} AS market,
		       ${ISO('(SELECT min(fetched_at) FROM player_availability WHERE day = (SELECT max(day) FROM player_availability))')} AS availability,
		       COALESCE((SELECT NOT (count(*) >= ${env.DEMO_MODE === 'true' ? 64 : 400} AND min(fetched_at) >= now() - interval '26 hours')
		         FROM player_availability WHERE day = (SELECT max(day) FROM player_availability)), true) AS availability_stale,
		       ${ISO('(SELECT max(fetched_at) FROM league_squad_daily)')} AS squad,
		       (SELECT max(day)::text FROM player_value_daily WHERE source = 'laliga_api') AS values_day,
		       ((now() AT TIME ZONE 'Europe/Madrid') - interval '20 minutes')::date::text AS values_expected,
		       ${ISO("(SELECT max(finished_at) FROM job_runs WHERE status = 'ok')")} AS last_job,
		       ${ISO("(SELECT max(cycle_end) FROM market_offer WHERE kind = 'marketPlayerLeague')")} AS cycle_end,
		       lm.state AS market_state, ${ISO('lm.at')} AS market_state_at
		  FROM (SELECT 1) one
		  LEFT JOIN LATERAL (
		       SELECT summary->'market'->>'state' AS state, finished_at AS at FROM job_runs
		        WHERE finished_at IS NOT NULL AND summary->'market'->>'state' IS NOT NULL
		        ORDER BY id DESC LIMIT 1) lm ON true`);
	return (rows[0] ?? {
		market: null, squad: null, values_day: null, values_expected: null, last_job: null,
		cycle_end: null, market_state: null, market_state_at: null
	}) as Freshness;
}

export async function myTeam() {
	const rows = await q(`
		SELECT lt.league_id, lt.team_id, lt.manager_id, lt.manager_name, s.position, s.previous_position, s.points,
		       s.team_value::float8 AS team_value, COALESCE(lt.team_money, s.team_money)::float8 AS team_money, s.day::text AS day,
		       (SELECT count(*) FROM league_teams x WHERE x.league_id = lt.league_id) AS managers
		FROM league_teams lt JOIN league_standing_daily s USING (league_id, team_id)
		WHERE lt.is_me ORDER BY s.day DESC LIMIT 1`);
	return rows[0] as
		| {
				league_id: string;
				team_id: string;
				manager_id: string;
				manager_name: string;
				position: number;
				previous_position: number | null;
				points: number;
				team_value: number;
				team_money: number | null;
				day: string;
				managers: number;
		  }
		| undefined;
}

/**
 * La jornada **que toca preparar**: la primera cuyo once todavía no se ha bloqueado.
 *
 * En cuanto una jornada arranca ya no se puede tocar su alineación, así que lo accionable pasa a
 * ser la siguiente. La app se quedaba clavada en la anterior por dos motivos distintos:
 *
 *  - Leía `weeks`, que solo guarda la jornada en curso.
 *  - Y la pantalla de Jornada se anclaba en «la jornada más antigua con algún partido sin jugar»,
 *    así que un aplazado la fijaba ahí para siempre: el Villarreal-Betis de la J5, sin resultado,
 *    mantenía toda la app en la jornada 5 cuando ya se jugaba la 6.
 *
 * El bloqueo es `weeks.opening_at` cuando lo tenemos —es el dato oficial— y si no, el primer
 * partido de esa jornada. La distinción importa: la J6 se bloqueó el 15 a las 17:00 aunque tenía
 * un partido adelantado al día 3.
 */
const NEXT_WEEK = `
	SELECT m.week, COALESCE(w.opening_at, min(m.match_date)) AS lock_at
	FROM matches m
	LEFT JOIN weeks w ON w.week = m.week
	GROUP BY m.week, w.opening_at
	HAVING COALESCE(w.opening_at, min(m.match_date)) > now()
	ORDER BY m.week
	LIMIT 1`;

export async function calendar() {
	const rows = await q(`
		WITH n AS (${NEXT_WEEK})
		SELECT n.week, ${ISO('n.lock_at')} AS opening_at FROM n`);
	const week = rows[0] as { week: number; opening_at: string | null } | undefined;

	// La protección de cláusulas va de la jornada **en curso**, no de la siguiente: empieza 24 h
	// antes de que se bloquee el once y dura hasta que la jornada acaba.
	const enCurso = await q(`
		SELECT week, ${ISO('opening_at')} AS opening_at, ${ISO('closing_at')} AS closing_at
		FROM weeks WHERE opening_at <= now() ORDER BY opening_at DESC LIMIT 1`);
	const current = enCurso[0] as
		| { week: number; opening_at: string | null; closing_at: string | null }
		| undefined;
	// el mercado de la liga cierra al final del ciclo; si ya pasó, el siguiente es 24 h después
	let closesAt = await marketCycle();
	if (closesAt) {
		let t = new Date(closesAt).getTime();
		while (t < Date.now()) t += 864e5;
		closesAt = new Date(t).toISOString();
	}
	return { week, current, closesAt };
}

export type SquadPlayer = PlayerCard & {
	buyout_clause: number | null;
	clause_locked_until: string | null;
	is_shielded: boolean | null;
	bought_at: string | null;
	bought_for: number | null;
	bought_type: number | null;
	week_points: { week: number; points: number | null }[];
};

export async function squad(teamId: string): Promise<{ team: Record<string, unknown> | undefined; players: SquadPlayer[] }> {
	const teamRows = await q(
		`SELECT lt.team_id, lt.manager_id, lt.manager_name, lt.is_me, s.position, s.points, s.team_value::float8 AS team_value,
		        COALESCE(lt.team_money, s.team_money)::float8 AS team_money, s.day::text AS day
		 FROM league_teams lt JOIN league_standing_daily s USING (league_id, team_id)
		 WHERE lt.team_id = $1 ORDER BY s.day DESC LIMIT 1`,
		[teamId]
	);
	const rows = await q(
		`${LATEST_DAY}, q AS (
			SELECT * FROM league_squad_daily WHERE team_id = $1
			   AND day = (SELECT max(day) FROM league_squad_daily WHERE team_id = $1))
		SELECT ${PLAYER_CARD},
		       q.buyout_clause::float8 AS buyout_clause, ${ISO('q.clause_locked_until')} AS clause_locked_until, q.is_shielded,
		       ${ISO('b.happened_at')} AS bought_at, b.amount::float8 AS bought_for, b.activity_type AS bought_type,
		       (SELECT COALESCE(jsonb_agg(jsonb_build_object('week', w.week, 'points', w.total_points) ORDER BY w.week), '[]')
		          FROM player_week_stats w WHERE w.player_id = p.player_id) AS week_points
		${PLAYER_JOINS}
		JOIN q ON q.player_id = p.player_id
		LEFT JOIN league_teams lt ON lt.team_id = q.team_id AND lt.league_id = q.league_id
		LEFT JOIN LATERAL (
			SELECT a.happened_at, a.amount, a.activity_type FROM league_activity a
			 WHERE a.league_id = q.league_id AND a.player_id = p.player_id
			   AND a.manager_id = lt.manager_id AND a.activity_type IN (1, 31, 32)
			 ORDER BY a.happened_at DESC LIMIT 1) b ON true
		ORDER BY p.position_id, v.market_value DESC`,
		[teamId]
	);
	return { team: teamRows[0], players: rows as SquadPlayer[] };
}

export type Offer = PlayerCard & {
	market_id: string;
	sale_price: number;
	kind: string;
	num_bids: number | null;
	num_offers: number | null;
	offer_money: number | null;
	buyout_clause: number | null;
	expires_at: string | null;
	owner_team_id: string | null;
	seller: string | null;
	mine: boolean | null;
	start_prob: number | null;
	injured: boolean | null;
	suspended: boolean | null;
	booking_risk: boolean | null;
	rec_verdict: string | null;
	rec_score: number | null;
};

/** Ofertas vivas del ciclo de mercado actual: una fila por jugador, sin caducadas.
 *  El ciclo lo marca el cierre del mercado de la liga, no el día natural (docs/plan-app.md §A1). */
export async function market(): Promise<Offer[]> {
	const rows = await q(`
		${LATEST_DAY},
		av_day AS (SELECT max(day) AS day FROM player_availability),
		rc_time AS (SELECT max(created_at) AS created_at FROM recommendations),
		m AS (
			SELECT * FROM market_offer
			 WHERE cycle_end = (SELECT max(cycle_end) FROM market_offer WHERE kind = 'marketPlayerLeague')
			   AND (expires_at IS NULL OR expires_at > now()))
		SELECT ${PLAYER_CARD}, m.market_id, m.sale_price::float8 AS sale_price, m.kind, m.num_bids, m.num_offers,
		       m.offer_money::float8 AS offer_money,
		       m.buyout_clause::float8 AS buyout_clause, ${ISO('m.expires_at')} AS expires_at,
		       m.owner_team_id, lt.manager_name AS seller, lt.is_me AS mine,
		       ${START_PROB()} AS start_prob, av.injured, av.suspended, av.booking_risk,
		       rc.subject->>'verdict' AS rec_verdict, rc.score::float8 AS rec_score
		${PLAYER_JOINS}
		JOIN m ON m.player_id = p.player_id
		LEFT JOIN league_teams lt ON lt.team_id = m.owner_team_id
		LEFT JOIN player_availability av ON av.player_id = p.player_id AND av.day = (SELECT day FROM av_day)
		LEFT JOIN recommendations rc ON rc.created_at = (SELECT created_at FROM rc_time)
		     AND rc.subject->>'player_id' = p.player_id
		ORDER BY (v.market_value - COALESCE(v1.market_value, v.market_value)) DESC`);
	return rows as Offer[];
}

/** Cuándo cierra el mercado de la liga en el ciclo actual. */
export async function marketCycle(): Promise<string | null> {
	const rows = await q(`SELECT ${ISO('max(cycle_end)')} AS cycle_end FROM market_offer WHERE kind = 'marketPlayerLeague'`);
	return (rows[0]?.cycle_end as string) ?? null;
}

export type Mover = PlayerCard & {
	diff_1d: number;
	pct_1d: number | null;
	diff_7d: number | null;
	owner: string | null;
	owner_is_me: boolean | null;
};

/** Radar global: subidas y bajadas del día entre los jugadores en LaLiga, con dueño en mi liga si lo tiene. */
export async function movers(
	limit = 20,
	options: { includeMine?: boolean } = {}
): Promise<{
	up: Mover[];
	down: Mover[];
	up_pct: Mover[];
	down_pct: Mover[];
	total_up: number;
	total_down: number;
}> {
	const whereMine = options.includeMine ? '' : 'AND (o.is_me IS NOT TRUE)';
	const base = `
		${LATEST_DAY}
		SELECT ${PLAYER_CARD}, (v.market_value - v1.market_value)::float8 AS diff_1d,
		       round(((v.market_value - v1.market_value)::numeric / v1.market_value * 100), 2)::float8 AS pct_1d,
		       (v.market_value - v7.market_value)::float8 AS diff_7d,
		       o.manager_name AS owner, o.is_me AS owner_is_me
		${PLAYER_JOINS}
		LEFT JOIN LATERAL (
			SELECT lt.manager_name, lt.is_me FROM ${SQUAD_NOW} q JOIN league_teams lt USING (league_id, team_id)
			 WHERE q.player_id = p.player_id LIMIT 1) o ON true
		WHERE v.status <> 'out_of_league' AND v1.market_value > 0
		  ${whereMine}`;

	const [up, down, upPct, downPct, totals] = await Promise.all([
		q(`${base} ORDER BY diff_1d DESC LIMIT ${limit}`),
		q(`${base} ORDER BY diff_1d ASC LIMIT ${limit}`),
		q(`${base} ORDER BY (v.market_value - v1.market_value)::float8 / v1.market_value DESC LIMIT ${limit}`),
		q(`${base} ORDER BY (v.market_value - v1.market_value)::float8 / v1.market_value ASC LIMIT ${limit}`),
		q(`
			WITH d AS (SELECT max(day) AS day FROM player_value_daily WHERE source = 'laliga_api')
			SELECT count(*) FILTER (WHERE v.market_value > v1.market_value) AS total_up,
			       count(*) FILTER (WHERE v.market_value < v1.market_value) AS total_down
			FROM player_value_daily v CROSS JOIN d
			JOIN player_value_daily v1 ON v1.player_id = v.player_id AND v1.day = d.day - 1 AND v1.source = v.source
			WHERE v.day = d.day AND v.status <> 'out_of_league' AND v.market_value > 0 AND v1.market_value > 0`)
	]);

	return {
		up: up as Mover[],
		down: down as Mover[],
		up_pct: upPct as Mover[],
		down_pct: downPct as Mover[],
		total_up: Number(totals[0]?.total_up ?? 0),
		total_down: Number(totals[0]?.total_down ?? 0)
	};
}

export async function standing() {
	const rows = await q(`
		SELECT lt.team_id, lt.manager_name, lt.is_me, s.position, s.previous_position, s.points,
		       s.team_value::float8 AS team_value, COALESCE(lt.team_money, s.team_money)::float8 AS team_money,
		       (SELECT count(*) FROM ${SQUAD_NOW} q WHERE q.team_id = lt.team_id) AS players,
		       (SELECT count(*) FROM ${SQUAD_NOW} q WHERE q.team_id = lt.team_id
		           AND (q.clause_locked_until IS NULL OR q.clause_locked_until <= now()) AND NOT COALESCE(q.is_shielded, false)) AS open_clauses,
		       (SELECT COALESCE(sum(w.total_points), 0) FROM player_week_stats w
		          JOIN ${SQUAD_NOW} q ON q.player_id = w.player_id AND q.team_id = lt.team_id
		         WHERE w.week = (SELECT max(week) FROM player_week_stats)) AS last_week_points,
		       ce.cash_estimate::float8 AS cash_estimate, ce.uncertainty::float8 AS cash_uncertainty,
		       ce.clause_spend_observed::float8 AS clause_spend_observed
		FROM league_teams lt JOIN league_standing_daily s USING (league_id, team_id)
		LEFT JOIN manager_cash_estimate ce ON ce.league_id = lt.league_id AND ce.team_id = lt.team_id
		     AND ce.day = (SELECT max(day) FROM manager_cash_estimate)
		WHERE s.day = (SELECT max(day) FROM league_standing_daily)
		ORDER BY s.position`);
	return rows as {
		team_id: string;
		manager_name: string;
		is_me: boolean;
		position: number;
		previous_position: number | null;
		points: number;
		team_value: number;
		team_money: number | null;
		players: number;
		open_clauses: number;
		last_week_points: number;
		cash_estimate: number | null;
		cash_uncertainty: number | null;
		clause_spend_observed: number | null;
	}[];
}

export type ClauseRow = PlayerCard & {
	team_id_owner: string;
	owner: string;
	owner_is_me: boolean;
	buyout_clause: number;
	clause_locked_until: string | null;
	is_shielded: boolean | null;
	gap: number; // valor − cláusula (positivo = regalado)
};

/** Cláusulas de toda la liga a la última fecha. */
export async function clauses(): Promise<ClauseRow[]> {
	const rows = await q(`
		${LATEST_DAY}, q AS (SELECT * FROM ${SQUAD_NOW} sq_now)
		SELECT ${PLAYER_CARD}, q.team_id AS team_id_owner, lt.manager_name AS owner, lt.is_me AS owner_is_me,
		       q.buyout_clause::float8 AS buyout_clause, ${ISO('q.clause_locked_until')} AS clause_locked_until, q.is_shielded,
		       (v.market_value - q.buyout_clause)::float8 AS gap
		${PLAYER_JOINS}
		JOIN q ON q.player_id = p.player_id
		JOIN league_teams lt ON lt.team_id = q.team_id AND lt.league_id = q.league_id
		ORDER BY gap DESC`);
	return rows as ClauseRow[];
}

export async function activity(limit = 40) {
	const rows = await q(
		`SELECT a.activity_id, a.activity_type, a.amount::float8 AS amount, a.week, ${ISO('a.happened_at')} AS happened_at,
		        m1.manager_name AS manager, m1.is_me AS manager_is_me, m2.manager_name AS manager2,
		        p.player_id, p.name AS player, p.position_id, t.name AS club
		 FROM league_activity a
		 LEFT JOIN league_teams m1 ON m1.manager_id = a.manager_id AND m1.league_id = a.league_id
		 LEFT JOIN league_teams m2 ON m2.manager_id = a.manager2_id AND m2.league_id = a.league_id
		 LEFT JOIN players p ON p.player_id = a.player_id
		 LEFT JOIN teams t ON t.team_id = p.team_id
		 ORDER BY a.happened_at DESC LIMIT $1`,
		[limit]
	);
	return rows as {
		activity_id: string;
		activity_type: number;
		amount: number | null;
		week: number | null;
		happened_at: string;
		manager: string | null;
		manager_is_me: boolean | null;
		manager2: string | null;
		player_id: string | null;
		player: string | null;
		position_id: number | null;
		club: string | null;
	}[];
}

export type PlayerSetPieces = {
	pen_scored: number;
	pen_taken: number;
	corner_accurate: number;
	corner_taken: number;
	fk_on_target: number;
	fk_taken: number;
	cross_accurate: number;
	cross_taken: number;
	team_pen: number;
	team_corner: number;
	team_fk: number;
	team_cross: number;
	/** Si es el que mas cornners saca de su club. Un umbral fijo mentia: Trent saca el 48 % del
	 *  Real Madrid y es el primero, y la pantalla le decia "no es el primero". */
	corner_top: boolean;
};

export async function player(playerId: string) {
	const card = await q(`${LATEST_DAY} SELECT ${PLAYER_CARD}, p.updated_at::text AS updated_at ${PLAYER_JOINS} WHERE p.player_id = $1`, [playerId]);
	if (!card[0]) return null;
	const seriesQuery = q(
		`SELECT day::text AS day, market_value::float8 AS value, change::float8 AS change, source
		   FROM player_value_daily WHERE player_id = $1 ORDER BY day`,
		[playerId]
	);
	const weeksQuery = q(
		`SELECT week, total_points, stats FROM player_week_stats WHERE player_id = $1 ORDER BY week`,
		[playerId]
	);
	const ownerQuery = q(
		`SELECT lt.team_id, lt.manager_name, lt.is_me, q.buyout_clause::float8 AS buyout_clause,
		        ${ISO('q.clause_locked_until')} AS clause_locked_until, q.is_shielded
		 FROM ${SQUAD_NOW} q JOIN league_teams lt USING (league_id, team_id)
		 WHERE q.player_id = $1 LIMIT 1`,
		[playerId]
	);
	const onSaleQuery = q(
		`SELECT m.sale_price::float8 AS sale_price, m.kind, m.num_bids, m.num_offers,
		        m.offer_money::float8 AS offer_money, ${ISO('m.expires_at')} AS expires_at,
		        lt.manager_name AS seller, lt.is_me AS mine
		 FROM market_offer m LEFT JOIN league_teams lt ON lt.team_id = m.owner_team_id
		 WHERE m.player_id = $1 AND m.cycle_end = (SELECT max(cycle_end) FROM market_offer WHERE kind = 'marketPlayerLeague')
		   AND (m.expires_at IS NULL OR m.expires_at > now()) LIMIT 1`,
		[playerId]
	);
	const historyQuery = q(
		`SELECT a.activity_type, a.amount::float8 AS amount, ${ISO('a.happened_at')} AS happened_at,
		        m1.manager_name AS manager, m2.manager_name AS manager2
		 FROM league_activity a
		 LEFT JOIN league_teams m1 ON m1.manager_id = a.manager_id AND m1.league_id = a.league_id
		 LEFT JOIN league_teams m2 ON m2.manager_id = a.manager2_id AND m2.league_id = a.league_id
		 WHERE a.player_id = $1 ORDER BY a.happened_at DESC`,
		[playerId]
	);
	// Balon parado: lo suyo y el total de su equipo, que es el denominador de "lanza el 80 %".
	const balonQuery = q(
		`WITH d AS (SELECT max(day) AS day FROM player_set_pieces)
		 SELECT s.pen_scored, s.pen_taken, s.corner_accurate, s.corner_taken,
		        s.fk_on_target, s.fk_taken, s.cross_accurate, s.cross_taken,
		        COALESCE(e.pen_taken, 0) AS team_pen, COALESCE(e.corner_taken, 0) AS team_corner,
		        COALESCE(e.fk_taken, 0) AS team_fk, COALESCE(e.cross_taken, 0) AS team_cross,
		        s.corner_taken > 0 AND s.corner_taken = (
		          SELECT max(s2.corner_taken) FROM player_set_pieces s2
		          JOIN players p2 ON p2.player_id = s2.player_id
		          WHERE p2.team_id = pl.team_id AND s2.day = d.day) AS corner_top
		   FROM player_set_pieces s
		   CROSS JOIN d
		   JOIN players pl ON pl.player_id = s.player_id
		   LEFT JOIN team_set_pieces e ON e.team_id = pl.team_id AND e.day = s.day
		  WHERE s.player_id = $1 AND s.day = d.day`,
		[playerId]
	);

	const availabilityQuery = q(
		`SELECT ${START_PROB()} AS start_prob, av.injured, av.suspended, av.booking_risk,
		        av.minutes, av.games, ${ISO('av.fetched_at')} AS fetched_at,
		        'https://www.futbolfantasy.com/jugadores/' || a.external_key AS source_url
		 FROM player_availability av
		 LEFT JOIN player_aliases a ON a.player_id = av.player_id AND a.source = 'futbolfantasy_lineups'
		 WHERE av.player_id = $1 AND av.day = (SELECT max(day) FROM player_availability) LIMIT 1`,
		[playerId]
	);

	const seasonStatsQuery = q(
		`SELECT form::float8 AS form, hierarchy, goals, assists, yellows, reds,
		        games, games_as_sub, games_subbed_off, minutes
		 FROM player_season_stats
		 WHERE player_id = $1 AND day = (SELECT max(day) FROM player_season_stats) LIMIT 1`,
		[playerId]
	);

	const nextWeekRowQuery = q(
		`WITH n AS (${NEXT_WEEK}) SELECT n.week FROM n`
	);

	const recentMatchesQuery = q(
		`SELECT m.match_id, m.week, ${ISO('m.match_date')} AS match_date,
		        m.local_team_id, m.visitor_team_id,
		        tl.name AS local_name, tl.slug AS local_slug, tl.badge_url AS local_badge,
		        tv.name AS visitor_name, tv.slug AS visitor_slug, tv.badge_url AS visitor_badge,
		        m.local_score, m.visitor_score,
		        m.local_team_id = pl.team_id AS is_home,
		        w.total_points,
		        (w.stats->'mins_played'->0)::int AS mins_played
		 FROM matches m
		 JOIN players pl ON pl.player_id = $1
		 JOIN teams tl ON tl.team_id = m.local_team_id
		 JOIN teams tv ON tv.team_id = m.visitor_team_id
		 LEFT JOIN player_week_stats w ON w.player_id = pl.player_id AND w.week = m.week
		 WHERE (m.local_team_id = pl.team_id OR m.visitor_team_id = pl.team_id)
		   AND m.state = 7
		 ORDER BY m.match_date DESC LIMIT 5`,
		[playerId]
	);

	const upcomingMatchesQuery = q(
		`SELECT m.match_id, m.week, ${ISO('m.match_date')} AS match_date,
		        m.local_team_id, m.visitor_team_id,
		        tl.name AS local_name, tl.slug AS local_slug, tl.badge_url AS local_badge,
		        tv.name AS visitor_name, tv.slug AS visitor_slug, tv.badge_url AS visitor_badge,
		        m.local_team_id = pl.team_id AS is_home,
		        f.xg_local::float8 AS xg_local, f.xg_visitor::float8 AS xg_visitor,
		        f.p_local::float8 AS p_local, f.p_draw::float8 AS p_draw, f.p_visitor::float8 AS p_visitor,
		        f.cs_local::float8 AS cs_local, f.cs_visitor::float8 AS cs_visitor
		 FROM matches m
		 JOIN players pl ON pl.player_id = $1
		 JOIN teams tl ON tl.team_id = m.local_team_id
		 JOIN teams tv ON tv.team_id = m.visitor_team_id
		 LEFT JOIN match_forecast f ON f.match_id = m.match_id
		 WHERE (m.local_team_id = pl.team_id OR m.visitor_team_id = pl.team_id)
		   AND m.state != 7
		 ORDER BY m.match_date ASC LIMIT 5`,
		[playerId]
	);

	const [series, weeks, owner, onSale, history, balon, availability, seasonStats, nextWeekRow, recentMatches, upcomingMatches] = await Promise.all([
		seriesQuery, weeksQuery, ownerQuery, onSaleQuery, historyQuery, balonQuery,
		availabilityQuery, seasonStatsQuery, nextWeekRowQuery, recentMatchesQuery, upcomingMatchesQuery
	]);

	return {
		card: card[0] as PlayerCard & { updated_at: string },
		setPieces: balon[0] as PlayerSetPieces | undefined,
		series: series as { day: string; value: number; change: number | null; source: string }[],
		weeks: weeks as { week: number; total_points: number | null; stats: Record<string, [number, number]> | null }[],
		owner: owner[0] as
			| { team_id: string; manager_name: string; is_me: boolean; buyout_clause: number; clause_locked_until: string | null; is_shielded: boolean | null }
			| undefined,
		onSale: onSale[0] as
			| {
					sale_price: number;
					kind: string;
					num_bids: number | null;
					num_offers: number | null;
					offer_money: number | null;
					expires_at: string | null;
					seller: string | null;
					mine: boolean | null;
			  }
			| undefined,
		history: history as { activity_type: number; amount: number | null; happened_at: string; manager: string | null; manager2: string | null }[],
		availability: availability[0] as PlayerAvailability | undefined,
		seasonStats: seasonStats[0] as PlayerSeasonStats | undefined,
		nextWeek: (nextWeekRow[0]?.week as number) ?? null,
		recentMatches: recentMatches as PlayerMatch[],
		upcomingMatches: upcomingMatches as PlayerMatch[]
	};
}

// Cara a cara necesita una foto breve, no la ficha completa (histórico, partidos y actividad).
// Una sola consulta trae los dos jugadores y sus datos comparables.
export type ComparisonPlayer = {
	card: PlayerCard;
	availability: { start_prob: number | null } | null;
	setPieces: { pen_taken: number; corner_taken: number; fk_taken: number } | null;
	owner: { manager_name: string; is_me: boolean } | null;
	onSale: boolean;
};

export async function comparisonPlayers(ids: string[]): Promise<Map<string, ComparisonPlayer>> {
	if (!ids.length) return new Map();
	const rows = await q(
		`${LATEST_DAY}, av_day AS (SELECT max(day) AS day FROM player_availability),
		 sp_day AS (SELECT max(day) AS day FROM player_set_pieces)
		 SELECT ${PLAYER_CARD}, ${START_PROB()} AS start_prob,
		        sp.pen_taken, sp.corner_taken, sp.fk_taken,
		        owner.manager_name, owner.is_me,
		        EXISTS (
		          SELECT 1 FROM market_offer mo
		          WHERE mo.player_id = p.player_id
		            AND mo.cycle_end = (SELECT max(cycle_end) FROM market_offer WHERE kind = 'marketPlayerLeague')
		            AND (mo.expires_at IS NULL OR mo.expires_at > now())
		        ) AS on_sale
		 ${PLAYER_JOINS}
		 LEFT JOIN player_availability av ON av.player_id = p.player_id AND av.day = (SELECT day FROM av_day)
		 LEFT JOIN player_set_pieces sp ON sp.player_id = p.player_id AND sp.day = (SELECT day FROM sp_day)
		 LEFT JOIN LATERAL (
		   SELECT lt.manager_name, lt.is_me FROM ${SQUAD_NOW} sq
		   JOIN league_teams lt ON lt.league_id = sq.league_id AND lt.team_id = sq.team_id
		   WHERE sq.player_id = p.player_id LIMIT 1
		 ) owner ON true
		 WHERE p.player_id = ANY($1::text[])`,
		[ids]
	);
	return new Map(rows.map((row: any) => [row.player_id, {
		card: row as PlayerCard,
		availability: row.start_prob == null ? null : { start_prob: row.start_prob },
		setPieces: row.pen_taken == null && row.corner_taken == null && row.fk_taken == null
			? null
			: { pen_taken: row.pen_taken ?? 0, corner_taken: row.corner_taken ?? 0, fk_taken: row.fk_taken ?? 0 },
		owner: row.manager_name == null ? null : { manager_name: row.manager_name, is_me: row.is_me },
		onSale: row.on_sale
	}]));
}

export async function searchPlayers(
	term = '',
	limit = 30,
	options: { positionId?: number; sortBy?: 'valor' | 'puntos' | 'subida' } = {}
) {
	const whereClauses: string[] = [];
	const params: unknown[] = [];

	if (term && term.trim()) {
		params.push(`%${term.trim()}%`);
		whereClauses.push(
			`(unaccent(p.name) ILIKE unaccent($${params.length}) OR unaccent(COALESCE(p.nickname, '')) ILIKE unaccent($${params.length}))`
		);
	}

	if (options.positionId && options.positionId > 0) {
		params.push(options.positionId);
		whereClauses.push(`p.position_id = $${params.length}`);
	}

	const whereSql = whereClauses.length ? `WHERE ${whereClauses.join(' AND ')}` : '';

	let orderSql = 'ORDER BY v.market_value DESC';
	if (options.sortBy === 'puntos') {
		orderSql = 'ORDER BY v.points_total DESC, v.market_value DESC';
	} else if (options.sortBy === 'subida') {
		orderSql = 'ORDER BY (v.market_value - COALESCE(v1.market_value, v.market_value)) DESC';
	}

	params.push(limit);
	const rows = await q(
		`${LATEST_DAY} SELECT ${PLAYER_CARD} ${PLAYER_JOINS}
		 ${whereSql}
		 ${orderSql} LIMIT $${params.length}`,
		params
	);
	return rows as PlayerCard[];
}


export type Threat = {
	player_id: string;
	name: string;
	nickname: string | null;
	value: number;
	buyout_clause: number;
	clause_locked_until: string | null;
	is_shielded: boolean | null;
	threats: { manager_name: string; cash_estimate: number; uncertainty: number }[];
};

/** Para cada jugador mío: qué rivales tienen saldo estimado suficiente para pagar su cláusula. */
export async function threats(teamId: string): Promise<Threat[]> {
	const rows = await q(
		`WITH d AS (SELECT max(day) AS day FROM league_squad_daily WHERE team_id = $1),
		      v AS (SELECT max(day) AS day FROM player_value_daily WHERE source = 'laliga_api'),
		      c AS (SELECT * FROM manager_cash_estimate WHERE day = (SELECT max(day) FROM manager_cash_estimate))
		SELECT p.player_id, p.name, p.nickname, pv.market_value::float8 AS value,
		       s.buyout_clause::float8 AS buyout_clause,
		       ${ISO('s.clause_locked_until')} AS clause_locked_until, s.is_shielded,
		       COALESCE((SELECT jsonb_agg(jsonb_build_object('manager_name', lt.manager_name,
		                        'cash_estimate', c.cash_estimate, 'uncertainty', c.uncertainty)
		                        ORDER BY c.cash_estimate DESC)
		                 FROM c JOIN league_teams lt ON lt.league_id = c.league_id AND lt.team_id = c.team_id
		                WHERE NOT lt.is_me AND c.cash_estimate >= s.buyout_clause), '[]') AS threats
		FROM league_squad_daily s CROSS JOIN d CROSS JOIN v
		JOIN players p ON p.player_id = s.player_id
		JOIN player_value_daily pv ON pv.player_id = p.player_id AND pv.day = v.day
		WHERE s.team_id = $1 AND s.day = d.day
		ORDER BY s.buyout_clause DESC`,
		[teamId]
	);
	return rows as Threat[];
}


export type Listing = Offer & { value_when_listed: number | null; falling_days: number };

/** Mis jugadores puestos a la venta, con la oferta recibida y lo que cuesta esperar. */
export async function myListings(teamId: string): Promise<Listing[]> {
	const rows = await q(
		`${LATEST_DAY}, m AS (
			SELECT * FROM market_offer
			 WHERE cycle_end = (SELECT max(cycle_end) FROM market_offer WHERE kind = 'marketPlayerLeague')
			   AND (expires_at IS NULL OR expires_at > now()) AND owner_team_id = $1)
		SELECT ${PLAYER_CARD}, m.market_id, m.sale_price::float8 AS sale_price, m.kind,
		       m.num_bids, m.num_offers, m.offer_money::float8 AS offer_money,
		       m.buyout_clause::float8 AS buyout_clause, ${ISO('m.expires_at')} AS expires_at,
		       m.owner_team_id, NULL::text AS seller, true AS mine,
		       NULL::float8 AS value_when_listed,
		       (SELECT count(*) FROM (
		          SELECT s.market_value, lag(s.market_value) OVER (ORDER BY s.day) AS prev, s.day
		            FROM player_value_daily s WHERE s.player_id = p.player_id AND s.day > d.day - 20
		          ) w WHERE w.prev IS NOT NULL AND w.market_value < w.prev
		            AND w.day > COALESCE((SELECT max(x.day) FROM (
		              SELECT s2.day, s2.market_value, lag(s2.market_value) OVER (ORDER BY s2.day) AS prev2
		                FROM player_value_daily s2 WHERE s2.player_id = p.player_id AND s2.day > d.day - 20
		              ) x WHERE x.prev2 IS NOT NULL AND x.market_value >= x.prev2), d.day - 20)
		       ) AS falling_days
		${PLAYER_JOINS}
		JOIN m ON m.player_id = p.player_id
		ORDER BY m.expires_at`,
		[teamId]
	);
	return rows as Listing[];
}


export type Reason = { code: string; text: string; value: number | null; source: string };
export type TrendOutlook = {
	status: 'validated' | 'insufficient' | 'unvalidated' | 'not_rising';
	streak: number;
	streak_censored: boolean;
	horizon: number;
	n?: number;
	days?: number;
	low_days?: number;
	high_days?: number;
	stop_within_3d?: number;
};
export type Rec = {
	availability_at: string | null;
	availability_url: string | null;
	id: number;
	kind: 'buy' | 'sell';
	player_id: string;
	name: string;
	verdict: string;
	score: number;
	value: number | null;
	max_bid: number | null;
	affordable_max: number | null;
	min_price: number | null;
	margin_required: number | null;
	bid_sample: number | null;
	drift: number | null;
	drift_low: number | null;
	drift_high: number | null;
	drift_n: number | null;
	up_rate: number | null;
	trend: TrendOutlook | null;
	value_day: string | null;
	history_days: number | null;
	image_url: string | null;
	bid_to_win: number | null;
	expected_resale: number | null;
	num_bids: number | null;
	streak: number | null;
	xpts: number | null;
	fixture_factor: number | null;
	sport_value: number | null;
	club_share: number | null;
	start_prob: number | null;
	fixture_label: string | null;
	club_name: string | null;
	position_id: number | null;
	eleven_gain: number | null; // puntos por jornada que gana (compra) o pierde (venta) tu once
	incomplete_eleven: boolean;
	missing_eleven: string[];
	completes_eleven: boolean;
	breaks_eleven: boolean;
	thesis: boolean;
	rebound: string | null; // señal de rebote que pasó su prueba (analysis/rebound.py)
	created_at: string;
	reasons: Reason[];
};

/** Recomendaciones del día, ya calculadas por el job. La web no decide nada: solo las muestra. */
export async function recommendations(): Promise<Rec[]> {
	const rows = await q(`
		SELECT r.id, r.kind, r.subject->>'player_id' AS player_id, r.subject->>'name' AS name,
		       r.subject->>'verdict' AS verdict, r.score::float8 AS score,
		       (r.subject->>'value')::float8 AS value,
		       (r.subject->>'max_bid')::float8 AS max_bid,
		       (r.subject->>'affordable_max')::float8 AS affordable_max,
		       (r.subject->>'min_price')::float8 AS min_price,
		       (r.subject->>'margin_required')::float8 AS margin_required,
		       (r.subject->>'bid_sample')::int AS bid_sample,
		       (r.subject->>'drift')::float8 AS drift,
		       (r.subject->>'drift_low')::float8 AS drift_low,
		       (r.subject->>'drift_high')::float8 AS drift_high,
		       (r.subject->>'drift_n')::int AS drift_n,
		       (r.subject->>'up_rate')::float8 AS up_rate,
		       r.subject->'trend' AS trend,
		       r.subject->>'value_day' AS value_day,
		       (r.subject->>'history_days')::int AS history_days,
		       p.image_url,
		       (r.subject->>'bid_to_win')::float8 AS bid_to_win,
		       (r.subject->>'expected_resale')::float8 AS expected_resale,
		       (r.subject->>'num_bids')::int AS num_bids,
		       (r.subject->>'streak')::int AS streak,
		       (r.subject->>'xpts')::float8 AS xpts,
		       (r.subject->>'fixture_factor')::float8 AS fixture_factor,
		       (r.subject->>'sport_value')::float8 AS sport_value,
		       (r.subject->>'club_share')::float8 AS club_share,
		       CASE WHEN (r.subject->>'availability_at')::timestamptz >= now() - interval '26 hours'
		         AND (r.subject->>'start_prob')::float8 >= 0 AND (r.subject->>'start_prob')::float8 < 1
		         THEN (r.subject->>'start_prob')::float8 END AS start_prob,
		       r.subject->>'availability_at' AS availability_at,
		       'https://www.futbolfantasy.com/jugadores/' || a.external_key AS availability_url,
		       r.subject->>'fixture_label' AS fixture_label,
		       COALESCE(r.subject->>'club_name', t.name) AS club_name,
		       (r.subject->>'eleven_gain')::float8 AS eleven_gain,
		       COALESCE((r.subject->>'incomplete_eleven')::boolean, false) AS incomplete_eleven,
		       COALESCE(r.subject->'missing_eleven', '[]'::jsonb) AS missing_eleven,
		       (SELECT position_id FROM players WHERE player_id = r.subject->>'player_id') AS position_id,
		       COALESCE((r.subject->>'completes_eleven')::boolean, false) AS completes_eleven,
		       COALESCE((r.subject->>'breaks_eleven')::boolean, false) AS breaks_eleven,
		       COALESCE((r.subject->>'thesis')::boolean, false) AS thesis,
		       r.subject->>'rebound' AS rebound,
		       ${ISO('r.created_at')} AS created_at, r.reasons
		FROM recommendations r
		LEFT JOIN players p ON p.player_id = r.subject->>'player_id'
		LEFT JOIN player_aliases a ON a.player_id = p.player_id AND a.source = 'futbolfantasy_lineups'
		LEFT JOIN teams t ON t.team_id = p.team_id
		-- Solo la última tanda. Cada recálculo escribe todas las filas de golpe, así que su
		-- created_at las identifica. Leer "las últimas 36 horas" mezclaba la foto de ayer con la de
		-- hoy y cada jugador salía dos veces con cifras distintas (2026-09-09: 28 filas, 14 jugadores).
		WHERE r.created_at = (SELECT max(created_at) FROM recommendations)
		ORDER BY (r.kind = 'sell'), COALESCE((r.subject->>'completes_eleven')::boolean, false) DESC, r.score DESC`);
	return rows as Rec[];
}

// --- Jornada -----------------------------------------------------------------------------------
// El pronóstico lo calcula el job (analysis/fixtures.py) y lo deja en `match_forecast`: aquí solo
// se lee. Si se calculara también aquí habría dos modelos y acabarían diciendo cosas distintas.

export type Match = {
	match_id: string;
	week: number;
	date: string | null;
	local_id: string;
	local: string;
	local_slug: string | null;
	local_badge: string | null;
	visitor_id: string;
	visitor: string;
	visitor_slug: string | null;
	visitor_badge: string | null;
	xg_local: number | null;
	xg_visitor: number | null;
	p_local: number | null;
	p_draw: number | null;
	p_visitor: number | null;
	cs_local: number | null;
	cs_visitor: number | null;
	played: number | null;
	local_score: number | null;
	visitor_score: number | null;
};

/**
 * Los partidos de la jornada en curso en adelante, con su pronóstico.
 *
 * Incluye los que ya se jugaron dentro de esas jornadas —los adelantados— con su resultado. Si se
 * filtraran, la rejilla de próximas jornadas les dejaba una raya que se lee como «no hay dato»
 * cuando lo que había era un Real Sociedad 0-0 Celta jugado el 3 de septiembre.
 */
export async function fixtures(): Promise<Match[]> {
	const rows = await q(`
		SELECT m.match_id, m.week, ${ISO('m.match_date')} AS date,
		       m.local_team_id AS local_id, tl.name AS local, tl.slug AS local_slug, tl.badge_url AS local_badge,
		       m.visitor_team_id AS visitor_id, tv.name AS visitor, tv.slug AS visitor_slug, tv.badge_url AS visitor_badge,
		       f.xg_local::float8, f.xg_visitor::float8,
		       f.p_local::float8, f.p_draw::float8, f.p_visitor::float8,
		       f.cs_local::float8, f.cs_visitor::float8, f.played,
		       m.local_score, m.visitor_score
		FROM matches m
		JOIN teams tl ON tl.team_id = m.local_team_id
		JOIN teams tv ON tv.team_id = m.visitor_team_id
		LEFT JOIN match_forecast f ON f.match_id = m.match_id
		WHERE m.week >= (SELECT week FROM (${NEXT_WEEK}) AS n)
		ORDER BY m.week, m.match_date`);
	return rows as Match[];
}

export type SquadByTeam = {
	team_id: string;
	player_id: string;
	name: string;
	position_id: number;
	value: number;
	start_prob: number | null;
	injured: boolean | null;
	suspended: boolean | null;
	mine: boolean;
};

/** Jugadores con dueño en la liga, para saber en qué partidos te juegas algo y qué se te escapa. */
export async function ownedByTeam(): Promise<SquadByTeam[]> {
	const rows = await q(`
		WITH d AS (SELECT max(day) AS day FROM league_squad_daily),
		     v AS (SELECT max(day) AS day FROM player_value_daily WHERE source = 'laliga_api'),
		     a AS (SELECT max(day) AS day FROM player_availability)
		SELECT p.team_id, p.player_id, COALESCE(p.nickname, p.name) AS name, p.position_id,
		       pv.market_value::float8 AS value,
		       ${START_PROB()} AS start_prob, av.injured, av.suspended, lt.is_me AS mine
		FROM league_squad_daily s
		CROSS JOIN d CROSS JOIN v CROSS JOIN a
		JOIN league_teams lt ON lt.league_id = s.league_id AND lt.team_id = s.team_id
		JOIN players p ON p.player_id = s.player_id
		LEFT JOIN player_value_daily pv ON pv.player_id = p.player_id AND pv.day = v.day
		LEFT JOIN player_availability av ON av.player_id = p.player_id AND av.day = a.day
		WHERE s.day = d.day
		ORDER BY lt.is_me DESC, pv.market_value DESC`);
	return rows as SquadByTeam[];
}

export type SetPiece = {
	player_id: string;
	name: string;
	team_id: string;
	position_id: number;
	pen_scored: number;
	pen_taken: number;
	corner_taken: number;
	cross_taken: number;
	fk_taken: number;
	team_pen: number;
	team_corner: number;
	team_cross: number;
	team_fk: number;
};

/**
 * Quién lanza el balón parado de cada equipo. El total del equipo viene de `team_set_pieces` y no
 * de sumar a estos jugadores: sumando solo a los que casamos, la Real Sociedad daba 18 córners en
 * vez de 24 y a Sergio Gómez le salía un 72 % en lugar de su 54 % real.
 */
export async function setPieces(): Promise<SetPiece[]> {
	const rows = await q(`
		WITH d AS (SELECT max(day) AS day FROM player_set_pieces)
		SELECT s.player_id, COALESCE(p.nickname, p.name) AS name, p.team_id, p.position_id,
		       s.pen_scored, s.pen_taken, s.corner_taken, s.cross_taken, s.fk_taken,
		       COALESCE(e.pen_taken, 0) AS team_pen, COALESCE(e.corner_taken, 0) AS team_corner,
		       COALESCE(e.cross_taken, 0) AS team_cross, COALESCE(e.fk_taken, 0) AS team_fk
		FROM player_set_pieces s
		CROSS JOIN d
		JOIN players p ON p.player_id = s.player_id
		LEFT JOIN team_set_pieces e ON e.team_id = p.team_id AND e.day = s.day
		WHERE s.day = d.day
		ORDER BY s.corner_taken + s.cross_taken + 5 * s.pen_taken DESC`);
	return rows as SetPiece[];
}

export type Bargain = PlayerCard & {
	expected: number;
	surplus: number;
	peers: number;
	owner: string | null;
	owner_is_me: boolean | null;
	sale_price: number | null;
};

/**
 * Quién rinde por encima de lo que cuesta. Lo calcula el job (`analysis/bargains.py`) comparando a
 * cada jugador con los de su misma posición que cuestan lo mismo: puntos por millón a secas es
 * ordenar por barato, porque la mediana cae de 3,18 p/M en el tramo de 1-5 M a 0,49 por encima de
 * 40 M. Aquí solo se lee, y se añade quién lo tiene, que es lo que decide si se puede pujar.
 */
export async function bargains(limit = 15): Promise<{ mejores: Bargain[]; peores: Bargain[] }> {
	const rows = await q(
		`${LATEST_DAY}, b AS (SELECT max(day) AS day FROM player_bargain)
		 SELECT ${PLAYER_CARD},
		        pb.expected::float8 AS expected, pb.surplus::float8 AS surplus, pb.peers,
		        lt.manager_name AS owner, lt.is_me AS owner_is_me,
		        mo.sale_price::float8 AS sale_price
		 ${PLAYER_JOINS}
		 CROSS JOIN b
		 JOIN player_bargain pb ON pb.player_id = p.player_id AND pb.day = b.day
		 LEFT JOIN ${SQUAD_NOW} sq ON sq.player_id = p.player_id
		 LEFT JOIN league_teams lt ON lt.league_id = sq.league_id AND lt.team_id = sq.team_id
		 LEFT JOIN market_offer mo ON mo.player_id = p.player_id
		      AND mo.cycle_end = (SELECT max(cycle_end) FROM market_offer WHERE kind = 'marketPlayerLeague')
		 ORDER BY pb.surplus DESC`
	);
	const todos = rows as Bargain[];
	return { mejores: todos.slice(0, limit), peores: todos.slice(-6).reverse() };
}

export type PriceTier = 'low' | 'mid' | 'high' | 'premium';

export type PriceTierPick = PlayerCard & {
	start_prob: number | null;
	injured: boolean | null;
	suspended: boolean | null;
	surplus: number | null;
	pen_taken: number;
	corner_taken: number;
	fault_taken: number;
	owner: string | null;
	owner_is_me: boolean | null;
	sale_price: number | null;
	score: number;
	tier: PriceTier;
	rank_in_tier: number;
};

/**
 * Recomendaciones de fichajes organizadas por posición y tramos de precio:
 * - < 5 M: Parches y chollos low-cost
 * - 5 - 15 M: Titulares solventes y rentables
 * - 15 - 30 M: Estrellas y diferenciales
 * - > 30 M: Cracks y capitanes
 * Pondera media de puntos, probabilidad de titularidad, surplus sobre coste y lanzadores a balón parado.
 */
export async function topPicksByPriceTier(limitPerGroup = 12): Promise<PriceTierPick[]> {
	const rows = await q(
		`${LATEST_DAY},
		 av_day AS (SELECT max(day) AS day FROM player_availability),
		 b_day AS (SELECT max(day) AS day FROM player_bargain),
		 psp_day AS (SELECT max(day) AS day FROM player_set_pieces),
		 ranked AS (
		   SELECT ${PLAYER_CARD},
		          ${START_PROB()} AS start_prob,
		          av.injured, av.suspended,
		          pb.surplus::float8 AS surplus,
		          COALESCE(psp.pen_taken, 0)::int AS pen_taken,
		          COALESCE(psp.corner_taken, 0)::int AS corner_taken,
		          COALESCE(psp.fk_taken, 0)::int AS fault_taken,
		          lt.manager_name AS owner,
		          lt.is_me AS owner_is_me,
		          mo.sale_price::float8 AS sale_price,
		          (
		            COALESCE(v.average_points::float8, 0) * 0.7 +
		            COALESCE(${START_PROB()}, 0.5) * 4.0 +
		            COALESCE(pb.surplus::float8, 0) * 0.2 +
		            CASE WHEN COALESCE(psp.pen_taken, 0) > 0 THEN 1.5 ELSE 0 END +
		            CASE WHEN COALESCE(psp.corner_taken, 0) > 2 THEN 0.8 ELSE 0 END
		          )::float8 as score,
		          CASE
		            WHEN v.market_value < 5000000 THEN 'low'
		            WHEN v.market_value < 15000000 THEN 'mid'
		            WHEN v.market_value < 30000000 THEN 'high'
		            ELSE 'premium'
		          END as tier,
		          ROW_NUMBER() OVER (
		            PARTITION BY p.position_id,
		                         CASE
		                           WHEN v.market_value < 5000000 THEN 'low'
		                           WHEN v.market_value < 15000000 THEN 'mid'
		                           WHEN v.market_value < 30000000 THEN 'high'
		                           ELSE 'premium'
		                         END
		            ORDER BY (
		              COALESCE(v.average_points::float8, 0) * 0.7 +
		              COALESCE(${START_PROB()}, 0.5) * 4.0 +
		              COALESCE(pb.surplus::float8, 0) * 0.2 +
		              CASE WHEN COALESCE(psp.pen_taken, 0) > 0 THEN 1.5 ELSE 0 END +
		              CASE WHEN COALESCE(psp.corner_taken, 0) > 2 THEN 0.8 ELSE 0 END
		            ) DESC
		          ) as rank_in_tier
		   ${PLAYER_JOINS}
		   LEFT JOIN player_availability av ON av.player_id = p.player_id AND av.day = (SELECT day FROM av_day)
		   LEFT JOIN player_bargain pb ON pb.player_id = p.player_id AND pb.day = (SELECT day FROM b_day)
		   LEFT JOIN player_set_pieces psp ON psp.player_id = p.player_id AND psp.day = (SELECT day FROM psp_day)
		   LEFT JOIN ${SQUAD_NOW} sq ON sq.player_id = p.player_id
		   LEFT JOIN league_teams lt ON lt.league_id = sq.league_id AND lt.team_id = sq.team_id
		   LEFT JOIN market_offer mo ON mo.player_id = p.player_id AND mo.cycle_end = (SELECT max(cycle_end) FROM market_offer WHERE kind = 'marketPlayerLeague')
		   WHERE v.market_value > 0 AND p.position_id BETWEEN 1 AND 4
		 )
		 SELECT * FROM ranked WHERE rank_in_tier <= $1 ORDER BY score DESC`,
		[limitPerGroup]
	);
	return rows as PriceTierPick[];
}

// --- Semáforo y recomendador de ventas de plantilla ---------------------------------------------

export type SellDecision = 'urgent' | 'recommended' | 'keep';

export type SellReason = {
	icon: string;
	title: string;
	desc: string;
	severity: 'high' | 'medium' | 'positive';
};

export type SquadSellAnalysis = PlayerCard & {
	start_prob: number | null;
	injured: boolean | null;
	suspended: boolean | null;
	surplus: number | null;
	form: number | null;
	hierarchy: string | null;
	in_eleven: boolean;
	xpts: number | null;
	sell_score: number;
	decision: SellDecision;
	reasons: SellReason[];
	action_summary: string;
};

export type SquadSellAdvisorResult = {
	players: SquadSellAnalysis[];
	urgentCount: number;
	recommendedCount: number;
	keepCount: number;
	hasGoalkeeper: boolean;
	deficitWarning: string | null;
};

/**
 * Analiza todos los jugadores de tu plantilla y calcula un Sell Score (0 - 100) y un Semáforo de Ventas
 * (urgente, recomendable, mantener) combinando:
 * - Sangría financiera (caída hoy, 7 días)
 * - Probabilidad de titularidad y minutos
 * - Bajas médicas o disciplinarias (lesiones, sanciones)
 * - Rendimiento y puntos vs coste de mercado
 * - Rol en plantilla (suplente caro fuera del once ideal)
 */
// Mínimos de cualquier formación válida (analysis/eleven.py, MINIMOS).
const ELEVEN_MIN: Record<number, number> = { 1: 1, 2: 3, 3: 3, 4: 1 };

/** ¿Te quedarías sin once válido si vendieras a este jugador? Solo cuenta a los que pueden jugar. */
function isNeededForEleven(pos: number, playerId: string, squad: any[]): boolean {
	const ok = squad.filter((p) => !p.injured && !p.suspended);
	if (!ok.some((p) => p.player_id === playerId)) return false;
	const same = ok.filter((p) => p.position_id === pos).length;
	return same <= (ELEVEN_MIN[pos] ?? 0) || ok.length <= 11;
}

export async function squadSellAdvisor(teamId: string): Promise<SquadSellAdvisorResult> {
	const rows = await q(
		`${LATEST_DAY},
		 s_day AS (SELECT max(day) AS day FROM league_squad_daily WHERE team_id = $1),
		 av_day AS (SELECT max(day) AS day FROM player_availability),
		 b_day AS (SELECT max(day) AS day FROM player_bargain),
		 st_day AS (SELECT max(day) AS day FROM player_season_stats),
		 l_day AS (SELECT max(day) AS day FROM lineup_daily WHERE team_id = $1),
		 rc_time AS (SELECT max(created_at) AS created_at FROM recommendations)
		 SELECT ${PLAYER_CARD},
		        rc.subject->>'verdict' AS rec_verdict,
		        (rc.subject->>'eleven_gain')::float8 AS rec_eleven_gain,
		        COALESCE((rc.subject->>'breaks_eleven')::boolean, false) AS rec_breaks,
		        ${START_PROB()} AS start_prob,
		        av.injured, av.suspended,
		        pb.surplus::float8 AS surplus,
		        st.form::float8 AS form, st.hierarchy,
		        COALESCE(ln.chosen, false) AS in_eleven,
		        ln.xpts::float8 AS xpts
		 ${PLAYER_JOINS}
		 JOIN league_squad_daily sq ON sq.player_id = p.player_id AND sq.team_id = $1 AND sq.day = (SELECT day FROM s_day)
		 LEFT JOIN player_availability av ON av.player_id = p.player_id AND av.day = (SELECT day FROM av_day)
		 LEFT JOIN player_bargain pb ON pb.player_id = p.player_id AND pb.day = (SELECT day FROM b_day)
		 LEFT JOIN player_season_stats st ON st.player_id = p.player_id AND st.day = (SELECT day FROM st_day)
			 LEFT JOIN lineup_daily ln ON ln.player_id = p.player_id AND ln.team_id = $1 AND ln.day = (SELECT day FROM l_day)
			      AND ln.formation IS NOT NULL
		 LEFT JOIN recommendations rc ON rc.kind = 'sell' AND rc.created_at = (SELECT created_at FROM rc_time)
		      AND rc.subject->>'player_id' = p.player_id
		 ORDER BY p.position_id, v.market_value DESC`,
		[teamId]
	);

	const theses = await thesisIds();
	const players: SquadSellAnalysis[] = rows.map((r: any) => {
		let score = 0;
		const reasons: SellReason[] = [];

		const diff1d = r.value_1d != null ? r.value - r.value_1d : 0;
		const diff7d = r.value_7d != null ? r.value - r.value_7d : 0;

		// 1. Pérdida económica
		if (diff1d < 0) {
			const dropPts = Math.min(25, 10 + Math.floor(Math.abs(diff1d) / 50000));
			score += dropPts;
			reasons.push({
				icon: '📉',
				title: `Baja ${signed(diff1d, 1)} hoy`,
				desc: 'Cada día que pasa en tu plantilla destruye valor de mercado.',
				severity: 'high'
			});
		} else if (diff1d > 150000) {
			score -= 20;
			reasons.push({
				icon: '🚀',
				title: `Sube ${signed(diff1d, 1)} hoy`,
				desc: 'Activo alcista: retener para seguir acumulando plusvalía.',
				severity: 'positive'
			});
		} else if (diff1d > 0) {
			score -= 8;
		}

		if (diff7d < 0) {
			score += 10;
			reasons.push({
				icon: '📉',
				title: `Acumula ${signed(diff7d, 1)} en 7 días`,
				desc: 'Tendencia semanal a la baja en el mercado de LaLiga.',
				severity: 'high'
			});
		} else if (diff7d > 1000000) {
			score -= 15;
		}

		// 2. Disponibilidad y minutos
		const injured = Boolean(r.injured);
		const suspended = Boolean(r.suspended);
		const startProb = r.start_prob;

		if (injured) {
			if (r.value > 40000000) {
				score += 15;
				reasons.push({
					icon: '🏥',
					title: 'Lesión confirmada',
					desc: 'Es un jugador de gran calibre; valora si la lesión es corta antes de soltarlo.',
					severity: 'medium'
				});
			} else {
				score += 30;
				reasons.push({
					icon: '🏥',
					title: 'Baja médica por lesión',
					desc: 'No jugará el próximo partido; inmoviliza presupuesto sin sumar puntos.',
					severity: 'high'
				});
			}
		} else if (suspended) {
			score += 20;
			reasons.push({
				icon: '🟥',
				title: 'Sancionado la próxima jornada',
				desc: 'Cumple ciclo de tarjetas o expulsión; no sumará puntos.',
				severity: 'high'
			});
		}

		if (startProb != null && startProb < 0.35) {
			score += 25;
			reasons.push({
				icon: '🪑',
				title: `Pocas opciones de inicio (${Math.round(startProb * 100)} %)`,
				desc: 'Estimación de FútbolFantasy para el próximo partido; puede entrar desde el banquillo.',
				severity: 'high'
			});
		} else if (startProb != null && startProb < 0.55) {
			score += 12;
			reasons.push({
				icon: '⚠️',
				title: `Rotación o duda (${Math.round(startProb * 100)} % titular)`,
				desc: 'Puesto no asegurado en el once titular de su club.',
				severity: 'medium'
			});
		} else if (startProb != null && startProb >= 0.7) {
			score -= 15;
			reasons.push({
				icon: '🛡️',
				title: `Titular probable (${Math.round(startProb * 100)} %)`,
				desc: 'La fuente prevé que salga de inicio; no es una alineación confirmada.',
				severity: 'positive'
			});
		}

		// 3. Rendimiento vs Coste
		const avgPts = r.average_points != null ? r.average_points : 0;
		if (avgPts < 1.5 && r.value > 1500000) {
			score += 20;
			reasons.push({
				icon: '⚖️',
				title: `Media pobre: ${num(avgPts, 1)} pts/j`,
				desc: `Aporta muy pocos puntos para costar ${money(r.value, 1)}.`,
				severity: 'high'
			});
		} else if (avgPts < 3.0 && r.value > 6000000) {
			score += 15;
			reasons.push({
				icon: '⚖️',
				title: `Bajo retorno: ${num(avgPts, 1)} pts/j`,
				desc: `Rendimiento escaso para una inversión de ${money(r.value, 1)}.`,
				severity: 'medium'
			});
		} else if (avgPts >= 6.0) {
			score -= 15;
			reasons.push({
				icon: '⭐',
				title: `Gran rendimiento: ${num(avgPts, 1)} pts/j`,
				desc: 'Promedio muy superior a la media de la liga.',
				severity: 'positive'
			});
		}

		if (r.surplus != null) {
			if (r.surplus < -3.0) {
				score += 10;
				reasons.push({
					icon: '⚠️',
					title: `Sobreprecio (${num(r.surplus, 1)} vs coste)`,
					desc: 'Rinde por debajo de otros jugadores de su mismo precio.',
					severity: 'medium'
				});
			} else if (r.surplus > 4.0) {
				score -= 10;
				reasons.push({
					icon: '💎',
					title: `Chollo (+${num(r.surplus, 1)} sobre coste)`,
					desc: 'Genera muchos más puntos que sus pares de mercado.',
					severity: 'positive'
				});
			}
		}

		// 4. Rol en plantilla
		if (!r.in_eleven && r.value > 4000000) {
			score += 10;
			reasons.push({
				icon: '💰',
				title: `Banquillo caro (${money(r.value, 1)})`,
				desc: 'No entra en el once óptimo; capital ocioso en el banquillo.',
				severity: 'medium'
			});
		}

		const finalScore = Math.max(0, Math.min(100, score));

		// **La decisión no la toma esta suma.** Las señales de arriba son hechos para leer (bajó hoy,
		// es suplente, está lesionado), pero sus pesos nunca se probaron contra lo que pasó después, y
		// durante una semana el semáforo decía «venta urgente» a jugadores que el recomendador —el que
		// sí supera su prueba hacia delante— mandaba aguantar, o a tu único portero. Ahora decide:
		//   1. lo imprescindible para alinear nunca se vende;
		//   2. el veredicto del recomendador (`analysis/recommend.py`);
		//   3. un hecho sin predicción: lesionado o sancionado y fuera de tu once, venderlo no te
		//      quita ni un punto y libera saldo.
		const pos = r.position_id as number;
		const imprescindible = r.rec_breaks || isNeededForEleven(pos, r.player_id, rows);
		let decision: SellDecision = 'keep';
		let action_summary = 'Mantener: ninguna señal contrastada aconseja venderlo hoy.';
		if (theses.has(r.player_id)) {
			reasons.unshift({
				icon: '',
				title: 'Es tu apuesta',
				desc: 'La marcaste tú: el mercado no ve lo que esperas de él, así que no se manda vender por una racha.',
				severity: 'positive'
			});
			action_summary = 'Tu apuesta: se mantiene mientras no la quites en su ficha.';
		} else if (imprescindible) {
			reasons.unshift({
				icon: '🧩',
				title: 'Imprescindible para alinear',
				desc: 'Sin él no llegas a los mínimos de un once válido (1 portero, 3 defensas, 3 medios, 1 delantero).',
				severity: 'positive'
			});
			action_summary = 'No lo vendas hasta tener sustituto: sin él no puedes alinear.';
		} else if (r.rec_verdict === 'vender') {
			decision = r.in_eleven ? 'recommended' : 'urgent';
			action_summary = r.in_eleven
				? 'Valóralo: lo que pierde de valor supera lo que suma a tu once.'
				: 'Véndelo: pierde valor y no juega en tu once, así que no te cuesta puntos.';
		} else if (r.rec_verdict === 'aguantar') {
			action_summary = 'Aguántalo: baja, pero esperar cuesta poco o sus puntos lo compensan (mira sus razones en Mercado).';
		} else if ((injured || suspended) && !r.in_eleven) {
			decision = 'recommended';
			action_summary = 'No jugará y no está en tu once: venderlo libera saldo sin perder puntos.';
		}

		return {
			...r,
			sell_score: finalScore,
			decision,
			reasons,
			action_summary
		};
	});

	// Primero lo que hay que vender, luego lo evaluable, luego el resto; dentro, por señales.
	const rank: Record<SellDecision, number> = { urgent: 0, recommended: 1, keep: 2 };
	players.sort((a, b) => rank[a.decision] - rank[b.decision] || b.sell_score - a.sell_score);

	const urgentCount = players.filter((p) => p.decision === 'urgent').length;
	const recommendedCount = players.filter((p) => p.decision === 'recommended').length;
	const keepCount = players.filter((p) => p.decision === 'keep').length;

	const hasGoalkeeper = players.some((p) => p.position_id === 1);
	let deficitWarning: string | null = null;
	if (!hasGoalkeeper) {
		deficitWarning = 'Tu plantilla no tiene ningún portero disponible. Te conviene vender algún descarte para liberar presupuesto y acudir al mercado antes de la próxima jornada.';
	}

	return {
		players,
		urgentCount,
		recommendedCount,
		keepCount,
		hasGoalkeeper,
		deficitWarning
	};
}

// --- El once ------------------------------------------------------------------------------------

export type ElevenPlayer = PlayerCard & {
	xpts: number | null;
	chosen: boolean;
	current: boolean;
	start_prob: number | null;
	injured: boolean | null;
	suspended: boolean | null;
};

export type ElevenView = {
	formation: string | null;
	feasible: number | null;
	forced: boolean | null;
	xpts: number;
	starters: ElevenPlayer[];
	bench: ElevenPlayer[];
} | null;

/**
 * El once que conviene poner y el que tienes puesto, tal como los dejó `analysis/eleven.py`.
 *
 * Las siete formaciones y el hecho de que no haya banquillo ni entrenador están comprobados contra
 * la API (`/v4/teams/lineup/formations?option=free` y el propio `lineup`), no supuestos: la página
 * llevaba una lista escrita a mano a la que le faltaba el 4-5-1.
 */
export async function eleven(teamId: string): Promise<ElevenView> {
	// **Solo el once del día de la plantilla.** Si el último cálculo es de otro día no se enseña:
	// el 2026-09-16 la pantalla mostraba un once con David Soria de portero, un jugador ya vendido,
	// porque el cálculo de hoy no pudo hacerse (sin portero no hay once) y quedaba el del día 15.
	// Un once con jugadores que ya no tienes es peor que no enseñar ninguno.
	const rows = await q(
		`${LATEST_DAY}, s AS (SELECT max(day) AS day FROM league_squad_daily),
		     l AS (SELECT max(day) AS day FROM lineup_daily WHERE team_id = $1 AND day = (SELECT day FROM s)),
		     a AS (SELECT max(day) AS day FROM player_availability)
		 SELECT ${PLAYER_CARD}, ln.xpts::float8 AS xpts, ln.chosen, ln.current,
		        ln.formation, ln.feasible, ln.forced,
		        ${START_PROB()} AS start_prob, av.injured, av.suspended
		 ${PLAYER_JOINS}
		 CROSS JOIN l CROSS JOIN a
		 JOIN lineup_daily ln ON ln.player_id = p.player_id AND ln.day = l.day AND ln.team_id = $1
		 LEFT JOIN player_availability av ON av.player_id = p.player_id AND av.day = a.day
		 ORDER BY p.position_id, ln.xpts DESC NULLS LAST`,
		[teamId]
	);
	if (!rows.length || !rows[0].formation) return null;
	const first = rows[0] as { formation: string | null; feasible: number | null; forced: boolean | null };
	const all = rows as ElevenPlayer[];
	const starters = all.filter((p) => p.chosen);
	return {
		formation: first.formation,
		feasible: first.feasible,
		forced: first.forced,
		xpts: starters.reduce((a, p) => a + (p.xpts ?? 0), 0),
		starters,
		bench: all.filter((p) => !p.chosen)
	};
}

/** Señales ya calculadas para simular el once sin volver a estimar puntos en la web. */
export async function plannerSquadSignals(teamId: string) {
	const rows = await q(
		`WITH s_day AS (SELECT max(day) AS day FROM league_squad_daily WHERE team_id = $1),
		      av_day AS (SELECT max(day) AS day FROM player_availability)
		 SELECT sq.player_id, ln.xpts::float8 AS xpts,
		        CASE WHEN av.fetched_at >= now() - interval '26 hours' THEN av.injured END AS injured,
		        CASE WHEN av.fetched_at >= now() - interval '26 hours' THEN av.suspended END AS suspended
		 FROM league_squad_daily sq
		 LEFT JOIN lineup_daily ln ON ln.team_id = sq.team_id AND ln.day = sq.day AND ln.player_id = sq.player_id
		 LEFT JOIN player_availability av ON av.player_id = sq.player_id AND av.day = (SELECT day FROM av_day)
		 WHERE sq.team_id = $1 AND sq.day = (SELECT day FROM s_day)`,
		[teamId]
	);
	return new Map(rows.map((r) => [r.player_id as string, r as {
		player_id: string; xpts: number | null; injured: boolean | null; suspended: boolean | null;
	}]));
}

// --- ¿Acierto? ----------------------------------------------------------------------------------
// Juzga las recomendaciones pasadas a los siete días, que es el horizonte con el que se tomaron.
// Lo calcula `analysis/calibration.py` y lo deja en `recommendation_log.outcome`; aquí solo se lee.

export type Verdict = {
	verdict: string;
	kind: string;
	n: number;
	con_beneficio: number;
	aciertos: number;
	beneficio: number;
	pujas: number;
	pujas_ok: number;
};

export type Judged = {
	player_id: string;
	name: string;
	kind: string;
	verdict: string;
	decided_at: string;
	bid: number | null;
	sold: boolean | null;
	paid: number | null;
	would_have_won: boolean | null;
	profit_if_taken: number | null;
	real_return: number | null;
	predicted_return: number | null;
};

export async function accuracy(): Promise<{
	pending: number;
	firstVerdictOn: string | null;
	verdicts: Verdict[];
	judged: Judged[];
}> {
	const [resumen] = (await q(
		`SELECT count(*)::int AS total,
		        count(*) FILTER (WHERE outcome IS NULL)::int AS pending,
		        (min(cycle_end) FILTER (WHERE outcome IS NULL) + interval '7 days')::date::text AS first_on
		 FROM recommendation_log`
	)) as { total: number; pending: number; first_on: string | null }[];

	const verdicts = await q(
		`SELECT verdict, kind, count(*)::int AS n,
		        count(*) FILTER (WHERE outcome->>'profit_if_taken' IS NOT NULL)::int AS con_beneficio,
		        count(*) FILTER (WHERE (outcome->>'profit_if_taken')::float8 > 0)::int AS aciertos,
		        COALESCE(sum((outcome->>'profit_if_taken')::float8), 0) AS beneficio,
		        count(*) FILTER (WHERE outcome->>'would_have_won' IS NOT NULL)::int AS pujas,
		        count(*) FILTER (WHERE (outcome->>'would_have_won')::boolean)::int AS pujas_ok
		 FROM recommendation_log WHERE outcome IS NOT NULL
		 GROUP BY verdict, kind ORDER BY n DESC`
	);

	const judged = await q(
		`SELECT l.player_id, COALESCE(p.nickname, p.name) AS name, l.kind, l.verdict,
		        ${ISO('l.cycle_end')} AS decided_at,
		        (l.subject->>'bid_to_win')::float8 AS bid,
		        (l.outcome->>'sold')::boolean AS sold,
		        (l.outcome->>'paid')::float8 AS paid,
		        (l.outcome->>'would_have_won')::boolean AS would_have_won,
		        (l.outcome->>'profit_if_taken')::float8 AS profit_if_taken,
		        (l.outcome->>'real_return')::float8 AS real_return,
		        (l.outcome->>'predicted_return')::float8 AS predicted_return
		 FROM recommendation_log l
		 LEFT JOIN players p ON p.player_id = l.player_id
		 WHERE l.outcome IS NOT NULL
		 ORDER BY l.cycle_end DESC, abs(COALESCE((l.outcome->>'profit_if_taken')::float8, 0)) DESC
		 LIMIT 20`
	);

	return {
		pending: resumen?.pending ?? 0,
		firstVerdictOn: resumen?.first_on ?? null,
		verdicts: verdicts as Verdict[],
		judged: judged as Judged[]
	};
}


// --- Apuestas del usuario -------------------------------------------------------------------------
// Jugadores que tienes por convicción propia. El recomendador no los manda vender por una racha de
// mercado (analysis/recommend.py, razón APUESTA). Es lo único que la web escribe en la base.

export type Thesis = { player_id: string; created_at: string; entry_value: number | null; note: string | null };

// Hasta que el job diario migre, la tabla no existe: leer no debe tumbar la pantalla.
export async function thesis(playerId: string): Promise<Thesis | null> {
	try {
		const rows = await q(
			`SELECT player_id, ${ISO('created_at')} AS created_at, entry_value::float8 AS entry_value, note
			   FROM player_thesis WHERE player_id = $1`,
			[playerId],
			{ noCache: true }
		);
		return (rows[0] as Thesis) ?? null;
	} catch {
		return null;
	}
}

export async function thesisIds(): Promise<Set<string>> {
	try {
		const rows = await q(`SELECT player_id FROM player_thesis`, [], { noCache: true });
		return new Set(rows.map((r) => r.player_id as string));
	} catch {
		return new Set();
	}
}

export async function setThesis(playerId: string, on: boolean, note: string | null): Promise<void> {
	if (on) {
		await q(
			`INSERT INTO player_thesis (player_id, entry_value, note)
			 SELECT $1, (SELECT market_value FROM player_value_daily WHERE player_id = $1 ORDER BY day DESC LIMIT 1), $2
			 ON CONFLICT (player_id) DO UPDATE SET note = EXCLUDED.note`,
			[playerId, note],
			{ noCache: true }
		);
	} else {
		await q(`DELETE FROM player_thesis WHERE player_id = $1`, [playerId], { noCache: true });
	}
	clearQueryCache();
}

// Lista de seguimiento (2026-09-27): jugadores que quieres a un precio. El job ligero comprueba cada
// pasada si se pueden fichar (mercado o cláusula abierta) y deja aquí su veredicto con los motivos;
// la web solo lo enseña y escribe tus condiciones, nunca decide ni toca LaLiga.

export type WatchDetail = {
	reasons: string[];
	hits: { kind: 'mercado' | 'clausula'; price: number; text: string; closes?: string | null }[];
	start_prob: number | null;
	value: number | null;
};

export type WatchRule = {
	max_price: number | null;
	min_start_prob: number | null;
	watch_market: boolean;
	watch_clause: boolean;
	note: string | null;
	value_at_add: number | null;
	created_at: string;
	state: 'cumple' | 'espera' | 'bloqueado' | 'tuyo' | null;
	detail: WatchDetail | null;
	checked_at: string | null;
};

export type WatchItem = PlayerCard & WatchRule;

const WATCH_COLS = `w.max_price::float8 AS max_price, w.min_start_prob::float8 AS min_start_prob,
	w.watch_market, w.watch_clause, w.note, w.value_at_add::float8 AS value_at_add,
	${ISO('w.created_at')} AS created_at, w.state, w.detail, ${ISO('w.checked_at')} AS checked_at`;

// Hasta que el job migre, la tabla no existe: leer no debe tumbar la pantalla.
export async function watchlist(): Promise<WatchItem[]> {
	try {
		const rows = await q(
			`${LATEST_DAY}
			SELECT ${PLAYER_CARD}, ${WATCH_COLS}
			${PLAYER_JOINS}
			JOIN watchlist w ON w.player_id = p.player_id
			ORDER BY (w.state = 'cumple') DESC NULLS LAST, w.created_at DESC`,
			[],
			{ noCache: true }
		);
		return rows as WatchItem[];
	} catch {
		return [];
	}
}

export async function watchRule(playerId: string): Promise<WatchRule | null> {
	try {
		const rows = await q(`SELECT ${WATCH_COLS} FROM watchlist w WHERE w.player_id = $1`, [playerId], { noCache: true });
		return (rows[0] as WatchRule) ?? null;
	} catch {
		return null;
	}
}

export async function setWatch(
	playerId: string,
	rule: { max_price: number | null; min_start_prob: number | null; watch_market: boolean; watch_clause: boolean; note: string | null } | null
): Promise<void> {
	if (rule) {
		// Al cambiar las condiciones se borra el veredicto: era de las anteriores.
		await q(
			`INSERT INTO watchlist (player_id, max_price, min_start_prob, watch_market, watch_clause, note, value_at_add)
			 SELECT $1, $2, $3, $4, $5, $6, (SELECT market_value FROM player_value_daily WHERE player_id = $1 ORDER BY day DESC LIMIT 1)
			 ON CONFLICT (player_id) DO UPDATE SET max_price = EXCLUDED.max_price, min_start_prob = EXCLUDED.min_start_prob,
			   watch_market = EXCLUDED.watch_market, watch_clause = EXCLUDED.watch_clause, note = EXCLUDED.note,
			   state = NULL, detail = NULL, checked_at = NULL`,
			[playerId, rule.max_price, rule.min_start_prob, rule.watch_market, rule.watch_clause, rule.note],
			{ noCache: true }
		);
	} else {
		await q(`DELETE FROM watchlist WHERE player_id = $1`, [playerId], { noCache: true });
	}
	clearQueryCache();
}

// Radar de rivales (analysis/rivals.py): qué le falta a cada uno, su saldo y cómo ficha.

export type RivalRadar = {
	team_id: string;
	manager_name: string;
	squad_size: number;
	available: Record<string, number>;
	can_field: boolean;
	missing: Record<string, number>;
	needs_text: string;
	cash: number | null;
	cash_uncertainty: number | null;
	signings_30d: number;
	clauses_30d: number;
	overpay_median: number | null;
	overpay_cases: number;
	could_bid: { player_id: string; name: string; position_id: number; price: number }[];
	computed_at: string;
};

export async function rivalRadar(): Promise<RivalRadar[]> {
	try {
		const rows = await q(
			`SELECT r.detail, ${ISO('r.computed_at')} AS computed_at
			   FROM rival_radar r
			  WHERE r.day = (SELECT max(day) FROM rival_radar)
			  ORDER BY (r.detail->>'can_field')::boolean, (r.detail->>'cash')::float8 DESC NULLS LAST`
		);
		return rows.map((r) => ({ ...(r.detail as RivalRadar), computed_at: r.computed_at as string }));
	} catch {
		return [];
	}
}

// Diario de decisiones (analysis/journal.py): lo que te dio de verdad cada fichaje y cada venta.

export type JournalEntry = {
	player_id: string;
	name: string | null;
	position_id: number | null;
	entry_at: string | null;
	entry_kind: 'mercado' | 'manager' | 'clausula' | 'inicial';
	paid: number | null;
	exit_at: string | null;
	exit_kind: 'venta_sistema' | 'venta_manager' | 'me_clausularon' | null;
	received: number | null;
	open: boolean;
	value_at_entry: number | null;
	value_now: number | null;
	pnl: number | null;
	return: number | null;
	baseline_return: number | null;
	vs_baseline: number | null;
	weeks: number;
	points: number;
	weeks_known_lineup: number;
	points_aligned: number | null;
	rec_at_entry: string | null;
	rec_at_exit: string | null;
	image_url: string | null;
	badge_url: string | null;
};

export async function journal(): Promise<{ entries: JournalEntry[]; computed_at: string | null }> {
	try {
		const rows = await q(
			`SELECT j.detail, p.image_url, t.badge_url, ${ISO('j.computed_at')} AS computed_at
			   FROM decision_journal j
			   LEFT JOIN players p ON p.player_id = j.player_id
			   LEFT JOIN teams t ON t.team_id = p.team_id
			  ORDER BY j.open DESC, COALESCE(j.detail->>'exit_at', j.detail->>'entry_at') DESC NULLS LAST`
		);
		return {
			entries: rows.map((r) => ({ ...(r.detail as JournalEntry), image_url: r.image_url as string | null, badge_url: r.badge_url as string | null })),
			computed_at: (rows[0]?.computed_at as string) ?? null
		};
	} catch {
		return { entries: [], computed_at: null };
	}
}
