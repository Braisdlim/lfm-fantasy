-- Esquema de lfm. Idempotente: solo CREATE ... IF NOT EXISTS.
-- Cambios: añadir al final, nunca editar sentencias antiguas (ver CLAUDE.md).

-- 0. Operativa -----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS job_runs (
    id          BIGSERIAL PRIMARY KEY,
    job         TEXT NOT NULL,                  -- 'daily', 'matchday', 'backfill'
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status      TEXT NOT NULL DEFAULT 'running',-- running | ok | error
    summary     JSONB,
    error       TEXT
);

-- 1. Crudo: todo lo que llega, tal cual ---------------------------------------------------

CREATE TABLE IF NOT EXISTS raw_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,                  -- 'laliga_api' | 'futbolfantasy' | 'analiticafantasy' | ...
    endpoint    TEXT NOT NULL,                  -- ruta o URL
    params      JSONB,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload     JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS raw_snapshots_src_ep_time ON raw_snapshots (source, endpoint, fetched_at DESC);

-- 2. Maestros -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS teams (
    team_id     TEXT PRIMARY KEY,               -- id de club real en la API
    name        TEXT NOT NULL,
    slug        TEXT,                           -- slug en futbolfantasy.com
    badge_url   TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS players (
    player_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    nickname    TEXT,
    team_id     TEXT REFERENCES teams(team_id),
    position_id INT,
    image_url   TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Series temporales --------------------------------------------------------------------

-- LA TABLA MÁS IMPORTANTE: una fila por jugador y día.
CREATE TABLE IF NOT EXISTS player_value_daily (
    player_id    TEXT NOT NULL REFERENCES players(player_id),
    day          DATE NOT NULL,
    market_value BIGINT NOT NULL,
    status       TEXT,                          -- ok | injured | doubtful | suspended | ...
    points_total INT,
    source       TEXT NOT NULL DEFAULT 'laliga_api', -- 'laliga_api' | 'futbolfantasy_backfill'
    PRIMARY KEY (player_id, day)
);

CREATE TABLE IF NOT EXISTS player_week_stats (
    player_id    TEXT NOT NULL REFERENCES players(player_id),
    week         INT NOT NULL,
    total_points INT,
    stats        JSONB,                         -- desglose {stat: [valor, puntos]}
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, week)
);

-- 4. Mi liga ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS league_teams (
    league_id    TEXT NOT NULL,
    team_id      TEXT NOT NULL,                 -- id del equipo fantasy (manager)
    manager_id   TEXT,
    manager_name TEXT,
    team_name    TEXT,
    is_me        BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (league_id, team_id)
);

CREATE TABLE IF NOT EXISTS league_standing_daily (
    league_id   TEXT NOT NULL,
    team_id     TEXT NOT NULL,
    day         DATE NOT NULL,
    position    INT,
    points      INT,
    team_value  BIGINT,
    PRIMARY KEY (league_id, team_id, day)
);

CREATE TABLE IF NOT EXISTS league_standing_week (
    league_id   TEXT NOT NULL,
    team_id     TEXT NOT NULL,
    week        INT NOT NULL,
    points      INT,                            -- VERIFY: puntos DE la jornada, no acumulados
    PRIMARY KEY (league_id, team_id, week)
);

-- Plantilla de cada equipo de la liga, cada día (de aquí salen cláusulas y su evolución)
CREATE TABLE IF NOT EXISTS league_squad_daily (
    league_id        TEXT NOT NULL,
    team_id          TEXT NOT NULL,
    player_id        TEXT NOT NULL REFERENCES players(player_id),
    day              DATE NOT NULL,
    buyout_clause    BIGINT,
    clause_locked_until TIMESTAMPTZ,
    buy_price        BIGINT,
    PRIMARY KEY (league_id, team_id, player_id, day)
);

-- Feed de actividad completo, deduplicado por id de actividad
CREATE TABLE IF NOT EXISTS league_activity (
    league_id     TEXT NOT NULL,
    activity_id   TEXT NOT NULL,
    activity_type INT NOT NULL,                 -- ver ACTIVITY_TYPES en endpoints.py
    manager_id    TEXT,
    team_id       TEXT,
    player_id     TEXT,
    amount        BIGINT,
    happened_at   TIMESTAMPTZ,
    raw           JSONB NOT NULL,
    PRIMARY KEY (league_id, activity_id)
);

-- Saldo estimado por rival (se recalcula desde league_activity)
CREATE TABLE IF NOT EXISTS manager_cash_estimate (
    league_id     TEXT NOT NULL,
    team_id       TEXT NOT NULL,
    day           DATE NOT NULL,
    cash_estimate BIGINT NOT NULL,
    uncertainty   BIGINT NOT NULL DEFAULT 0,
    method        TEXT,
    PRIMARY KEY (league_id, team_id, day)
);

CREATE TABLE IF NOT EXISTS market_daily (
    league_id     TEXT NOT NULL,
    day           DATE NOT NULL,
    market_id     TEXT NOT NULL,
    player_id     TEXT NOT NULL,
    sale_price    BIGINT,
    owner_team_id TEXT,                         -- NULL si es del sistema
    expires_at    TIMESTAMPTZ,
    raw           JSONB NOT NULL,
    PRIMARY KEY (league_id, day, market_id)
);

-- 5. Fuentes externas y entrada manual ----------------------------------------------------

CREATE TABLE IF NOT EXISTS external_predictions (
    source      TEXT NOT NULL,                  -- 'analiticafantasy' | 'futbolfantasy' | ...
    player_id   TEXT NOT NULL,
    week        INT NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    xpts        NUMERIC(6,2),
    p_start     NUMERIC(4,3),
    extra       JSONB,
    PRIMARY KEY (source, player_id, week, fetched_at)
);

CREATE TABLE IF NOT EXISTS manual_tiers (
    player_id   TEXT NOT NULL REFERENCES players(player_id),
    source      TEXT NOT NULL,                  -- 'jose_carrasco' | ...
    tier        TEXT NOT NULL,                  -- 'S' | 'A' | 'B' | ...
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, source)
);

-- Mapeo de nombres externos → player_id (los scrapers no traen ids de LaLiga)
CREATE TABLE IF NOT EXISTS player_aliases (
    source      TEXT NOT NULL,
    external_key TEXT NOT NULL,                 -- p. ej. 'nombre|posicion|equipo' normalizado
    player_id   TEXT NOT NULL REFERENCES players(player_id),
    confidence  NUMERIC(4,3) NOT NULL DEFAULT 1,
    PRIMARY KEY (source, external_key)
);

-- 6. Salida: recomendaciones y alertas ----------------------------------------------------

CREATE TABLE IF NOT EXISTS recommendations (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT NOT NULL,                  -- sell | buy | raise_clause | shield | lineup | ...
    subject     JSONB NOT NULL,                 -- {player_id, team_id, ...}
    score       NUMERIC(8,3),
    reasons     JSONB NOT NULL,                 -- [{code, text, value, source}]
    acted_at    TIMESTAMPTZ,
    outcome     JSONB
);

CREATE TABLE IF NOT EXISTS alerts (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT NOT NULL,
    dedupe_key  TEXT NOT NULL UNIQUE,           -- evita repetir la misma alerta
    payload     JSONB NOT NULL,
    sent_at     TIMESTAMPTZ
);

-- 2026-09-08: /players real trae averagePoints (media de puntos por jornada) ------------------

ALTER TABLE player_value_daily ADD COLUMN IF NOT EXISTS average_points NUMERIC(6,2);

-- 2026-09-08: corte 2 (standing, plantillas, activity, market) con la forma real de la API -----

ALTER TABLE league_standing_daily ADD COLUMN IF NOT EXISTS previous_position INT;
ALTER TABLE league_standing_daily ADD COLUMN IF NOT EXISTS team_money BIGINT;      -- solo mi equipo
ALTER TABLE league_squad_daily ADD COLUMN IF NOT EXISTS is_shielded BOOLEAN;
ALTER TABLE league_squad_daily ADD COLUMN IF NOT EXISTS market_value BIGINT;
ALTER TABLE league_activity ADD COLUMN IF NOT EXISTS manager2_id TEXT;             -- vendedor en tipo 1
ALTER TABLE league_activity ADD COLUMN IF NOT EXISTS week INT;                     -- tipo 6
ALTER TABLE market_daily ADD COLUMN IF NOT EXISTS kind TEXT;                       -- marketPlayerLeague | marketPlayerTeam
ALTER TABLE market_daily ADD COLUMN IF NOT EXISTS num_bids INT;
ALTER TABLE market_daily ADD COLUMN IF NOT EXISTS num_offers INT;
ALTER TABLE market_daily ADD COLUMN IF NOT EXISTS buyout_clause BIGINT;

-- 2026-09-08: calendario (week/current + calendar) para cuentas atrás y próximo rival --------

CREATE TABLE IF NOT EXISTS weeks (
    week        INT PRIMARY KEY,
    opening_at  TIMESTAMPTZ,                   -- primer partido: bloqueo del once
    closing_at  TIMESTAMPTZ,
    is_live     BOOLEAN,
    next_week   INT,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS matches (
    match_id        TEXT PRIMARY KEY,
    week            INT NOT NULL,
    match_date      TIMESTAMPTZ,
    local_team_id   TEXT,
    visitor_team_id TEXT,
    state           INT,
    local_score     INT,
    visitor_score   INT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS matches_week ON matches (week);

-- 2026-09-08: búsqueda sin tildes desde la web

CREATE EXTENSION IF NOT EXISTS unaccent;

-- 2026-09-08: ciclo de mercado. El mercado NO rota a medianoche sino a la hora de la liga
-- (19:21 en 90000001), así que dos capturas del mismo día natural pueden pertenecer a ciclos
-- distintos. La unidad correcta es (liga, cierre del ciclo, jugador): un jugador aparece una vez
-- por ciclo y la última lectura sustituye a la anterior. Ver docs/plan-app.md §A1.

CREATE TABLE IF NOT EXISTS market_offer (
    league_id     TEXT NOT NULL,
    cycle_end     TIMESTAMPTZ NOT NULL,   -- cuando cierra el mercado de la liga en ese ciclo
    player_id     TEXT NOT NULL,
    market_id     TEXT NOT NULL,
    kind          TEXT NOT NULL,          -- marketPlayerLeague (la liga) | marketPlayerTeam (un manager)
    sale_price    BIGINT,
    owner_team_id TEXT,                   -- NULL si lo vende la liga
    expires_at    TIMESTAMPTZ,           -- plazo propio de esta oferta (los de manager duran mas)
    num_bids      INT,
    num_offers    INT,
    offer_money   BIGINT,                 -- oferta directa recibida (solo en mis ventas)
    buyout_clause BIGINT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw           JSONB NOT NULL,
    PRIMARY KEY (league_id, cycle_end, player_id)
);
CREATE INDEX IF NOT EXISTS market_offer_expires ON market_offer (league_id, expires_at DESC);
CREATE INDEX IF NOT EXISTS market_offer_player ON market_offer (player_id, cycle_end DESC);
CREATE INDEX IF NOT EXISTS league_squad_daily_day ON league_squad_daily (day DESC);
CREATE INDEX IF NOT EXISTS player_value_daily_day ON player_value_daily (day DESC);

-- 2026-09-08: cadencia. Saber cuándo se leyó cada cosa, para mostrar la antigüedad por pantalla
-- en vez de una fecha global (docs/plan-app.md §D).

ALTER TABLE league_squad_daily ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE league_standing_daily ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- 2026-09-08: el score de una recomendación es un beneficio en euros, no cabe en NUMERIC(8,3)
ALTER TABLE recommendations ALTER COLUMN score TYPE NUMERIC(14,2);

-- 2026-09-08: disponibilidad y probabilidad de ser titular (FútbolFantasy). Es el factor que
-- más pesa en los puntos esperados y la API oficial no lo da.

CREATE TABLE IF NOT EXISTS player_availability (
    player_id    TEXT NOT NULL REFERENCES players(player_id),
    day          DATE NOT NULL,
    start_prob   NUMERIC(4,3),          -- 0..1, probabilidad de ser titular
    injured      BOOLEAN,
    suspended    BOOLEAN,
    booking_risk BOOLEAN,               -- apercibido: a una amarilla de sancion
    minutes      INT,                   -- minutos de la temporada
    games        INT,
    source       TEXT NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, day)
);
CREATE INDEX IF NOT EXISTS player_availability_day ON player_availability (day DESC);

-- Histórico de recomendaciones, para poder comprobar después si acertaban (docs/criterio.md §7.11).
-- `recommendations` guarda solo la foto vigente porque es lo que pinta la web; aquí se conserva una
-- fila por **ciclo de mercado** y jugador. Dentro de un ciclo las pasadas horarias actualizan la
-- misma fila (la última antes del cierre es la que decidió), y al rotar el ciclo queda congelada.
CREATE TABLE IF NOT EXISTS recommendation_log (
    cycle_end     TIMESTAMPTZ NOT NULL,   -- identifica el ciclo: el mercado rota a la hora de la liga
    kind          TEXT NOT NULL,          -- buy | sell
    player_id     TEXT NOT NULL,
    verdict       TEXT NOT NULL,          -- pujar | no_pujar | sin_saldo | vender | aguantar | sin_datos
    score         NUMERIC(14,2),
    subject       JSONB NOT NULL,         -- las cifras con las que se decidió
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome       JSONB,                  -- se rellena después: qué pasó de verdad
    PRIMARY KEY (cycle_end, kind, player_id)
);
CREATE INDEX IF NOT EXISTS recommendation_log_cycle ON recommendation_log (cycle_end DESC);
CREATE INDEX IF NOT EXISTS recommendation_log_pending ON recommendation_log (cycle_end) WHERE outcome IS NULL;

-- Balón parado: quién lanza los penaltis, córners y faltas de cada equipo.
-- Viene en las mismas 20 páginas de FútbolFantasy que ya descargamos, codificado como
-- `(aciertos + 1) * 1000 + intentos` en `data-bpp` / `data-bpc` / `data-bpfd` / `data-bpfc`.
-- Verificado el 2026-09-09 contra `/analytics/{equipo}/balon-parado`, que publica esas mismas
-- cifras en texto: Unai López 6/16 córners = 7016, Budimir 3/3 penaltis = 4003.
-- Son acumulados de temporada, así que la fila de cada día sustituye a la anterior.
CREATE TABLE IF NOT EXISTS player_set_pieces (
    player_id        TEXT NOT NULL REFERENCES players(player_id),
    day              DATE NOT NULL,
    pen_scored       INT,   -- penaltis marcados
    pen_taken        INT,   -- penaltis lanzados
    corner_accurate  INT,   -- córners precisos (solo los colgados; los cortos no cuentan aquí)
    corner_taken     INT,
    fk_on_target     INT,   -- faltas directas que van a puerta
    fk_taken         INT,
    cross_accurate   INT,   -- faltas colgadas al área que encuentran rematador
    cross_taken      INT,
    source           TEXT NOT NULL,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, day)
);
CREATE INDEX IF NOT EXISTS player_set_pieces_day ON player_set_pieces (day DESC);

-- Total de balón parado de cada equipo, que es el denominador de "lanza el 80 % de los córners".
-- Se guarda aparte porque sumar a los jugadores casados se queda corto: el 2026-09-09 la Real
-- Sociedad daba 18 córners en vez de 24 porque a Carlos Soler no lo habíamos casado, y eso
-- inflaba el porcentaje de todos sus compañeros. Aquí se suma la página entera, casada o no.
CREATE TABLE IF NOT EXISTS team_set_pieces (
    team_id       TEXT NOT NULL REFERENCES teams(team_id),
    day           DATE NOT NULL,
    pen_taken     INT,
    corner_taken  INT,
    fk_taken      INT,
    cross_taken   INT,
    source        TEXT NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, day)
);

-- Pronóstico de cada partido por jugar, para que la web no tenga que reimplementar el modelo.
-- Lo escribe el job diario desde `analysis/fixtures.py`: Poisson con fuerza de ataque y defensa
-- encogida hacia la media de la liga. Se recalcula entero cada día, así que una fila vieja de un
-- partido ya jugado no estorba: se borra al reescribir.
CREATE TABLE IF NOT EXISTS match_forecast (
    match_id     TEXT PRIMARY KEY REFERENCES matches(match_id),
    week         INT NOT NULL,
    xg_local     NUMERIC(5,3),   -- goles esperados del local
    xg_visitor   NUMERIC(5,3),
    p_local      NUMERIC(4,3),   -- probabilidad de que gane el local
    p_draw       NUMERIC(4,3),
    p_visitor    NUMERIC(4,3),
    cs_local     NUMERIC(4,3),   -- probabilidad de que el local deje la portería a cero
    cs_visitor   NUMERIC(4,3),
    played       INT,            -- partidos con los que se ha estimado; con pocos, poca confianza
    computed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS match_forecast_week ON match_forecast (week);

-- Rendimiento de cada jugador frente a lo que cuesta, calculado por `analysis/bargains.py`.
-- Se guarda para que la web solo lea tablas: la comparación es contra los vecinos de precio de su
-- misma posición y no se puede escribir en una consulta legible.
CREATE TABLE IF NOT EXISTS player_bargain (
    player_id   TEXT NOT NULL REFERENCES players(player_id),
    day         DATE NOT NULL,
    points      INT,             -- los que lleva
    expected    NUMERIC(6,2),    -- la mediana de los que cuestan como él en su posición
    surplus     NUMERIC(6,2),    -- puntos de más (o de menos)
    peers       INT,             -- con cuántos se ha comparado
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, day)
);
CREATE INDEX IF NOT EXISTS player_bargain_day ON player_bargain (day DESC);

-- El once que conviene poner, calculado por `analysis/eleven.py`, y el que tienes puesto de verdad.
-- `chosen` distingue a los titulares del once propuesto; `current` dice si ese jugador está hoy
-- alineado en el juego. Con las dos cosas la pantalla puede decir "cambia a este por este" en vez
-- de limitarse a enseñar una lista.
CREATE TABLE IF NOT EXISTS lineup_daily (
    team_id     TEXT NOT NULL,
    day         DATE NOT NULL,
    player_id   TEXT NOT NULL REFERENCES players(player_id),
    chosen      BOOLEAN NOT NULL,          -- entra en el once propuesto
    current     BOOLEAN NOT NULL,          -- lo tienes alineado ahora mismo en el juego
    xpts        NUMERIC(6,2),
    formation   TEXT,                      -- el dibujo propuesto, "3-4-3"
    feasible    INT,                       -- cuántas formaciones cabían con esta plantilla
    forced      BOOLEAN,                   -- si no había ninguna elección que tomar
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, day, player_id)
);

-- Componentes de la temporada de cada jugador: goles, asistencias, tarjetas y reparto de titularidad.
-- Sale de las **mismas 20 páginas de FútbolFantasy** que ya descargábamos para la titularidad, así
-- que no cuesta ni una petición más. Usábamos 5 atributos de los ~25 que trae cada jugador.
--
-- Importa porque la media de puntos pasados es un estimador ruidoso: medido el 2026-09-16 sobre el
-- desglose oficial de `player_week_stats.stats`, el gol explica el 5,6 % de los puntos de un
-- defensa y el 7,6 % de los de un medio, pero aporta la mayor desviación típica de todas las
-- partidas. Predecir desde los componentes permite estimar aparte lo estable (minutos, nota DAZN,
-- acciones técnicas: ~70 % del total) y lo ruidoso (goles), en vez de mezclarlo en una sola media.
--
-- Son acumulados de temporada, así que la fila de cada día sustituye a la anterior y la serie
-- diaria permite reconstruir después lo que pasó en cada jornada por diferencia.
CREATE TABLE IF NOT EXISTS player_season_stats (
    player_id       TEXT NOT NULL REFERENCES players(player_id),
    day             DATE NOT NULL,
    goals           INT,   -- data-totalGoles
    assists         INT,   -- data-totalAsistencias
    yellows         INT,   -- data-totalAmarillas
    reds            INT,   -- data-totalRojas
    games           INT,   -- data-totalPartidosJugados
    games_as_sub    INT,   -- data-totalPartidosJugadosSuplente: entró desde el banquillo
    games_subbed_off INT,  -- data-totalPartidosSustituido: salió antes del final
    minutes         INT,   -- data-totalMinutosJugados
    hierarchy       INT,   -- data-jerarquia, 0-100: peso del jugador en su equipo según la fuente
    form            NUMERIC(4,1),  -- data-forma_value
    source          TEXT NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, day)
);
CREATE INDEX IF NOT EXISTS player_season_stats_day ON player_season_stats (day DESC);

-- Tokens de autenticación contra la API de LaLiga (Azure AD B2C).
-- En GitHub Actions el sistema de archivos es efímero y los secretos son estáticos. Guardar los
-- tokens aquí permite que el refresh token rote tras cada pasada y se mantenga vivo indefinidamente
-- en Neon sin requerir que el usuario vuelva a iniciar sesión cada 90 días.
CREATE TABLE IF NOT EXISTS auth_tokens (
    service         TEXT PRIMARY KEY,              -- 'laliga_b2c'
    access_token    TEXT,
    id_token        TEXT,
    refresh_token   TEXT NOT NULL,
    expires_at      DOUBLE PRECISION NOT NULL,     -- epoch seconds
    client_id       TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Apuestas del usuario (2026-09-20): jugadores que tiene por convicción propia (p. ej. «va a ser
-- titular del Madrid») y que el recomendador no debe mandar vender por una racha de mercado. La
-- decisión es tuya (capa «decisión» de docs/criterio.md); la app solo lleva la cuenta de cómo va.
CREATE TABLE IF NOT EXISTS player_thesis (
    player_id    TEXT PRIMARY KEY REFERENCES players(player_id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    entry_value  BIGINT,          -- valor el día que la marcaste, para ver si va saliendo
    note         TEXT
);

-- Señales de rebote medidas (2026-09-20, analysis/rebound.py). Una fila por señal con su última
-- medición: el recomendador solo usa las que tienen `passes`.
CREATE TABLE IF NOT EXISTS signal_check (
    signal        TEXT PRIMARY KEY,
    measured_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    n             INT NOT NULL,
    mean_7d       NUMERIC(8,4),     -- cambio medio a 7 días de los que bajaban y tenían la señal
    up_rate       NUMERIC(5,3),
    control_mean  NUMERIC(8,4),     -- el de los que bajaban sin ella
    passes        BOOLEAN NOT NULL,
    detail        JSONB
);

-- Cambio diario guardado al escribir, no calculado al leer (2026-09-20).
-- Hasta ahora cada pantalla restaba el valor de «ayer» por su cuenta: la ficha lo hacía contra el
-- último dato que hubiera aunque faltaran días, y mezclando la serie de FútbolFantasy con la de la
-- API. `change` solo existe si el día anterior es de la **misma fuente**; si falta, es NULL y la app
-- dice «sin dato de ayer». Nunca se interpola ni se deduce de otra tabla.
ALTER TABLE player_value_daily ADD COLUMN IF NOT EXISTS change BIGINT;
ALTER TABLE player_value_daily ADD COLUMN IF NOT EXISTS captured_at TIMESTAMPTZ;
-- Un cero no es un valor, es un dato que falta (el backfill dejó miles): fuera.
DELETE FROM player_value_daily WHERE market_value <= 0;
UPDATE player_value_daily v SET change = v.market_value - p.market_value
  FROM player_value_daily p
 WHERE v.change IS NULL AND p.player_id = v.player_id AND p.day = v.day - 1 AND p.source = v.source;

-- Lista de seguimiento (2026-09-27): jugadores que te interesan y a qué precio los quieres. El job
-- ligero comprueba cada pasada si alguno está en el mercado o con la cláusula abierta por debajo de
-- tu máximo (y con la titularidad que pediste) y avisa por Telegram una sola vez por ocasión. Solo
-- lee: nunca puja ni clausula. La web escribe aquí igual que en `player_thesis`.
CREATE TABLE IF NOT EXISTS watchlist (
    player_id      TEXT PRIMARY KEY REFERENCES players(player_id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    max_price      BIGINT,          -- lo máximo que pagarías (mercado o cláusula); NULL = sin límite
    min_start_prob NUMERIC(4,3),    -- titularidad estimada mínima; NULL = no importa
    watch_market   BOOLEAN NOT NULL DEFAULT true,
    watch_clause   BOOLEAN NOT NULL DEFAULT true,
    note           TEXT,
    value_at_add   BIGINT,          -- valor el día que lo añadiste
    state          TEXT,            -- cumple | espera | bloqueado | tuyo (lo escribe el job)
    detail         JSONB,           -- por qué: cifras y motivos de la última comprobación
    checked_at     TIMESTAMPTZ
);

-- Radar de rivales (2026-09-27, analysis/rivals.py): por rival, qué le falta para alinear, su
-- saldo estimado, cómo ficha y qué jugadores del mercado podría disputarte. Una fila por rival y
-- día; la pasada más reciente del día sustituye a la anterior.
CREATE TABLE IF NOT EXISTS rival_radar (
    league_id   TEXT NOT NULL,
    team_id     TEXT NOT NULL,
    day         DATE NOT NULL,
    detail      JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (league_id, team_id, day)
);

-- Diario de decisiones (2026-09-27, analysis/journal.py): cada jugador que entró en tu plantilla,
-- lo que pagaste, lo que recuperaste o vale hoy, sus puntos mientras fue tuyo y la comparación con
-- su posición en el mismo periodo. Derivado: se reconstruye entero en cada pasada del diario.
CREATE TABLE IF NOT EXISTS decision_journal (
    league_id   TEXT NOT NULL,
    player_id   TEXT NOT NULL,
    entry_at    TIMESTAMPTZ NOT NULL,   -- 2000-01-01 si venía en la plantilla inicial
    open        BOOLEAN NOT NULL,       -- sigue en tu plantilla
    detail      JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (league_id, player_id, entry_at)
);

-- 2026-09-28: saldo propio más reciente. El job ligero recibe teamMoney cada hora aunque todavía
-- no exista la fila de clasificación del día; guardarlo en league_teams evita perderlo y conserva
-- intacto el histórico de league_standing_daily.
ALTER TABLE league_teams ADD COLUMN IF NOT EXISTS team_money BIGINT;
ALTER TABLE league_teams ADD COLUMN IF NOT EXISTS money_fetched_at TIMESTAMPTZ;

-- 2026-09-28: gasto mínimo identificado en subidas manuales entre capturas de plantilla.
ALTER TABLE manager_cash_estimate ADD COLUMN IF NOT EXISTS clause_spend_observed BIGINT NOT NULL DEFAULT 0;

-- 2026-10-09: HTML íntegro en gzip binario. Las capturas conservan su fecha y
-- referencia SHA-256; no multiplicar el mismo contenido ni la expansión base64.
CREATE TABLE IF NOT EXISTS raw_html_blobs (
    sha256 TEXT PRIMARY KEY CHECK (length(sha256) = 64),
    body BYTEA NOT NULL
);

-- 2026-10-09: modelos derivados de precios. Una fila por modelo; el corte, la
-- huella completa de los datos y el código invalidan la copia automáticamente.
CREATE TABLE IF NOT EXISTS analysis_cache (
    name TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    body BYTEA NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64)
);
