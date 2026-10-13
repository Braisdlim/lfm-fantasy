"""Envío de mensajes a Telegram (canal de avisos; no hay conversación).

**Un aviso roto nunca puede tumbar el job.** El 2026-09-08 dos ejecuciones del job diario se
marcaron como fallidas cuando la recogida había ido bien: lo que reventó fue el `_fmt` del mensaje.
Desde entonces `send()` no lanza nunca y devuelve `False` explicando por qué no pudo enviar.

Puesta en marcha (una vez):

    1. En Telegram, habla con @BotFather y manda /newbot. Te da un token.
    2. Abre un chat con tu bot recién creado y mándale cualquier cosa ("hola").
    3. uv run python -m lfm.notify.telegram chat-id --token <TOKEN>   -> te dice tu chat_id
    4. Guarda TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env y en los secretos de Actions.
    5. uv run python -m lfm.notify.telegram test                      -> comprueba que llega
"""

from __future__ import annotations

import httpx

from lfm.config import settings

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 15


def send(text: str, *, silent: bool = False) -> bool:
    """Manda un mensaje. Devuelve si se envió; **nunca lanza**.

    Sin credenciales no es un error: se imprime y se sigue, que es lo que pasa en local."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        print(f"[telegram desactivado] {text}")
        return False
    try:
        r = httpx.post(
            API.format(token=settings.telegram_bot_token, method="sendMessage"),
            json={
                "chat_id": settings.telegram_chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_notification": silent,
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as e:
        print(f"[telegram] no se pudo enviar: {type(e).__name__}: {e}")
        return False
    if r.status_code != 200:
        # la API explica el motivo en `description`: chat_id mal, bot bloqueado, HTML inválido...
        detalle = ""
        try:
            detalle = r.json().get("description", "")
        except ValueError:
            detalle = r.text[:200]
        print(f"[telegram] la API respondió {r.status_code}: {detalle}")
        return False
    return True


def chat_id_from_updates(token: str) -> list[tuple[str, str]]:
    """Los chats que le han escrito al bot, para no tener que buscar el id a mano.

    Telegram solo los guarda 24 h y solo si el chat ha mandado algún mensaje: si sale vacío,
    escríbele algo al bot y vuelve a ejecutarlo."""
    r = httpx.get(API.format(token=token, method="getUpdates"), timeout=TIMEOUT)
    r.raise_for_status()
    out: dict[str, str] = {}
    for u in r.json().get("result", []):
        chat = (u.get("message") or u.get("channel_post") or {}).get("chat") or {}
        if chat.get("id") is not None:
            nombre = chat.get("title") or " ".join(
                x for x in (chat.get("first_name"), chat.get("last_name")) if x
            )
            out[str(chat["id"])] = nombre or chat.get("type", "?")
    return sorted(out.items())


if __name__ == "__main__":  # pragma: no cover
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Utilidades del canal de avisos")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("chat-id", help="lista los chats que han escrito al bot")
    p.add_argument("--token", help="por defecto, TELEGRAM_BOT_TOKEN del entorno")
    sub.add_parser("test", help="manda un mensaje de prueba con la configuración actual")

    args = ap.parse_args()
    if args.cmd == "chat-id":
        token = args.token or settings.telegram_bot_token
        if not token:
            sys.exit("Falta el token: pásalo con --token o ponlo en TELEGRAM_BOT_TOKEN")
        chats = chat_id_from_updates(token)
        if not chats:
            sys.exit(
                "Ningún chat ha escrito al bot en las últimas 24 h.\n"
                "Abre Telegram, búscalo por su nombre de usuario, mándale 'hola' y repite."
            )
        print("Chats que han escrito al bot:")
        for cid, nombre in chats:
            print(f"  TELEGRAM_CHAT_ID={cid}   ({nombre})")
    else:
        ok = send("✅ <b>lfm</b> conectado. Este es el canal de avisos del job.")
        print("Enviado." if ok else "No se envió; mira el motivo arriba.")
        sys.exit(0 if ok else 1)
