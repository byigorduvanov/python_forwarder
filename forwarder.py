import re
from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl
import config

# Инициализация клиента с или без прокси
if config.PROXY:
    client = TelegramClient('session', config.API_ID, config.API_HASH, proxy=config.PROXY)
else:
    client = TelegramClient('session', config.API_ID, config.API_HASH)

# Сопоставление исходящих и целевых каналов
mapping = {m["source"]: m["dest"] for m in config.MAPPINGS}

# Извлечение всех ссылок из текста и entities

def extract_all_links(message):
    urls = set()
    if message.message:
        urls.update(re.findall(r'https?://[^\s<>"\]]+|www\.[^\s<>"\]]+', message.message))
    if message.entities:
        for entity in message.entities:
            if isinstance(entity, MessageEntityTextUrl):
                urls.add(entity.url)
            elif isinstance(entity, MessageEntityUrl):
                url = message.message[entity.offset:entity.offset+entity.length]
                urls.add(url)
    return list(urls)

# Фильтр по стоп-словам

def should_block_line(line: str) -> bool:
    blocked = [
        'Бонусные ссылки', 'поддержка', 'nazare_crypto',
        'График', 'Live Chart', 'Trade BTC/USDT',
        'Торгуйте фьючерсами', 'Perpetual Trading', 'BYBLT'
    ]
    return any(x.lower() in line.lower() for x in blocked)

# Обработка арбитражного канала

def process_6620270004(text, urls):
    lines = []
    for line in text.splitlines():
        if should_block_line(line):
            continue

        for exchange in ['binance', 'huobi', 'mexc', 'bybit', 'okx', 'gateio', 'kucoin']:
            if f'[{exchange}]' in line.lower():
                url = next((u for u in urls if exchange in u), None)
                if url:
                    clean_url = url.split('?')[0]
                    line = line.replace(f'[{exchange}]', f'[<a href="{clean_url}">{exchange}</a>]')

        lines.append(line)
    return "\n".join(lines)

# Обработка MEXC

def process_2407118810(text, urls):
    lines = []
    for line in text.splitlines():
        if should_block_line(line):
            continue

        if 'Trade: Mexc' in line:
            url = next((u for u in urls if 'mexc.com' in u), None)
            if url:
                clean_url = url.split('?')[0]
                line = line.replace('Trade: Mexc', f'Trade: <a href="{clean_url}">Mexc</a>')

        lines.append(line)
    return "\n".join(lines)

# Обработка Bybit

def process_2354753954(text, urls):
    lines = []
    for line in text.splitlines():
        if should_block_line(line):
            continue

        if 'Trade: Bybit' in line:
            url = next((u for u in urls if 'bybit.com' in u), None)
            if url:
                clean_url = url.split('?')[0]
                line = line.replace('Trade: Bybit', f'Trade: <a href="{clean_url}">Bybit</a>')

        lines.append(line)
    return "\n".join(lines)

# Универсальная обработка

def process_general(text):
    return "\n".join(line for line in text.splitlines() if not should_block_line(line))

# Главный хендлер

@client.on(events.NewMessage(chats=list(mapping.keys())))
async def handler(event):
    src = event.chat_id
    dst = mapping[src]
    text = event.message.message or ""
    urls = extract_all_links(event.message)

    if src == -1006620270004:
        final = process_6620270004(text, urls)
    elif src == -1002407118810:
        final = process_2407118810(text, urls)
    elif src == -1002354753954:
        final = process_2354753954(text, urls)
    elif src in (-1002638772677, -1002632064203):
        final = process_general(text)
    else:
        final = text

    await client.send_message(dst, final, parse_mode='html', link_preview=False)

# Запуск клиента

async def main():
    print("🚀 Forwarder запущен для всех процессов")
    await client.run_until_disconnected()

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())

