"""
Pyrogram TG Service — ищет лида в Telegram по телефону / @нику и отправляет скрипт.
Запуск: python tg_service.py
"""

import os
import asyncio
import time
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify
from pyrogram import Client
from pyrogram.errors import (
    FloodWait, UserPrivacyRestricted, PeerIdInvalid,
    UsernameNotOccupied, UsernameInvalid, PhoneNumberInvalid,
    RPCError
)

app = Flask(__name__)

API_ID          = int(os.getenv("TG_API_ID", "0"))
API_HASH        = os.getenv("TG_API_HASH", "")
SESSION_STRING  = os.getenv("TG_SESSION_STRING", "")  # строка сессии для сервера
SESSION_FILE    = os.getenv("TG_SESSION", "lead_session")  # файл для локального запуска
MIN_INTERVAL    = int(os.getenv("TG_MIN_INTERVAL", "1800"))
PORT            = int(os.getenv("PORT", "5001"))


def get_greeting() -> str:
    msk = datetime.now(timezone(timedelta(hours=3)))
    h = msk.hour
    if 6 <= h < 12:
        return "Доброе утро"
    elif 12 <= h < 18:
        return "Добрый день"
    elif 18 <= h < 23:
        return "Добрый вечер"
    else:
        return "Добрый день"


SCRIPTS = {
    "design_costume": (
        "{greeting} 🙂\n\n"
        "Меня зовут Виктория, куратор Факультета дизайна Синергии 🎓\n\n"
        "Увидела вашу заявку на факультет дизайна одежды - "
        "хочу лично помочь разобраться, подходит ли оно именно вам 🤍\n\n"
        "Как я могу к вам обращаться? ✨"
    ),
    "design_arch": (
        "{greeting} 🙂\n\n"
        "Меня зовут Виктория, куратор Факультета дизайна Синергии 🎓\n\n"
        "Увидела вашу заявку на архитектурный факультет - "
        "хочу лично помочь разобраться, подходит ли оно именно вам 🤍\n\n"
        "Как я могу к вам обращаться? ✨"
    ),
    "art_2024": (
        "{greeting} 🙂\n\n"
        "Меня зовут Виктория, куратор Факультета дизайна Синергии 🎓\n\n"
        "Увидела вашу заявку на арт-факультет - "
        "хочу лично помочь разобраться, подходит ли оно именно вам 🤍\n\n"
        "Как я могу к вам обращаться? ✨"
    ),
    "design_2024": (
        "{greeting} 🙂\n\n"
        "Меня зовут Виктория, куратор Факультета дизайна Синергии 🎓\n\n"
        "Увидела вашу заявку на факультет дизайна - "
        "хочу лично помочь разобраться, подходит ли оно именно вам 🤍\n\n"
        "Как я могу к вам обращаться? ✨"
    ),
}

DEFAULT_SCRIPT = (
    "{greeting} 🙂\n\n"
    "Меня зовут Виктория, куратор Факультета дизайна Синергии 🎓\n\n"
    "Увидела вашу заявку на факультет дизайна - "
    "хочу лично помочь разобраться, подходит ли оно именно вам 🤍\n\n"
    "Как я могу к вам обращаться? ✨"
)

_last_send_time: float = 0.0


def make_client():
    """Создаёт клиент — через StringSession (сервер) или файл (локально)."""
    if SESSION_STRING:
        return Client(":memory:", api_id=API_ID, api_hash=API_HASH,
                      session_string=SESSION_STRING)
    return Client(SESSION_FILE, api_id=API_ID, api_hash=API_HASH)


async def _find_and_send(name: str, phone: str, tg_username: str, message: str) -> dict:
    async with make_client() as client:
        target = None
        found_via = None

        if tg_username:
            handle = tg_username.strip()
            if "t.me/" in handle:
                handle = handle.split("t.me/")[-1].split("?")[0].strip("/")
            handle = handle.lstrip("@").strip()
            if handle:
                try:
                    target = await client.get_users(handle)
                    found_via = "username"
                except (UsernameNotOccupied, UsernameInvalid, PeerIdInvalid, RPCError):
                    pass

        if not target and phone:
            clean = phone.replace(" ", "").replace("-", "")
            try:
                res = await client.import_contacts([
                    {"phone_number": clean, "first_name": name or "Lead", "last_name": ""}
                ])
                if res.imported:
                    uid = res.imported[0].user_id
                    target = await client.get_users(uid)
                    found_via = "phone"
                    try:
                        await client.delete_contacts([target.id])
                    except Exception:
                        pass
            except (PhoneNumberInvalid, RPCError) as e:
                app.logger.warning(f"Phone lookup error: {e}")

        if not target:
            return {"found": False, "sent": False, "error": "Пользователь не найден в TG"}

        try:
            text = message.replace("{name}", (name or "").split()[0] if name else "")
            await client.send_message(target.id, text)
            return {
                "found": True, "sent": True,
                "found_via": found_via,
                "tg_id": target.id,
                "tg_username": getattr(target, "username", "") or "",
                "tg_name": f"{getattr(target,'first_name','') or ''} {getattr(target,'last_name','') or ''}".strip()
            }
        except UserPrivacyRestricted:
            return {"found": True, "sent": False,
                    "tg_id": target.id,
                    "tg_username": getattr(target, "username", "") or "",
                    "error": "Закрытые настройки приватности"}
        except FloodWait as e:
            return {"found": True, "sent": False, "error": f"FloodWait {e.value}s"}
        except Exception as e:
            return {"found": True, "sent": False, "error": str(e)}


@app.route("/send", methods=["POST"])
def send():
    global _last_send_time
    data = request.get_json(force=True) or {}

    elapsed = time.time() - _last_send_time
    if _last_send_time > 0 and elapsed < MIN_INTERVAL:
        wait = int(MIN_INTERVAL - elapsed)
        return jsonify({
            "queued": True,
            "wait_seconds": wait,
            "message": f"Rate limit: следующая отправка через {wait//60} мин {wait%60} сек"
        }), 429

    name        = data.get("name", "")
    phone       = data.get("phone", "")
    tg_username = data.get("tg_username", "")
    product     = data.get("product", "")

    template = data.get("message") or SCRIPTS.get(product, DEFAULT_SCRIPT)
    message  = template.replace("{greeting}", get_greeting())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            _find_and_send(name, phone, tg_username, message)
        )
    except Exception as e:
        result = {"found": False, "sent": False, "error": str(e)}
    finally:
        loop.close()

    if result.get("sent"):
        _last_send_time = time.time()

    return jsonify(result)


@app.route("/health")
def health():
    last = int(_last_send_time)
    wait = max(0, MIN_INTERVAL - int(time.time() - _last_send_time)) if last else 0
    return jsonify({"status": "ok", "last_send_unix": last, "next_available_in_sec": wait})


if __name__ == "__main__":
    if API_ID == 0 or not API_HASH:
        print("[ERROR] Заполни TG_API_ID и TG_API_HASH в .env!")
        exit(1)
    if not SESSION_STRING and not os.path.exists(f"{SESSION_FILE}.session"):
        print("[ERROR] Нет строки сессии. Запусти generate_session.py")
        exit(1)
    print(f"[OK] TG Service запускается на порту {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
