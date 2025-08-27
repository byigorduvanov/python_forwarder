import re
from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl
import config
from telethon import functions
from telethon.tl.types import InputPeerChannel
from telethon.tl.functions.messages import SendMessageRequest
from telethon.tl.types import InputPeerChannel
from typing import Optional
from telethon.tl.types import InputPeerChannel
from telethon.tl.functions.messages import SendMessageRequest

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
        'Торгуйте фьючерсами', 'Perpetual Trading', 'BYBIT'
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
    "gateio":   ("ref_type",      "VGVNVF5DAG"),
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
def _action_to_market_and_dir(action: str):
    """
    Повертає (market, direction), де:
      market ∈ {'spot','swap'}
      direction ∈ {'long','short'}  (BUY трактуємо як 'long')
    """
    a = (action or "").lower()
    if any(k in a for k in ("short", "шорт")):
        return "swap", "short"
    if any(k in a for k in ("long", "лонг")):
        return "swap", "long"
    if any(k in a for k in ("buy", "куп", "покуп", "купить")):
        return "spot", "long"
    # дефолт — spot long
    return "spot", "long"

def _exch_name_only(exch_field: str) -> str:
    # "gateio (https://...)" -> "gateio"
    return exch_field.split("(", 1)[0].strip().lower()

def _normalize_exchange_slug(name: str) -> str:
    n = re.sub(r'[^a-z0-9]+', '', (name or '').lower())
    aliases = {
        'gateio': 'gate', 'gate': 'gate',
        'okex': 'okx', 'okx': 'okx',
        'huobi': 'htx', 'htx': 'htx',
        'binance': 'binance',
        'bybit': 'bybit',
        'mexc': 'mexc',
        'kucoin': 'kucoin',
        'bitget': 'bitget',
        'blofin': 'blofin',
        'ourbit': 'ourbit',
    }
    return aliases.get(n, n)

def process_6620270004(text, urls):
    lines_out = []
    all_lines = text.splitlines()
    if not all_lines:
        return ""

    # 1) Тікер
    first = all_lines[0].strip()
    m = re.match(r'^([^:\s]+):\s*(.*)', first)
    if m:
        ticker, rest = m.groups()
        lines_out.append(f'`{ticker}`: {rest}')
    else:
        lines_out.append(first)
        ticker = first.split(':', 1)[0].strip()
    ticker_slug = re.sub(r'[^a-z0-9]+', '', ticker.lower())

    # 2) |exchange| -> url
    exchange_tokens = re.findall(r'\|([^|]+)\|', text)
    exchange_urls = dict(zip(exchange_tokens, urls))

    legs = []  # зберігаємо [{'slug','market','dir'}] у порядку появи

    # 3) Обробка рядків
    for line in all_lines[1:]:
        low = line.lower().strip()
        if should_block_line(line) or "график" in low or line.startswith("📈"):
            continue

        m2 = re.match(r'^(\S+)\s*\|([^|]+)\|\s*-\s*(.+)', line)
        if m2:
            emoji, exch, action = m2.groups()

            raw = exchange_urls.get(exch, "")
            if not raw:
                murl = re.search(r'\((https?://[^)]+)\)', exch)
                raw = murl.group(1) if murl else ""

            clean = raw.split('?', 1)[0] if raw else ""
            with_ref = append_referral(clean, exch) if clean else ""

            exch_display = _exch_name_only(exch)
            exch_slug = _normalize_exchange_slug(exch_display)
            md_link = f"[{exch_display}]({with_ref})" if with_ref else exch_display

            lines_out.append(f"{emoji} |{md_link}| - {action}")

            market, direction = _action_to_market_and_dir(action)
            if len(legs) < 2:  # беремо тільки перші дві ноги
                legs.append({"slug": exch_slug, "market": market, "dir": direction})
        else:
            lines_out.append(line)

    # 4) Формуємо посилання: СПОЧАТКУ SHORT, ПОТІМ LONG/BUY
    if ticker_slug and len(legs) >= 2:
        # відсортуємо так, щоб short був першим
        legs_sorted = sorted(legs[:2], key=lambda L: 0 if L["dir"] == "short" else 1)

        uainvest_link = (
            f"https://uainvest.com.ua/arbitrage/"
            f"{ticker_slug}-{legs_sorted[0]['slug']}-{legs_sorted[0]['market']}-"
            f"{ticker_slug and ''}{legs_sorted[1]['slug']}-{legs_sorted[1]['market']}"
        )
        # ↑ залишив формат як був: ticker-EX1-market1-EX2-market2
        # (ticker_slug and '' ) тримає формат конкатенації без пробілів

        lines_out.append("")
        lines_out.append(uainvest_link)

    return "\n".join(lines_out)


# Обработка MEXC

def process_2407118810(text, urls):
    lines = []
    for line in text.splitlines():
        if should_block_line(line):
            continue

        # Убираем Weex и лишние |
        line = line.replace("Gate", "").replace("|", "").strip()

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
    Bybit Liquidations:
    - підсвічує тікер у першому рядку бектиками (для зручного копіювання)
    - додає 'Trade: [Bybit](<ref link>)' як у process_2354753954
    - фільтрує сміттєві рядки
    """
    out = []
    lines = text.splitlines()

    # 1) перший рядок: 🟢 NMRUSDT Шорт ликв.  /  🔴 NMRUSDT Лонг ликв.
    if lines:
        first = lines[0]
        m = re.match(r'^([🔴🟢])\s*([A-Z0-9]+)\b(.*)$', first.strip())
        if m:
            dot, ticker, tail = m.groups()
            # обгортаємо тікер бектиками -> копіюється по long-tap
            first = f"{dot} `{ticker}`{tail}"
        out.append(first)

    # 2) інші рядки як є, але без стоп-слів
    for line in lines[1:]:
        if should_block_line(line):
            continue
        out.append(line)

    # 3) додаємо реф-лінк "Trade: Bybit"
    #    (якщо потрібно – заміни базовий url на конкретну сторінку торгів)
    base = "https://www.bybit.com/"
    with_ref = append_referral(base, "bybit")
    out.append(f"Trade: [Bybit]({with_ref})")

    return "\n".join(out)

# Универсальная обработка
def process_general(text):
    return "\n".join(line for line in text.splitlines() if not should_block_line(line))



# ID каналів
ARB_SRC                = 6620270004
MEXC_SRC               = -1002407118810
BYBIT_DUMP_SRC         = -1002354753954
BYBIT_LIQUIDATION_SRC  = -1002579369940



# Централізована функція для діставання символу без “.P” і “/”


# ----------------------------------------------------------------
# 5) Головний хендлер




# 4) Загальний хендлер для інших каналів залишається без змін, але не обробляє NEW_SRC
@client.on(events.NewMessage(chats=list(mapping.keys())))
async def handler(event):
    src = event.chat_id
 #   if src == NEW_SRC:
  #      return  # все повідомлення NEW_SRC вже оброблені в cornix_handler

    dst  = mapping[src]
    text = (event.message.message or "").strip()
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



