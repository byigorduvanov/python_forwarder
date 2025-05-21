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
    text = message.message or ""
    urls = []
    # 1) Спершу всі чисті URL за допомогою regex (у порядку появи)
    for m in re.finditer(r'https?://[^\s<>"\]]+|www\.[^\s<>"\]]+', text):
        url = m.group(0)
        if url not in urls:
            urls.append(url)
    # 2) Додаємо ті, що ховаються під MessageEntityTextUrl (якщо їх ще нема)
    if message.entities:
        for entity in sorted(message.entities, key=lambda e: e.offset):
            if isinstance(entity, MessageEntityTextUrl):
                u = entity.url
            elif isinstance(entity, MessageEntityUrl):
                u = text[entity.offset:entity.offset+entity.length]
            else:
                continue
            if u not in urls:
                urls.append(u)
    return urls


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
    lines_out = []
    all_lines = text.splitlines()
    if not all_lines:
        return ""

    # 1) Перший рядок — wrap ticker, не змінюємо
    first = all_lines[0].strip()
    m = re.match(r'^([^:\s]+):\s*(.*)', first)
    if m:
        ticker, rest = m.groups()
        lines_out.append(f'`{ticker}`: {rest}')
    else:
        lines_out.append(first)

    # 2) Дістаємо в порядку появи біржі з |exchange|
    exchange_tokens = re.findall(r'\|([^|]+)\|', text)

    # 3) Просто зшиваємо exchange_tokens та urls по відповідних індексах
    exchange_urls = dict(zip(exchange_tokens, urls))

    # 4) Обробляємо рядки-стікери і всі інші
    for line in all_lines[1:]:
        low = line.lower().strip()

        # стоп-слова і "графік"/📈
        if should_block_line(line) or "графік" in low or line.startswith("📈"):
            continue

        # рядок-стікер?
        m2 = re.match(r'^(\S+)\s*\|([^|]+)\|\s*-\s*(.+)', line)
        if m2:
            emoji, exch, action = m2.groups()
            url = exchange_urls.get(exch, "")
            clean = url.split('?')[0] if url else ""
            md_link = f"[{exch}]({clean})" if clean else exch
            line = f"{emoji} |{md_link}| - {action}"

        lines_out.append(line)

    return "\n".join(lines_out)



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

