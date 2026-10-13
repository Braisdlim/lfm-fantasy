"""Configuración por variables de entorno (ver .env.example)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Raíz del repo (src/lfm/config.py → ../../). Las rutas de .env y .tokens.json se anclan aquí
# para que los comandos funcionen igual desde cualquier carpeta.
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(default="", alias="DATABASE_URL")
    price_cache_dir: Path | None = Field(default=None, alias="PRICE_CACHE_DIR")

    laliga_email: str = Field(default="", alias="LALIGA_EMAIL")
    laliga_password: str = Field(default="", alias="LALIGA_PASSWORD")
    laliga_refresh_token: str = Field(default="", alias="LALIGA_REFRESH_TOKEN")

    league_id: str = Field(default="", alias="LEAGUE_ID")
    competition_id: str = Field(default="1", alias="COMPETITION_ID")
    market_reset_hour_utc: int | None = Field(default=None, alias="MARKET_RESET_HOUR_UTC")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    app_url: str = Field(default="", alias="APP_URL")

    # Archivo local de tokens (ignorado por git). En CI no existe: se usa el refresh token.
    tokens_file: Path = Field(default=REPO_ROOT / ".tokens.json")

    # Pausa mínima entre peticiones a la API de LaLiga (regla 3 de CLAUDE.md)
    request_pause_seconds: float = 1.5

    @field_validator("market_reset_hour_utc", mode="before")
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        # .env.example deja el valor vacío y "" no es un entero válido: no debe romper el arranque
        return None if v == "" else v


settings = Settings()
