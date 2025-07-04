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


# Реферальные параметры для каждой биржи (ключ — название в lower-case)
REFERRAL_PARAMS = {
    "lbank":    ("ref",           "4XEVI"),
    "bybit":    ("ref_code",      "71984"),
    "okx":      (None,            "ua/join/25436408"),
    "kucoin":   ("r",             "af/rPC2UVN"),
    "mexc":     ("inviteCode",    "12GYmQ"),
    "bitget":   ("ref",           "u/4CS395UZ"),
    "bingx":    ("invite",        "WBU7DG"),
    "huobi":    ("invite_code",   "jadv5223"),
    "gateio":   ("ref_type",      "103"),
    "whitebit": ("referral",      "2603b5d0-55b7-49a0-b202-db326e322d9d"),
}

def append_referral(url: str, exch: str) -> str:
    """
    К добавляет к url из exchange_urls параметр из REFERRAL_PARAMS[exch].
    Сохраняет уже существующие query-параметры.
    """
    key_code = REFERRAL_PARAMS.get(exch.lower())
    if not key_code:
        return url
    key, code = key_code
    base, *rest = url.split("?", 1)
    existing = rest[0] if rest else ""
    ref = f"{key}={code}"
    new_query = f"{existing}&{ref}" if existing else ref
    return f"{base}?{new_query}"

# Обработка арбитражного канала

# Обработка арбитражного канала
def process_6620270004(text, urls):
    lines_out = []
    all_lines = text.splitlines()
    if not all_lines:
        return ""

    # Первую строку — wrap тикер
    first = all_lines[0].strip()
    m = re.match(r'^([^:\s]+):\s*(.*)', first)
    if m:
        ticker, rest = m.groups()
        lines_out.append(f'`{ticker}`: {rest}')
    else:
        lines_out.append(first)

    # Собираем список бирж по |exchange|
    exchange_tokens = re.findall(r'\|([^|]+)\|', text)
    exchange_urls   = dict(zip(exchange_tokens, urls))

    # Обрабатываем остальные строки
    for line in all_lines[1:]:
        low = line.lower().strip()

        # фильтруем стоп-слова и "график"/📈
        if should_block_line(line) or "график" in low or line.startswith("📈"):
            continue

        m2 = re.match(r'^(\S+)\s*\|([^|]+)\|\s*-\s*(.+)', line)
        if m2:
            emoji, exch, action = m2.groups()
            raw = exchange_urls.get(exch, "")
            if raw:
                clean      = raw.split('?', 1)[0]
                with_ref   = append_referral(clean, exch)
                md_link    = f"[{exch}]({with_ref})"
            else:
                md_link = exch
            line = f"{emoji} |{md_link}| - {action}"

        lines_out.append(line)

    return "\n".join(lines_out)



# Обработка MEXC

def process_2407118810(text, urls):
    lines = []
    for line in text.splitlines():
        if should_block_line(line):
            continue

        # Убираем Weex и лишние |
        line = line.replace("Weex", "").replace("|", "").strip()

        # Оборачиваем тикер
        m = re.match(r'(#mexc_[^:]+:\s*)(\S+)', line, flags=re.IGNORECASE)
        if m:
            prefix, ticker = m.groups()
            line = f"{prefix}`{ticker}`"

        # Заменяем Trade: Mexc на Markdown-линк + реферальный код
        if 'Trade: Mexc' in line:
            # Берём первую ссылку на mexc из списка
            url = next((u for u in urls if 'mexc.com' in u), None)
            if url:
                clean = url.split('?', 1)[0]
                with_ref = append_referral(clean, 'mexc')
                line = line.replace(
                    'Trade: Mexc',
                    f"Trade: [Mexc]({with_ref})"
                )
        lines.append(line)
    return "\n".join(lines)


# Обработка Bybit

def process_2354753954(text, urls):
    lines = []
    for line in text.splitlines():
        low = line.lower()
        if any(kw in low for kw in ('бонус', 'ссыл', 'силка', 'поддерж', 'підтрим')):
            continue

        # Оборачиваем тикер, если нужно
        m = re.match(r'(#bybit_[^:]+:\s*)(\S+)', line, flags=re.IGNORECASE)
        if m:
            prefix, ticker = m.groups()
            line = f"{prefix}`{ticker}`"

        # Заменяем Trade: Bybit на Markdown-линк + реферальный код
        if 'trade: bybit' in low:
            url = next((u for u in urls if 'bybit.com' in u), None)
            if url:
                clean = url.split('?', 1)[0]
                with_ref = append_referral(clean, 'bybit')
                line = re.sub(
                    r'(?i)Trade:\s*Bybit',
                    f"Trade: [Bybit]({with_ref})",
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



# ID каналів
ARB_SRC                = 6620270004
MEXC_SRC               = -1002407118810
BYBIT_DUMP_SRC         = -1002354753954
BYBIT_LIQUIDATION_SRC  = -1002579369940
NEW_SRC = -1002800273881


# Главный хендлер
# Зберігаємо, на яке повідомлення в destination ми відповідаємо для кожного символу
symbol_to_msgid: dict[str,int] = {}

def process_cornix_initial(text: str) -> tuple[str,str]:
    """
    Парсить первинне Cornix-повідомлення з Entry Zone, Targets і Stop-Loss,
    і повертає кортеж (symbol, formatted_text), де formatted_text має саме такий
    вигляд:

    $WOO

    Напрямок:  Short

    👉 Вхід: маркет  [0.06635 - 0.06730]

    ✅ Тейк: 0.06592/ 0.06494/ 0.06410/ 0.06328

    ❌ Стоп: 0.06856

    Стоп у відсотках: 2.34%

    РИЗИК 5%

    Після першого тейку ставимо стоп в б/з.
    """
    # 1) Витягуємо тікер без суфікса .P
    m = re.search(r'#([A-Z0-9/]+?)(?:\.P)?\b', text)
    raw_symbol = m.group(1) if m else ""
    symbol = f"${raw_symbol}"

    # 2) Напрямок
    dir_m = re.search(r'\b(Short|Long)\b', text)
    direction = dir_m.group(1).capitalize() if dir_m else ""

    # 3) Вхід
    entry_m = re.search(r'Entry Zone:\s*([\d\.]+\s*-\s*[\d\.]+)', text)
    entry = entry_m.group(1) if entry_m else ""

    # 4) Список тейків
    takes = re.findall(r'Target\s*\d+:\s*([\d\.]+)', text)
    takes_str = "/ ".join(takes) if takes else ""

    # 5) Стоп-лосс
    stop_m = re.search(r'Stop-Loss:\s*([\d\.]+)', text)
    stop_price = stop_m.group(1) if stop_m else ""



    formatted = (
        f"{symbol}\n\n"
        f"Напрямок:  {direction}\n\n"
        f"👉 Вхід: маркет  [{entry}]\n\n"
        f"✅ Тейк: {takes_str}\n\n"
        f"❌ Стоп: {stop_price}\n\n"
        f"РИЗИК 5%\n\n"
        "Після першого тейку ставимо стоп в б/з."
    )
    return symbol, formatted

def process_cornix_take(text: str) -> tuple[str,str]:
    """
    Парсить Take-Profit target N ✅
    """
    # знайдемо символ
    sym_m = re.search(r'#([A-Z0-9/\.]+)', text)
    symbol = sym_m.group(1) if sym_m else ""
    # знайдемо N
    n_m = re.search(r'Take-Profit target\s*(\d+)', text)
    n = int(n_m.group(1)) if n_m else 0
    names = {1:"перший тейк",2:"другий тейк",3:"третій тейк",4:"четвертий тейк"}
    label = names.get(n, f"{n}-й тейк")
    return symbol, label

def process_cornix_all_take(text:str) -> tuple[str,str]:
    sym_m = re.search(r'#([A-Z0-9/\.]+)', text)
    symbol = sym_m.group(1) if sym_m else ""
    return symbol, "Усі тейки ✅"

def process_cornix_stop(text:str) -> tuple[str,str]:
    sym_m = re.search(r'#([A-Z0-9/\.]+)', text)
    symbol = sym_m.group(1) if sym_m else ""
    return symbol, "Стоп в б/з ⛔"

# ----------------------------------------------------------------
# 5) Головний хендлер
# ----------------------------------------------------------------
# Зберігаємо, на яке повідомлення в destination ми відповідаємо для кожного символу
symbol_to_msgid: dict[str,int] = {}

@client.on(events.NewMessage(chats=list(mapping.keys())))
async def handler(event):
    src  = event.chat_id
    dst  = mapping[src]
    text = (event.message.message or "").strip()

    # 1) Cornix-канал: не фільтруємо по “Intraday,”, а дивимося на зміст
    if src == NEW_SRC:
        # Обробляємо лише ті повідомлення, що мають хоча б один із наших патернів:
        if "Entry Zone" in text:
            sym, final = process_cornix_initial(text)
            sent = await client.send_message(dst, final, parse_mode='md')
            symbol_to_msgid[sym] = sent.id
            return

        if "Take-Profit target" in text and "✅" in text:
            sym, final = process_cornix_take(text)
            reply_to = symbol_to_msgid.get(sym)
            await client.send_message(dst, final, parse_mode='md', reply_to=reply_to)
            return

        if "All take-profit targets" in text:
            sym, final = process_cornix_all_take(text)
            reply_to = symbol_to_msgid.get(sym)
            await client.send_message(dst, final, parse_mode='md', reply_to=reply_to)
            return

        if "Stop-Loss" in text or "Closed at stoploss" in text or "Stop Target Hit" in text:
            sym, final = process_cornix_stop(text)
            reply_to = symbol_to_msgid.get(sym)
            await client.send_message(dst, final, parse_mode='md', reply_to=reply_to)
            return

        # всі інші повідомлення з this каналу — ігноруємо
        return

    # 2) Всі інші канали — ваша стандартна логіка
    urls = extract_all_links(event.message)
    if src == MEXC_SRC:
        if not text.lower().startswith("#mexc"):
            return
        final = process_2407118810(text, urls)

    elif src == BYBIT_DUMP_SRC:
        if not text.lower().startswith("#bybit"):
            return
        final = process_2354753954(text, urls)

    elif src == BYBIT_LIQUIDATION_SRC:
        if not (text.startswith("🔴") or text.startswith("🟢")):
            return
        final = process_bybit_liquidations(text, urls)

    elif src == ARB_SRC:
        final = process_6620270004(text, urls)

    else:
        final = process_general(text)

    await client.send_message(dst, final, parse_mode='md', link_preview=False)





# Запуск клиента

async def main():
    print("🚀 Forwarder запущен для всех процессов")
    await client.run_until_disconnected()

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())



