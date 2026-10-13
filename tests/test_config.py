from lfm.config import Settings


def test_blank_market_reset_hour_is_none():
    # .env.example deja MARKET_RESET_HOUR_UTC= vacío: copiarlo tal cual no debe romper el arranque
    assert Settings(_env_file=None, MARKET_RESET_HOUR_UTC="").market_reset_hour_utc is None
    assert Settings(_env_file=None, MARKET_RESET_HOUR_UTC="7").market_reset_hour_utc == 7
