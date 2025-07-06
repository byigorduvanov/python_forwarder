#!/usr/bin/env python3
import asyncio, json
from telethon import TelegramClient
from telethon.tl.types import Message

api_id    = 26768625
api_hash  = 'd2ccaf19443a02d26e72040579f64152'

# Замість чистого числа перепишіть так,
# щоб воно було без префіксу -100 — Telethon сам до нього додасть:
chat_internal_id = -1002046293798
thread_id        = 2
output_file      = 'thread_messages.json'

async def dump_thread():
    client = TelegramClient('session', api_id, api_hash)
    await client.start()

    # 1) Знаходимо серед діалогів наш чат:
    target = None
    async for dialog in client.iter_dialogs():
        # dialog.id у Telethon для каналів = внутрішній ID
        if dialog.id == chat_internal_id:
            target = dialog.entity
            break

    if not target:
        print(f'❌ Я не знайшов чат з ідентифікатором {chat_internal_id}.')
        print('   Переконайтеся, що ви дійсно є учасником групи чи каналу.')
        await client.disconnect()
        return

    print(f'✅ Знайшов чат: {dialog.name!r}')

    # 2) Тепер збираємо повідомлення, відфільтровані за reply_to = thread_id
    msgs = []
    async for m in client.iter_messages(entity=target, reply_to=thread_id, limit=None):
        if isinstance(m, Message) and m.text:
            msgs.append({
                'id':        m.id,
                'date':      m.date.isoformat(),
                'sender_id': m.sender_id,
                'text':      m.text
            })

    msgs.reverse()  # щоб від найстарішого до найновішого
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(msgs, f, ensure_ascii=False, indent=2)

    print(f'Збережено {len(msgs)} повідомлень у {output_file}')
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(dump_thread())
