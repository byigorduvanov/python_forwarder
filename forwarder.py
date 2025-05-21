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

        # видаляємо Weex і зайві вертикальні риски
        line = line.replace("Weex", "").replace("|", "").strip()

        # обгортаємо ticker у backticks
        m = re.match(r'(#mexc_[^:]+:\s*)(\S+)', line, flags=re.IGNORECASE)
        if m:
            prefix, ticker = m.groups()
            line = f"{prefix}`{ticker}`"

        # заміна Trade: Mexc → Markdown-лінк
        if 'Trade: Mexc' in line:
            url = next((u for u in urls if 'mexc.com' in u), None)
            if url:
                clean_url = url.split('?')[0]
                # ЗАМІНА тут — пишемо Markdown-лінк, а не HTML
                line = line.replace(
                    'Trade: Mexc',
                    f'Trade: [Mexc]({clean_url})'
                )

        lines.append(line)
    return "\n".join(lines)


# Обработка Bybit

def process_2354753954(text, urls):
    lines = []
    for line in text.splitlines():
        low = line.lower()

        block_keywords = ('бонус', 'ссыл', 'силка', 'поддерж', 'підтрим')
        if any(kw in low for kw in block_keywords):
            continue

        # обгортаємо тикер у backticks, якщо потрібно (аналогічно MEXC)
        m = re.match(r'(#bybit_[^:]+:\s*)(\S+)', line, flags=re.IGNORECASE)
        if m:
            prefix, ticker = m.groups()
            line = f"{prefix}`{ticker}`"

        # заміна Trade: Bybit → Markdown-лінк
        if 'trade: bybit' in low:
            url = next((u for u in urls if 'bybit.com' in u), None)
            if url:
                clean_url = url.split('?')[0]
                # тут використовуємо [Bybit](url)
                line = re.sub(
                    r'(?i)Trade:\s*Bybit',
                    f'Trade: [Bybit]({clean_url})',
                    line
                )

        lines.append(line)
    return "\n".join(lines)




#ліквідації

def process_bybit_liquidations(text, urls):
    """
    Спеціальна обробка для Bybit Liquidations:
    - прибираємо останній рядок з бонусними ссылками та поддержкой
    - (за потреби можна додати інші трансформації)
    """
    lines = text.splitlines()
    # якщо останній рядок містить "бонус" або "поддерж", відсікаємо його
    if lines and any(kw in lines[-1].lower() for kw in ("бонус", "ссыл", "поддерж")):
        lines = lines[:-1]
    return "\n".join(lines)


# Универсальная обработка

def process_general(text):
    return "\n".join(line for line in text.splitlines() if not should_block_line(line))

# Главный хендлер

# ID каналів
MEXC_SRC               = -1002407118810
BYBIT_DUMP_SRC         = -1002354753954
BYBIT_LIQUIDATION_SRC  = -1002579369940

@client.on(events.NewMessage(chats=list(mapping.keys())))
async def handler(event):
    src  = event.chat_id
    dst  = mapping[src]
    text = (event.message.message or "").strip()
    urls = extract_all_links(event.message)

    # MEXC: тільки якщо починається з "#mexc"
    if src == MEXC_SRC:
        if not text.lower().startswith("#mexc"):
            return  # ігноруємо
        final = process_2407118810(text, urls)

    # Bybit Dump: тільки якщо починається з "#bybit"
    elif src == BYBIT_DUMP_SRC:
        if not text.lower().startswith("#bybit"):
            return
        final = process_2354753954(text, urls)

        # Bybit Liquidations: тільки якщо починається з "🔴" або "🟢"
    elif src == BYBIT_LIQUIDATION_SRC:
        if not (text.startswith("🔴") or text.startswith("🟢")):
            return
        final = process_bybit_liquidations(text, urls)

    # Арбітраж
    elif src == -1006620270004:
        final = process_6620270004(text, urls)

    # Інші (general)
    elif src in (-1002638772677, -1002632064203):
        final = process_general(text)

    else:
        final = text

    await client.send_message(dst, final, parse_mode='md', link_preview=False)



# Запуск клиента

async def main():
    print("🚀 Forwarder запущен для всех процессов")
    await client.run_until_disconnected()

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())

