#!/usr/bin/env python3
"""
Automobiliu skelbimu monitoringas kelese platformose.
Tikrina naujus skelbimus (pagal jau nustatytus marke/metu filtrus URL adresuose)
ir siuncia Telegram alerta, kai atsiranda naujas skelbimas.
"""

import os
import re
import json
import sys
import requests

# ---------------------------------------------------------------------------
# KONFIGŪRACIJA
# ---------------------------------------------------------------------------
# Kiekvienam platform'ui reikia:
#   name         - trumpas pavadinimas (naudojamas seen.json faile ir pranešimuose)
#   url          - paieškos URL su jau įdėtais markės/metų filtrais
#   link_pattern - regex, kuris HTML tekste suranda skelbimo nuorodą IR unikalų ID
#                  (regex turi turėti 2 grupes: (visa_nuoroda) ir (unikalus_id))
#
# autoplius.lt ir auto24.ee - patikrinta, veikia.
# autogidas.lt ir otomoto.pl - regex NEPATIKRINTAS (svetainės blokavo automatinį
# tikrinimą šio pokalbio metu). Pirmą kartą paleidus per GitHub Actions, patikrink
# "Actions" logus - jei "rasta 0 skelbimų", reikės pakoreguoti regex (žr. README.md).

MONITORS = [
    {
        "name": "autoplius.lt",
        "url": (
            "https://autoplius.lt/skelbimai/naudoti-automobiliai"
            "?category_id=2&make_date_to=1989"
            "&make_id%5B61%5D=0&make_id%5B66%5D=0&make_id%5B71%5D=0"
            "&make_id%5B95%5D=0&make_id%5B96%5D=0&make_id_list=61"
            "&slist=3020110755&older_not=-1"
        ),
        "link_pattern": r'href="(/skelbimai/[a-z0-9\-]+?-(\d{6,})\.html)"',
        "base_url": "https://autoplius.lt",
    },
    {
        "name": "auto24.ee",
        "url": (
            "https://www.auto24.ee/kasutatud/nimekiri.php"
            "?bn=2&a=100&b=44&f2=1989&ae=8&af=50&ssid=312353504&ad=1"
        ),
        "link_pattern": r'href="(/soidukid/(\d+))"',
        "base_url": "https://www.auto24.ee",
    },
    {
        "name": "autogidas.lt",
        "url": (
            "https://autogidas.lt/skelbimai/automobiliai/"
            "?f_42=1989&f_1%5B0%5D=Oldsmobile&f_1%5B1%5D=Cadillac"
            "&f_1%5B2%5D=Lincoln&f_1%5B3%5D=Mercury&f_1%5B4%5D=Buick"
        ),
        "link_pattern": r'href="(/skelbimas/[a-z0-9\-]+?-(\d{7,})\.html)"',
        "base_url": "https://autogidas.lt",
        "price_pattern": r'data-price="([\d\s.,]+)"',
        "currency": "€",
    },
    {
        "name": "otomoto.pl",
        "url": (
            "https://www.otomoto.pl/osobowe/buick--cadillac--lincoln--oldsmobile"
            "?search%5Bfilter_float_year%3Ato%5D=1989"
            "&search%5Bmake_model_generation%5D%5B0%5D=buick"
            "&search%5Bmake_model_generation%5D%5B1%5D=cadillac"
            "&search%5Bmake_model_generation%5D%5B2%5D=lincoln"
            "&search%5Bmake_model_generation%5D%5B3%5D=oldsmobile"
            "&search%5Border%5D=created_at%3Adesc"
        ),
        "link_pattern": r'href="(https://www\.otomoto\.pl/[a-z\-]+/oferta/[a-zA-Z0-9\-]+ID(\w+)\.html)"',
        "base_url": "https://www.otomoto.pl",
        "otomoto_article_parsing": True,
    },
    {
        "name": "ss.lv-lincoln",
        "url": "https://www.ss.lv/lv/transport/cars/search-result/?q=Lincoln+continental",
        "link_pattern": r'href="(/msg/lv/transport/cars/[a-z0-9\-]+/([a-z0-9]+)\.html)"',
        "base_url": "https://www.ss.lv",
    },
    {
        "name": "ss.lv-cadillac",
        "url": "https://www.ss.lv/lv/transport/cars/search-result/?q=cadillac",
        "link_pattern": r'href="(/msg/lv/transport/cars/[a-z0-9\-]+/([a-z0-9]+)\.html)"',
        "base_url": "https://www.ss.lv",
    },
    {
        "name": "ss.lv-oldsmobile",
        "url": "https://www.ss.lv/lv/transport/cars/search-result/?q=oldsmobile",
        "link_pattern": r'href="(/msg/lv/transport/cars/[a-z0-9\-]+/([a-z0-9]+)\.html)"',
        "base_url": "https://www.ss.lv",
    },
    {
        "name": "ss.lv-buick",
        "url": "https://www.ss.lv/lv/transport/cars/search-result/?q=buick",
        "link_pattern": r'href="(/msg/lv/transport/cars/[a-z0-9\-]+/([a-z0-9]+)\.html)"',
        "base_url": "https://www.ss.lv",
    },
]

SEEN_FILE = "seen.json"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Markės, kurias bandysime atpažinti skelbimo nuorodoje/slug'e - naudojama
# trumpam Telegram pranešimui sudaryti.
KNOWN_BRANDS = [
    "Cadillac", "Buick", "Lincoln", "Oldsmobile", "Mercury",
    "Chevrolet", "Chrysler", "Pontiac", "Dodge", "Plymouth",
]


def guess_brand(text):
    lowered = text.lower()
    for brand in KNOWN_BRANDS:
        if brand.lower() in lowered:
            return brand
    return None


_EXCHANGE_RATE_CACHE = {}


def get_exchange_rate(from_currency, to_currency="EUR"):
    """Grąžina valiutos kursą (kiek to_currency už 1 from_currency vienetą).
    Naudoja nemokamą Frankfurter API, su fallback fiksuota reikšme, jei
    užklausa nepavyksta (pvz. nėra interneto tuo momentu)."""
    if from_currency == to_currency:
        return 1.0

    key = (from_currency, to_currency)
    if key in _EXCHANGE_RATE_CACHE:
        return _EXCHANGE_RATE_CACHE[key]

    rate = None
    try:
        resp = requests.get(
            f"https://api.frankfurter.dev/v1/latest?from={from_currency}&to={to_currency}",
            timeout=10,
        )
        resp.raise_for_status()
        rate = resp.json()["rates"][to_currency]
    except Exception as e:
        print(f"[!] Nepavyko gauti {from_currency}->{to_currency} kurso ({e}), naudoju atsarginį.")
        # Atsarginiai apytiksliai kursai, jei API nepasiekiamas
        fallback_rates = {("PLN", "EUR"): 0.235}
        rate = fallback_rates.get(key, 1.0)

    _EXCHANGE_RATE_CACHE[key] = rate
    return rate

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "lt-LT,lt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] TELEGRAM_BOT_TOKEN arba TELEGRAM_CHAT_ID nenustatyti, praleidžiu siuntimą.")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    if not resp.ok:
        print(f"[!] Telegram klaida: {resp.status_code} {resp.text}")


def parse_otomoto_articles(html, base_url):
    """Otomoto.pl kiekvieną skelbimą laiko <article data-id="...">...</article>
    bloke, kuriame yra ir nuoroda, ir kaina - tai patikimiau, nei bandyti
    susieti pagal eiliškumą su atskiru JSON-LD sąrašu (kuris gali neatitikti
    dėl reklaminių/pažymėtų skelbimų)."""
    article_re = re.compile(r'<article[^>]*data-id="(\d+)"[^>]*>(.*?)</article>', re.DOTALL)
    href_re = re.compile(r'href="(https://www\.otomoto\.pl/[^"]+?\.html)"')
    # lankstus kainos gaudymas: ieškom skaičiaus <span translate="no"> viduje,
    # o valiutos - bet kur netoliese po jo (tarp jų gali būti įvairūs tegai)
    price_re = re.compile(
        r'<span[^>]*translate="no"[^>]*>\s*([\d\s\u00a0]+)\s*</span>(.{0,200}?)(PLN|EUR|z\u0142)',
        re.DOTALL,
    )
    title_re = re.compile(r'aria-label="([^"]+)"')

    listings = {}
    articles_found = 0
    prices_found = 0
    for m in article_re.finditer(html):
        article_id, body = m.group(1), m.group(2)
        articles_found += 1

        href_match = href_re.search(body)
        if not href_match:
            continue
        url = href_match.group(1)

        price, currency = None, ""
        # Patikimesnis būdas: randam valiutos žymą (PLN/zł), tada imam
        # paskutinį skaičių, esantį PRIEŠ ją - taip nesvarbu, kiek tegų
        # ar tarpų yra tarp kainos ir valiutos.
        currency_match = re.search(r'>\s*(PLN|EUR|z\u0142)\s*<', body)
        if currency_match:
            before = body[:currency_match.start()]
            number_matches = re.findall(r'>\s*(\d[\d\s\u00a0]{2,})\s*<', before)
            if number_matches:
                price = number_matches[-1].replace("\u00a0", "").replace(" ", "").strip()
                currency = currency_match.group(1)
                if currency == "z\u0142":
                    currency = "PLN"
                prices_found += 1

        title_match = title_re.search(body)
        title = title_match.group(1).strip() if title_match else ""
        brand = guess_brand(title) if title else guess_brand(url)

        listings[article_id] = {
            "url": url,
            "price": price,
            "currency": currency,
            "brand": brand,
            "title": title,
        }

    # Papildymas iš JSON-LD: ten kainos yra patikimai visiems skelbimams.
    # Susiejam pagal automobilio pavadinimą (ne pagal eiliškumą, nes
    # reklaminiai skelbimai eiliškumą sugadina).
    try:
        json_ld_match = re.search(
            r'<script id="listing-json-ld"[^>]*>(.*?)</script>', html, re.DOTALL
        )
        if json_ld_match:
            data = json.loads(json_ld_match.group(1))
            items = data.get("mainEntity", {}).get("itemListElement", [])
            by_name = {}
            for item in items:
                offered = item.get("itemOffered", {})
                spec = item.get("priceSpecification", {})
                name = (offered.get("name") or "").strip().lower()
                if name and name not in by_name:
                    by_name[name] = {
                        "price": str(spec.get("price")) if spec.get("price") else None,
                        "currency": spec.get("priceCurrency", ""),
                        "brand": offered.get("brand"),
                    }

            for item in listings.values():
                if item["price"]:
                    continue  # jau turim kainą iš HTML
                key = item["title"].strip().lower()
                match = by_name.get(key)
                if not match:
                    # bandom dalinį atitikimą (pvz. "Cadillac Deville 4.6" vs "Cadillac Deville")
                    for name, vals in by_name.items():
                        if name and (name in key or key in name):
                            match = vals
                            break
                if match and match["price"]:
                    item["price"] = match["price"]
                    item["currency"] = match["currency"]
                    if match["brand"]:
                        item["brand"] = match["brand"]
                    prices_found += 1
    except (json.JSONDecodeError, AttributeError, KeyError, TypeError):
        pass

    print(f"    [debug otomoto] rasta {articles_found} skelbimų, iš jų su kaina: {prices_found}")

    return listings


def fetch_listings(monitor):
    """Grąžina dict {unikalus_id: pilnas_url} rastą puslapyje."""
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        # pirma apsilankom pagrindiniame puslapyje, kad gautume cookies
        # (kai kurios svetainės blokuoja, jei iškart einama tiesiai į paieškos URL)
        if monitor.get("base_url"):
            try:
                session.get(monitor["base_url"], timeout=15)
            except requests.RequestException:
                pass
        resp = session.get(monitor["url"], timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[!] {monitor['name']}: nepavyko pasiekti puslapio ({e})")
        return None

    html = resp.text

    # otomoto.pl naudoja atskirą, patikimesnį parsinimo būdą (žr. paaiškinimą
    # funkcijoje parse_otomoto_articles) - jame kaina ir nuoroda susietos
    # tiesiogiai per bendrą <article data-id="..."> konteinerį.
    if monitor.get("otomoto_article_parsing"):
        listings = parse_otomoto_articles(html, monitor["base_url"])
        if len(listings) == 0:
            print(f"    [debug {monitor['name']}] atsakymo kodas: {resp.status_code}, ilgis: {len(html)} simbolių")
            print(f"    [debug {monitor['name']}] pirmi 500 simboliai: {html[:500]!r}")
        return listings

    pattern = re.compile(monitor["link_pattern"])
    price_pattern = monitor.get("price_pattern")
    price_re = re.compile(price_pattern) if price_pattern else None

    listings = {}
    for m in pattern.finditer(html):
        link, uid = m.group(1), m.group(2)
        if link.startswith("http"):
            full_url = link
        else:
            full_url = monitor["base_url"].rstrip("/") + link

        price = None
        if price_re:
            # ieškom kainos artimiausioje HTML dalyje PRIEŠ nuorodą
            # (kai kainos atributas yra bendram konteineryje, apgaubiančiame nuorodą)
            window_start = max(0, m.start() - 3000)
            segment = html[window_start:m.start()]
            price_matches = list(price_re.finditer(segment))
            if price_matches:
                price = price_matches[-1].group(1).strip()

        brand = guess_brand(link)

        listings[uid] = {
            "url": full_url,
            "price": price,
            "currency": monitor.get("currency", ""),
            "brand": brand,
        }

    if len(listings) == 0:
        print(f"    [debug {monitor['name']}] atsakymo kodas: {resp.status_code}, ilgis: {len(html)} simbolių")
        print(f"    [debug {monitor['name']}] pirmi 500 simboliai: {html[:500]!r}")

    return listings


def main():
    seen = load_seen()
    any_new = False

    for monitor in MONITORS:
        name = monitor["name"]
        print(f"Tikrinu: {name} ...")
        listings = fetch_listings(monitor)

        if listings is None:
            continue  # klaida gaunant puslapį, praleidžiam šį ratą

        if len(listings) == 0:
            print(f"[!] {name}: rasta 0 skelbimų - greičiausiai reikia pakoreguoti link_pattern regex.")

        platform_seen = set(seen.get(name, []))

        if name not in seen:
            # Pirmas paleidimas šiai platformai - tik išsaugom esamus skelbimus,
            # nesiunčiam alertų už "senus" skelbimus.
            seen[name] = list(listings.keys())
            print(f"[i] {name}: pirmas paleidimas, išsaugota {len(listings)} skelbimų kaip bazinė būsena.")
            continue

        new_ids = [uid for uid in listings if uid not in platform_seen]

        for uid in new_ids:
            any_new = True
            item = listings[uid]
            parts = []
            if item["brand"]:
                parts.append(f"<b>{item['brand']}</b>")
            if item["price"]:
                price_text = f"{item['price']} {item['currency']}".strip()
                # jei kaina PLN, papildomai parodom konvertuotą EUR reikšmę
                if item["currency"] == "PLN":
                    try:
                        price_num = float(str(item["price"]).replace(" ", "").replace(",", "."))
                        rate = get_exchange_rate("PLN", "EUR")
                        eur_value = round(price_num * rate)
                        price_text = f"~{eur_value} € ({item['price']} PLN)"
                    except (ValueError, TypeError):
                        pass
                parts.append(price_text)
            summary = " · ".join(parts) if parts else "Naujas skelbimas"
            msg = f"🚗 {summary} ({name})\n{item['url']}"
            send_telegram(msg)
            print(f"[+] Naujas skelbimas: {item['url']}")

        # atnaujinam seen sąrašą (laikom tik paskutinius ~500, kad failas neaugtų amžinai)
        updated = list(platform_seen.union(listings.keys()))
        seen[name] = updated[-500:]

    save_seen(seen)

    if not any_new:
        print("Naujų skelbimų nerasta.")


if __name__ == "__main__":
    sys.exit(main())
