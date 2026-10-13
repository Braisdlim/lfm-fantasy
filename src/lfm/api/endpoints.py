"""Mapa de endpoints de la API no documentada de LaLiga Fantasy (temporada 26/27).

Fuente: código de Externoak/LaLigaApp v3.5.0 (julio 2026), src/services/api.js.
Todo lo marcado VERIFY está pendiente de confirmar con tráfico real (docs/setup.md §6).

Convención: funciones que devuelven la ruta relativa a BASE_URL. Las de lectura van en
READ; las de escritura en WRITE y NUNCA se llaman desde jobs automáticos (CLAUDE.md regla 1).
"""

from __future__ import annotations

BASE_URL = "https://fantasy-api.llt-services.com/api"
ASSETS_URL = "https://assets-fantasy.llt-services.com"
STATS_BASE_URL = "https://fantasy-api.llt-services.com/stats"  # VERIFY: LaLigaApp lo enruta vía proxy /stats

# Cabeceras que envía LaLigaApp. VERIFY: comparar con las de la app móvil (User-Agent, x-app-version...).
DEFAULT_HEADERS = {"x-lang": "es", "Accept": "application/json"}


def _cmp(competition_id: str) -> str:
    return f"/v1/competition/{competition_id}"


class READ:
    """Endpoints de solo lectura."""

    @staticmethod
    def me() -> str:
        return "/v4/user/me"

    @staticmethod
    def leagues(cmp: str) -> str:
        return f"{_cmp(cmp)}/leagues"

    @staticmethod
    def standing(cmp: str, league_id: str, week: int | None = None) -> str:
        base = f"{_cmp(cmp)}/leagues/{league_id}/standing"
        # VERIFY: en standing/{week}, ¿`points` es de la jornada o acumulado?
        return f"{base}/{week}" if week is not None else base

    @staticmethod
    def activity(cmp: str, league_id: str, index: int = 0) -> str:
        # Feed paginado. Tipos: 1 compró, 4 blindó, 6 ganancia jornada, 7 alineación
        # incorrecta, 9 nuevo miembro, 31 fichó, 32 clausuló, 33 vendió.
        return f"{_cmp(cmp)}/leagues/{league_id}/activity/{index}"

    @staticmethod
    def team(cmp: str, league_id: str, team_id: str) -> str:
        # Plantilla de cualquier equipo de la liga: buyoutClause, buyoutClauseLockedEndTime
        return f"{_cmp(cmp)}/leagues/{league_id}/teams/{team_id}"

    @staticmethod
    def lineup(cmp: str, team_id: str) -> str:
        return f"{_cmp(cmp)}/teams/{team_id}/lineup"

    @staticmethod
    def lineup_week(cmp: str, team_id: str, week: int) -> str:
        # VERIFY: ¿devuelve onces pasados de equipos rivales?
        return f"{_cmp(cmp)}/teams/{team_id}/lineup/week/{week}"

    @staticmethod
    def money(cmp: str, team_id: str) -> str:
        # VERIFY: ¿funciona con teamId ajeno? Probablemente solo el propio.
        return f"{_cmp(cmp)}/teams/{team_id}/money"

    @staticmethod
    def market(cmp: str, league_id: str) -> str:
        return f"{_cmp(cmp)}/league/{league_id}/market"

    @staticmethod
    def players(cmp: str) -> str:
        # Todos los jugadores: marketValue, positionId, status, points, images
        return f"{_cmp(cmp)}/players"

    @staticmethod
    def player_detail(cmp: str, player_id: str, league_id: str) -> str:
        # playerMaster.playerStats[] por jornada con desglose; marketPlayer si en venta
        return f"{_cmp(cmp)}/player/{player_id}/league/{league_id}"

    @staticmethod
    def player_market_value_history(cmp: str, player_id: str) -> str:
        # Confirmado el 2026-10-09: público, lista diaria de {lfpId,marketValue,date,bids}.
        return f"{_cmp(cmp)}/player/{player_id}/market-value"

    @staticmethod
    def calendar(cmp: str, week: int) -> str:
        return f"{_cmp(cmp)}/calendar?weekNumber={week}"

    @staticmethod
    def current_week(cmp: str) -> str:
        return f"{_cmp(cmp)}/week/current"

    @staticmethod
    def teams_master() -> str:
        return "/v3/teams-master"

    @staticmethod
    def formations(option: str = "free") -> str:
        return f"/v4/teams/lineup/formations?option={option}"

    @staticmethod
    def premium_configuration() -> str:
        return "/v4/leagues/premium-configuration"

    @staticmethod
    def week_stats(cmp: str, week: int) -> str:
        # Se sirve bajo STATS_BASE_URL, no bajo BASE_URL
        return f"/v1/competition/{cmp}/stats/week/{week}"


class WRITE:
    """Operaciones sobre el juego. Solo desde la PWA con confirmación explícita."""

    @staticmethod
    def bid(cmp: str, league_id: str, market_id: str) -> str:
        return f"{_cmp(cmp)}/league/{league_id}/market/{market_id}/bid"  # POST {"money": N}

    @staticmethod
    def modify_bid(cmp: str, league_id: str, market_id: str, bid_id: str) -> str:
        return f"{_cmp(cmp)}/league/{league_id}/market/{market_id}/bid/{bid_id}"  # PUT

    @staticmethod
    def cancel_bid(cmp: str, league_id: str, market_id: str, bid_id: str) -> str:
        return f"{_cmp(cmp)}/league/{league_id}/market/{market_id}/bid/{bid_id}/cancel"  # DELETE

    @staticmethod
    def sell(cmp: str, league_id: str) -> str:
        return f"{_cmp(cmp)}/league/{league_id}/market/sell"  # POST {"playerId","salePrice"}

    @staticmethod
    def withdraw(cmp: str, league_id: str, market_id: str) -> str:
        return f"{_cmp(cmp)}/league/{league_id}/market/{market_id}/delete"  # DELETE

    @staticmethod
    def direct_offer(cmp: str, league_id: str) -> str:
        return f"{_cmp(cmp)}/league/{league_id}/market/direct-offer"  # POST {"playerId","money"}

    @staticmethod
    def accept_offer(cmp: str, league_id: str, market_id: str, offer_id: str) -> str:
        # POST {"offerMoney": N} — obligatorio, sin body devuelve 400
        return f"{_cmp(cmp)}/league/{league_id}/market/{market_id}/offer/{offer_id}/accept"

    @staticmethod
    def reject_offer(cmp: str, league_id: str, market_id: str, offer_id: str) -> str:
        # POST sin body y SIN Content-Type
        return f"{_cmp(cmp)}/league/{league_id}/market/{market_id}/offer/{offer_id}/reject"

    @staticmethod
    def update_lineup(cmp: str, team_id: str) -> str:
        return f"{_cmp(cmp)}/teams/{team_id}/lineup"  # PUT

    @staticmethod
    def raise_clause(cmp: str, league_id: str) -> str:
        return f"{_cmp(cmp)}/league/{league_id}/buyout/player"  # PUT {factor, playerId, valueToIncrease}

    @staticmethod
    def pay_clause(cmp: str, league_id: str, player_id: str) -> str:
        return f"{_cmp(cmp)}/league/{league_id}/buyout/{player_id}/pay"  # POST {buyoutClauseToPay}

    @staticmethod
    def shield(cmp: str, league_id: str) -> str:
        return f"{_cmp(cmp)}/league/{league_id}/shield/player"  # PUT {playerId, rewardedAdType, rewardedAd}


# Tipos de actividad del feed (activityTypeId)
ACTIVITY_TYPES = {
    1: "bought",  # compró (mercado)
    4: "shielded",  # blindó
    6: "week_income",  # ganancia por jornada
    7: "invalid_lineup",  # alineación incorrecta
    9: "new_member",
    31: "signed",  # fichó
    32: "clause_paid",  # clausuló
    33: "sold",  # vendió
}

POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD", 5: "COACH"}  # confirmado 2026-09-08 con /players real
