"""Fixtures de test a partir de respuestas reales de la API, anonimizadas.

CLAUDE.md pide tests sobre JSON real capturado de la API y anonimizado. Este módulo:

- `Anonymizer.anonymize(payload)`: recorre el JSON y sustituye nombres de personas y URLs por
  valores sintéticos deterministas. Conserva estructura, tipos, ids, valores de mercado, puntos y
  nombres de clubes (entidades públicas, no personas).
- `sample_players(payload, n)`: reduce la lista de jugadores a una muestra que cubre todas las
  combinaciones posición×estado observadas, para que el fixture quepa en el repo y sea legible.
- `write_fixture(path, payload, meta)`: escribe el JSON con metadatos de la captura.

Se usa desde `python -m lfm.jobs.daily --dry-run --save-fixture`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from lfm.collectors.players import LIST_KEYS, extract_list

# Claves cuyo valor identifica a una persona. Solo se sustituyen dentro de dicts que "parecen
# persona" (ver _looks_like_person), de modo que {"team": {"name": "Celta"}} se conserva.
PERSON_NAME_KEYS = frozenset(
    {
        "name",
        "nickname",
        "firstName",
        "lastName",
        "shortName",
        "fullName",
        "slug",
        "playerName",
        "managerName",
        "userName",
        "email",
    }
)
# Claves cuya presencia delata a un jugador o a un mánager.
PERSON_MARKER_KEYS = frozenset(
    {
        "positionId",
        "marketValue",
        "playerStatus",
        "nickname",
        "playerMaster",
        "managerName",
        "userId",
        "manager",
    }
)
FAKE_HOST = "https://assets.example.invalid"
# Nombres de archivo "neutros" (256x256.png, 001.jpg) se conservan; el resto podría llevar el
# nombre del jugador y se sustituye por image.<ext>.
_NEUTRAL_BASENAME = re.compile(r"^[0-9x_\-]+\.[a-z0-9]+$", re.IGNORECASE)


def _looks_like_person(d: dict) -> bool:
    return bool(PERSON_MARKER_KEYS & d.keys())


def _is_url(v: str) -> bool:
    return v.startswith(("http://", "https://"))


def _pseudonym(key: str, idx: int) -> str:
    n = f"{idx:03d}"
    return {
        "nickname": f"J{n}",
        "shortName": f"J{n}",
        "firstName": f"Nombre{n}",
        "lastName": f"Apellido{n}",
        "slug": f"jugador-{n}",
        "managerName": f"Manager {n}",
        "userName": f"manager{n}",
        "email": f"persona{n}@example.invalid",
    }.get(key, f"Jugador {n}")


class Anonymizer:
    """Sustituciones deterministas: la misma persona (mismo id) recibe siempre el mismo seudónimo
    y la misma URL recibe siempre la misma URL falsa."""

    def __init__(self) -> None:
        self._people: dict[Any, int] = {}
        self._urls: dict[str, int] = {}

    def _person_index(self, d: dict) -> int:
        key = ("id", d["id"]) if d.get("id") is not None else ("obj", id(d))
        return self._people.setdefault(key, len(self._people) + 1)

    def _fake_url(self, url: str) -> str:
        idx = self._urls.setdefault(url, len(self._urls) + 1)
        basename = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        if not _NEUTRAL_BASENAME.match(basename):
            ext = basename.rsplit(".", 1)[-1] if "." in basename else "bin"
            basename = f"image.{ext}"
        return f"{FAKE_HOST}/{idx}/{basename}"

    def anonymize(self, node: Any) -> Any:
        if isinstance(node, list):
            return [self.anonymize(x) for x in node]
        if isinstance(node, dict):
            person = _looks_like_person(node)
            idx = self._person_index(node) if person else 0
            out: dict = {}
            for k, v in node.items():
                if person and k in PERSON_NAME_KEYS and isinstance(v, str):
                    out[k] = _pseudonym(k, idx)
                elif isinstance(v, str) and _is_url(v):
                    out[k] = self._fake_url(v)
                else:
                    out[k] = self.anonymize(v)
            return out
        return node


def _status(p: dict) -> Any:
    return p.get("playerStatus") or p.get("status")


def sample_list(items: list, n: int, kind: Callable[[Any], Any] | None = None) -> list:
    """Hasta `n` elementos repartidos por la lista, en el orden original, garantizando al menos
    uno de cada `kind(item)` (aunque eso supere `n`)."""
    chosen: set[int] = set()
    seen: set = set()
    if kind is not None:
        for i, it in enumerate(items):
            k = kind(it)
            if k not in seen:
                seen.add(k)
                chosen.add(i)
    step = max(1, len(items) // n) if n else len(items) or 1
    for i in range(0, len(items), step):
        if len(chosen) >= n:
            break
        chosen.add(i)
    return [items[i] for i in sorted(chosen)]


def sample_players(payload: Any, n: int = 30) -> Any:
    """Muestra de jugadores que cubre todas las combinaciones posición×estado, en el mismo
    envoltorio que la respuesta original."""
    items = extract_list(payload)
    if not items:
        return payload
    sample = sample_list(items, n, kind=lambda p: (p.get("positionId"), _status(p)))
    if isinstance(payload, list):
        return sample
    key = next(k for k in LIST_KEYS if isinstance(payload.get(k), list))
    return {**payload, key: sample}


def sample_for(name: str, payload: Any) -> Any:
    """Estrategia de muestreo por endpoint (nombre lógico usado por el dry-run)."""
    if name == "players":
        return sample_players(payload)
    if name == "activity":
        return sample_list(extract_list(payload), 12, kind=lambda a: a.get("activityTypeId"))
    if name == "market":
        return sample_list(extract_list(payload), 6, kind=lambda m: m.get("discr"))
    if name == "team" and isinstance(payload, dict) and isinstance(payload.get("players"), list):
        players = sample_list(
            payload["players"], 4, kind=lambda p: (p.get("playerMaster") or {}).get("positionId")
        )
        return {**payload, "players": players}
    return payload  # standing: entero (una fila por manager)


def count_items(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in (*LIST_KEYS, "players"):
            if isinstance(payload.get(key), list):
                return len(payload[key])
    return 1


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def write_fixture(path: Path, payload: Any, meta: dict) -> Path:
    """Escribe el fixture. Si la respuesta es un dict, los metadatos van en `_meta`; si es una
    lista, van en `<nombre>.meta.json` al lado para no alterar la forma real de la respuesta."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, dict):
        body: Any = {"_meta": meta, **payload}
    else:
        body = payload
        path.with_suffix(".meta.json").write_text(_dumps(meta), encoding="utf-8")
    path.write_text(_dumps(body), encoding="utf-8")
    return path
