# get.tech Free .tech Domain Farm

Полностью автоматический фарм бесплатных `.tech` доменов (1 год) через промо-акцию Hacktoberfest на [get.tech](https://get.tech/). Чистый HTTP, без браузера, без карты, $0 за домен.

**Промо-код:** `hacktoberfestd0b8o5` — «One year free .tech domain», скидка 12.99 = полная цена года, к оплате $0. Купон работает 1 раз на аккаунт → масс-фарм = 1 аккаунт на домен.

**Пруф (2026-10-18):** 7 доменов заказано подряд с одного IP, все с `discount: 12.99`, оплата $0:

| Домен | Invoice ID | Статус |
|---|---|---|
| reformboss.tech | 144667507 | PendingExecution → активация |
| gothbreach.tech | 144673571 | OK |
| teleraptor.tech | 144676214 | OK |
| iishko.tech | (в банке) | OK |
| gothide.tech | 144676308 | OK |
| reformgang.tech | 144676504 | OK |
| alstack.tech | — | 504-storm → восстановлен свипером |

---

## Быстрый старт

```bash
pip install curl_cffi

# один домен (аккаунт создастся сам из одноразового ящика):
python gt_claim_one.py myproject

# со своим email:
python gt_claim_one.py myproject my@mail.com
```

В конце скрипт печатает **email + пароль + customerid аккаунта** — сохрани, это твой доступ к DNS-панели домена.

### Масс-фарм

```bash
# 3 параллельных воркера, каждый обрабатывает свою долю кандидатов:
python gt_farm.py 0 3 &
python gt_farm.py 1 3 &
python gt_farm.py 2 3 &

# свипер восстановления упавших заказов (504-шторм):
python gt_retry.py &
```

- Список кандидатов правится в секции `CANDIDATE SEEDS` в `gt_farm.py` (BRANDS + BASES×SUFFIX ≈ 1200+ комбинаций из коробки).
- Всё заказанное пишется в **`gt_bank.jsonl`**: `email, gettech_password, customerid, domain, invoiceid, orderid, discount, ts`. Это твой реестр для DNS — бэкапь его.
- Опционально: `GT_MAILS_FILE` (файл `email:password` на строку) как фолбэк-пул почты; `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`/`TELEGRAM_THREAD_ID` — нотификации о каждом CLAIMED.

---

## Детальный гайд: протокол API get.tech

get.tech — витрина Radix (реестр `.tech`). Фронтенд — Laravel + Alpine, весь чекаут ходит в `https://get.tech/api/*` обычным JSON. Cloudflare защищает сайт, но **`curl_cffi` с `impersonate="chrome131"` проходит без челленджа** (проверено с резидентного IP; с VPS/DC-IP может прилететь managed challenge).

### Шаг 0. Сессия + CSRF

Купон кладётся в сессию через URL поиска:

```
GET https://get.tech/search?domain=<имя>&coupon=hacktoberfestd0b8o5
```

Из HTML вынимаем `<meta name="csrf-token" content="...">`. На все API-вызовы ставим заголовки:

```
X-CSRF-TOKEN: <token>
X-Requested-With: XMLHttpRequest
Accept: application/json, text/plain, */*
Referer: https://get.tech/search
Origin: https://get.tech
```

### Шаг 1. Регистрация аккаунта (email-верификация НЕ нужна)

```json
POST /api/signup
{"signup": {
  "name": "John Smith", "address": "12 Main Street", "company": "N/A",
  "city": "Wilmington", "zip": "19801",
  "username": "<email>", "password": "<пароль>",
  "countryCode": "1", "phone": "2025550123",
  "country": "US", "state": "Other", "otherState": "other"
}}
```

Ответ содержит `customerid`. Аккаунт живой сразу, никакого подтверждения почты — поэтому идеально работают одноразовые ящики (в скриптах — voidash API: `POST https://api.voidash.com/api/v1/inboxes {"domain":"voidash.bond"}` → `{"address": "..."}`, безлимитно).

Ошибка `"<email> is already a Customer."` = почта уже занята → следующий ящик.

### Шаг 2. Вход

```json
POST /api/login
{"username": "<email>", "password": "<пароль>"}
```

→ 200 + `customerid`. Сессия (cookie) авторизована. `GET /api/logged-in` — проверка.

### Шаг 3. Прайс

```
GET /api/pricing  →  {"pricing": "<JSON-СТРОКА>"}
```

Внутри (после `json.loads` второго уровня):

```json
"dottech": {
  "addnewdomain": {"1": 12.99, "2": 49.99, "3": 84.99, ...},
  "privacy_protection": 9.0,
  "renewdomain": {"1": 47.99, ...}
}
```

**Ключи — СТРОКИ** (`"1"`, не `1` — иначе KeyError). Цена года = `addnewdomain["1"]` = 12.99. `privacy_protection` 9.0 — платный аддон, **не включать** (условие промо: отключить платные security/privacy-услуги).

### Шаг 4. Проверка доступности

```
GET /api/search-availability?domain=<имя>
```

Точный матч в списке: `domain == "<имя>.tech"`, `status == "available"`, **без поля `pricing`** (с `pricing` = премиум-домен за отдельные деньги). Другие статусы: `regthroughothers` (занят), `reserved` и т.п.

### Шаг 5. Корзина — КРИТИЧНЫЙ ФОРМАТ

```json
POST /api/update-cart
{"cart": [{"category": "domorder", "product": "dottech",
           "domain": "<имя>.tech", "duration": 1, "price": 12.99}]}
```

→ ответ `updated`. **Без `duration` и `price` в item следующие шаги падают в Laravel-500 «Whoops»** (фронтенд кладёт их из /pricing; сервер ждёт то же). Поле `status` не нужно. Ничего лишнего (privacy) не добавлять.

### Шаг 6. Купон

Купон уже в сессии из URL шага 0. Контроль:

```
GET  /api/get-coupon-code          → текущий купон сессии
POST /api/test-coupon {"coupon": "hacktoberfestd0b8o5"}
→ {"message": "Coupon applied!", "status": "Success",
   "description": "One year free .tech domain"}
```

### Шаг 7. Заказ

```
POST /api/place-order      (пустое тело)
→ 200 {"message": "Finalizing Order", "status": "Success", "order": ["<JSON-строка>"]}
```

Внутри `order[0]`: `invoiceid`, `orderid`/`entityid`, `discount: "12.99"` (= полная скидка, к оплате $0), `actionstatus: "PendingExecution"` → активация регистрации минуты-часы. **PayPal/Stripe не нужны при нулевой сумме.**

### Итого по деньгам

`12.99 (домен) − 12.99 (купон) + 0 (privacy отключён) = $0`. Карта не запрашивается.

---

## DNS: как забрать управление доменом

Каждый домен живёт в **своём аккаунте** (купон 1/акк). Доступы — в `gt_bank.jsonl`.

1. Логин на `https://get.tech/login` (email + `gettech_password` из банка).
2. **My Account** → список доменов → у домена: **Manage DNS** / **Manage NameServers** (панель Radix).
3. Варианты: оставить NS Radix и править A/AAAA/CNAME/MX/TXT-записи в их DNS-менеджере, либо сменить NS на свои (Cloudflare и т.д.).
4. Заказ со статусом PendingExecution появляется в панели после активации (обычно до часа).

⚠️ **Автопродление:** через год домен платно продлевается (renewdomain 1y = 47.99). Зайди в панель каждого домена и **выключи auto-renew**, если не хочешь списывания (карта для этого не привязана, но проверь).

Публичного DNS API у витрины не обнаружено — записи ставятся через веб-панель. Если найдёшь API-эндпоинты панели (DevTools → Network в разделе DNS) — PR welcome.

---

## Питфолы (проверено на себе)

1. **Ориджин get.tech периодически лежит глобально** — 504 на ВСЕ эндпоинты (подтверждалось с 3 независимых сетей). Окна жизни 5-20 минут. Все вызовы обёрнуты в retry с backoff; фармы просто ждут окна.
2. **504 ≠ провал.** Cloudflare режет по таймауту, но ориджин запрос часто ДОУСПЕВАЕТ выполнить. Симптом: signup на только что созданный ящик отвечает «already a Customer». Лечение: на «already a Customer» для своего свежего ящика — персистентно логиниться (8 попыток), а не выбрасывать почту. Аналогично place-order: после 504 проверить `GET /api/get-cart` — пустая корзина = заказ скорее всего прошёл. **Никогда не долби place-order вслепую — будет дубль заказа.**
3. **curl_cffi обязателен.** `requests`/`urllib` ловят CF-челлендж; headless-браузеры залипают на managed challenge. `impersonate="chrome131"` с резидентного IP проходит чисто.
4. **Ключи pricing — строки** (`addnewdomain["1"]`), не int.
5. **Купон = 1 free-домен на аккаунт.** Второй домен в том же аккаунте пойдёт по полной цене. Масс-фарм = свежие акки.
6. **Premium-домены** в выдаче search-availability имеют поле `pricing` и статус available — не брать (зарегистрируются за деньги, купон их не покрывает).
7. **500 «Whoops» на test-coupon/place-order** = item корзины без `duration`/`price` (см. шаг 5).
8. Одноразовые почтовые домены могут быть в блэклисте у других сервисов — для get.tech voidash-домены проходят (проверено: voidash.bond, govno.eu.cc, musor.eu.cc, pomoi.eu.cc).

---

## Файлы

| Файл | Назначение |
|---|---|
| `gt_claim_one.py` | Забрать ОДИН домен (минимальный пример протокола) |
| `gt_farm.py` | Масс-фарм: воркеры-шарды, банк, resume-state |
| `gt_retry.py` | Свитчер: восстанавливает FAIL-заказы из банка (логин → cart → place-order с контролем дублей) |
| `requirements.txt` | `curl_cffi` |

## Дисклеймер

Промо-код опубликован организаторами акции (Hacktoberfest/get.tech). Скрипты создают аккаунты на одноразовые ящики и используют купон штатным образом — 1 домен на аккаунт. Не нагружайте ориджин: в скриптах уже есть pacing (20-40с между доменами) и retry-tolerantность к 504. Всё, что заказали, — ваше: не забудьте выключить auto-renew.
