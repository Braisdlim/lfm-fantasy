"""Tests unitarios para la persistencia y carga de tokens en Neon DB."""

import time
from unittest.mock import MagicMock, patch

from lfm.api import auth


def test_save_db_and_load_db_mocked():
    fake_tokens = auth.Tokens(
        access_token="acc-123",
        id_token="id-456",
        refresh_token="ref-789",
        expires_at=time.time() + 3600,
        client_id=auth.REFRESH_CLIENT_ID,
    )

    mock_row = {
        "access_token": fake_tokens.access_token,
        "id_token": fake_tokens.id_token,
        "refresh_token": fake_tokens.refresh_token,
        "expires_at": fake_tokens.expires_at,
        "client_id": fake_tokens.client_id,
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.mappings.return_value.first.return_value = mock_row

    mock_engine = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    with patch("lfm.db.session.engine", return_value=mock_engine):
        fake_tokens.save_db()
        assert mock_conn.execute.called

        loaded = auth.Tokens.load_db()
        assert loaded is not None
        assert loaded.access_token == "acc-123"
        assert loaded.id_token == "id-456"
        assert loaded.refresh_token == "ref-789"
        assert loaded.client_id == auth.REFRESH_CLIENT_ID
        assert not loaded.is_expired()


def test_load_db_returns_none_when_empty():
    mock_conn = MagicMock()
    mock_conn.execute.return_value.mappings.return_value.first.return_value = None

    mock_engine = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    with patch("lfm.db.session.engine", return_value=mock_engine):
        loaded = auth.Tokens.load_db()
        assert loaded is None


def test_get_tokens_falls_back_to_db_when_local_expired():
    fake_expired_local = auth.Tokens(
        access_token="old", id_token="old", refresh_token="old", expires_at=time.time() - 100
    )
    fake_valid_db = auth.Tokens(
        access_token="new", id_token="new", refresh_token="new", expires_at=time.time() + 1800
    )

    with patch.object(auth.Tokens, "load", return_value=fake_expired_local):
        with patch.object(auth.Tokens, "load_db", return_value=fake_valid_db):
            tokens = auth.get_tokens()
            assert tokens.access_token == "new"
            assert tokens.refresh_token == "new"
