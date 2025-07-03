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

def process_new_signal(text: str) -> str:
    """
    Приводим сигнал вида:
      😘 Новая сделка | $NEAR
      Направление: SHORT
      Вход: [2.2950 - 2.3245]
      Тейк: 2.2820/ 2.2450/ 2.2111/ 2.1679
      Стоп: 2.3854(3.15%)
      …
    в формат:
      $NEAR

      Напрямок:  Short

      👉 Вхід: маркет  [2.2950 - 2.3245]

      ✅ Тейк: 2.2820/ 2.2450/ 2.2111/ 2.1679

      ❌ Стоп: 2.3854

      Стоп у відсотках: 3.15%

      РИЗИК 5%

      Після першого тейку ставимо стоп в б/з.
    """
    # символ
    sym = re.search(r'Новая сделка\s*\|\s*(\$\w+)', text)
    symbol = sym.group(1) if sym else ''

    # направление
    dir_ = re.search(r'Направление:\s*(\w+)', text)
    direction = dir_.group(1).capitalize() if dir_ else ''

    # вход
    ent = re.search(r'Вход:\s*\[([^\]]+)\]', text)
    entry = ent.group(1) if ent else ''

    # тейк
    tk = re.search(r'Тейк:\s*([^\n]+)', text)
    take = tk.group(1).strip() if tk else ''

    # стоп-цена
    st = re.search(r'Стоп:\s*([\d.]+)', text)
    stop_price = st.group(1) if st else ''

    # стоп-процент
    sp = re.search(r'Стоп:[^\(]*\(([\d.]+)%\)', text)
    stop_pct = sp.group(1) + '%' if sp else ''

    risk = '5%'  # жестко задано, как вы просили

    return (
        f"{symbol}\n\n"
        f"Напрямок:  {direction}\n\n"
        f"👉 Вхід: маркет  [{entry}]\n\n"
        f"✅ Тейк: {take}\n\n"
        f"❌ Стоп: {stop_price}\n\n"
        f"Стоп у відсотках: {stop_pct}\n\n"
        f"РИЗИК {risk}\n\n"
        "Після першого тейку ставимо стоп в б/з."
    )
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
# Словник винятків для реплаїв

# Глобальний словник для зв'язку оригінал → переслане повідомлення
forwarded_map: dict[tuple[int,int], int] = {}
# Словник винятків для реплаїв
# Словник винятків для реплаїв
REPLY_OVERRIDES = {
    "Немного не достаем до цели":      "перший тейк, стоп в б/з",
    "Фиксируем сейчас 25% позиции":    None,
    "Забираем первую цель":            "другий тейк",
    "Первая цель есть":                "третій тейк",
    "Забрали вторую цель":             "четвертий тейк",
    "Зафиксировал ещё 25% позиции":    None,
    "Еще 25% позиции":                 None,
    "Закрылись в бу":                  "стоп в б/з",
    "Тейк":                  "Тейк",
    "✔️Забрали вторую цель":                  "Другий тейк",
}

def process_reply(text: str) -> str:
    """
    Збираємо з вхідного text тільки ті рядки, які є в REPLY_OVERRIDES
    і в яких значення не None. Решту ігноруємо.
    """
    out_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in REPLY_OVERRIDES:
            uk = REPLY_OVERRIDES[stripped]
            if uk:
                out_lines.append(uk)
            # якщо uk is None — пропускаємо цю рядок
    return "\n".join(out_lines)


@client.on(events.NewMessage(chats=list(mapping.keys())))
async def handler(event):
    src = event.chat_id
    dst = mapping[src]
    text = (event.message.message or "").strip()

    # 1) Реплай — обробляємо винятками
    if event.message.reply_to_msg_id:
        final = process_reply(text)
        # якщо нічого не залишилося — ігноруємо весь event
        if not final:
            return

    # 2) Нові сигнали в NEW_SRC
    elif src == NEW_SRC:
        if re.match(r'^😘\s*Новая сделка\s*\|\s*\$\w+', text):
            final = process_new_signal(text)
        else:
            return

    # 3) Інші канали — ваша існуюча логіка
    else:
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

    # Після отримання final — пересилаємо і зберігаємо мапінг для реплаїв
    reply_to_id = None
    if event.message.reply_to_msg_id:
        reply_to_id = forwarded_map.get((src, event.message.reply_to_msg_id))

    sent = await client.send_message(
        dst,
        final,
        parse_mode='md',
        link_preview=False,
        reply_to=reply_to_id
    )
    forwarded_map[(src, event.message.id)] = sent.id



# Запуск клиента

async def main():
    print("🚀 Forwarder запущен для всех процессов")
    await client.run_until_disconnected()

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())



