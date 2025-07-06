#!/usr/bin/env python3
import asyncio
import json
import logging
import socks
from telethon import TelegramClient
from telethon.tl.types import Message

# ──────────────────────────────────────────────────────────────────
# Логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S"
)

# Ваші дані
api_id    = 21430994
api_hash  = 'd2ac107a6c8c5d2e1ec4ab0faaaee02d'
phone     = '+380997471990'    # номер без пробілів
twofa     = 'Google_pro2004'   # 2FA-пароль, якщо є

# SOCKS5-проксі
proxy = (
    socks.SOCKS5,
    '5.35.38.164',
    28505,
    True,
    'chaplin',
    'dQ7pA6ZxtN'
)

# ID групи (з префіксом -100) та ID теми
chat_id     = -1002423792428
topic_id    =     23183

# Файл для запису (JSON-Lines)
output_file = 'thread_messages.jsonl'
# ──────────────────────────────────────────────────────────────────

async def main():
    # 1) Унікальний файл сесії, щоб не затирати інші пристрої
    session_name = f"session_{phone.lstrip('+')}"
    logging.info("Використовую сесію %r.session", session_name)

    # 2) Створюємо клієнт із проксі
    client = TelegramClient(session_name, api_id, api_hash, proxy=proxy)

    # 3) .start() обробить авторизацію лише при відсутності сесії
    await client.start(phone=phone, password=twofa)
    logging.info("✅ Успішна авторизація")

    # 4) Знаходимо потрібний чат серед діалогів
    logging.info("Шукаю чат з ID=%s…", chat_id)
    target = None
    async for dlg in client.iter_dialogs():
        if dlg.id == chat_id:
            target = dlg.entity
            logging.info("✅ Знайдено чат: %r", dlg.title or dlg.name)
            break

    if not target:
        logging.error("❌ Чат з ID=%s не знайдено", chat_id)
        await client.disconnect()
        return

    # 5) Стрімимо повідомлення в JSON-Lines
    logging.info("Починаю дамп теми %s у %s…", topic_id, output_file)
    count = 0
    with open(output_file, 'w', encoding='utf-8') as f:
        async for m in client.iter_messages(entity=target, reply_to=topic_id, limit=None):
            if isinstance(m, Message) and m.text:
                line = {
                    'id':        m.id,
                    'date':      m.date.isoformat(),
                    'sender_id': m.sender_id,
                    'text':      m.text
                }
                f.write(json.dumps(line, ensure_ascii=False) + '\n')
                count += 1
                if count % 500 == 0:
                    logging.info("  🔄 Збережено %d повідомлень…", count)

    logging.info("✅ Завершено! Всього збережено %d повідомлень у %s", count, output_file)
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
