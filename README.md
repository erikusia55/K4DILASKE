# Automobilių skelbimų monitoringas (autoplius.lt, auto24.ee, autogidas.lt, otomoto.pl)

Šis įrankis kas 20 minučių tikrina 4 platformas pagal jau nustatytus markės/metų
filtrus (užkoduota `scraper.py` faile pagal tavo pateiktus URL) ir siunčia
Telegram žinutę, kai atsiranda naujas skelbimas.
 
## 1. Sukurk Telegram botą (5 min)

1. Telegrame susirask `@BotFather`.
2. Parašyk `/newbot`, sek instrukcijas (duok botui vardą).
3. BotFather atsiųs **token** – atrodo maždaug taip: `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.
   Tai bus `TELEGRAM_BOT_TOKEN`.
4. Susirask savo naujai sukurtą botą Telegrame ir parašyk jam bet ką (pvz. "labas"),
   kad jis "žinotų" apie tave.
5. Naršyklėje atidaryk (pakeitęs `<TOKEN>` savo tokenu):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
6. Rasi JSON su `"chat":{"id": 123456789, ...}` – tas skaičius yra tavo `TELEGRAM_CHAT_ID`.

## 2. Susikurk GitHub repozitoriją

1. Eik į github.com → **New repository** → pavadink pvz. `auto-monitor` → **Private** (rekomenduojama).
2. Įkelk visus šiuos failus į repozitoriją:
   - `scraper.py`
   - `requirements.txt`
   - `.github/workflows/monitor.yml`
   (galima tiesiog per "Add file → Upload files" naršyklėje, arba per `git push`)

## 3. Pridėk paslaptis (Secrets)

Repo puslapyje: **Settings → Secrets and variables → Actions → New repository secret**

Pridėk du:
- `TELEGRAM_BOT_TOKEN` = tavo boto tokenas
- `TELEGRAM_CHAT_ID` = tavo chat ID

## 4. Paleisk pirmą kartą rankiniu būdu

Repo puslapyje: **Actions → "Automobiliu skelbimu monitoringas" → Run workflow**.

Pirmą kartą paleidus skriptas **neišsiųs alertų** – jis tik išsaugos esamus
skelbimus kaip "jau matytus" (baseline), kad nespamintų tavęs visais dabar
egzistuojančiais skelbimais. Nuo antro paleidimo gausi pranešimus tik apie
tikrai naujus skelbimus.

Patikrink **Actions** logus – jei kuriai nors platformai parašyta
"rasta 0 skelbimų", reiškia tos svetainės HTML struktūra skiriasi nuo numatyto
regex ir jį reikės pakoreguoti (žr. skyrių žemiau).

## 5. Jei autogidas.lt arba otomoto.pl neveikia (0 skelbimų)

Šių dviejų platformų automatinio tikrinimo nepavyko patvirtinti iš anksto
(svetainės blokavo bandymą arba nuoroda buvo per ilga). Jei logai rodo
"rasta 0 skelbimų":

1. Atsidaryk atitinkamą URL naršyklėje, paspausk dešiniu pele → "Rodyti puslapio
   kodą" (View Page Source).
2. Susirask, kaip atrodo skelbimo nuorodos HTML kode (pvz. ieškok `<a href="...`
   šalia skelbimo pavadinimo).
3. Atnaujink atitinkamo monitoriaus `link_pattern` reikšmę `scraper.py` faile,
   kad ji atitiktų tikrą nuorodos formatą.
4. Jei svetainė vis tiek blokuoja (grąžina klaidos puslapį vietoj rezultatų),
   gali prireikti sudėtingesnio įrankio (pvz. Playwright su realiu naršyklės
   varikliu) – parašyk man, padėsiu tai pridėti.

## Kaip tai veikia (trumpai)

- Kiekvienas paleidimas nuskaito visus 4 puslapius, ištraukia skelbimų ID.
- ID sąrašas saugomas `seen.json` faile, kuris po kiekvieno paleidimo
  automatiškai atnaujinamas ir "commit'inamas" atgal į repo (todėl reikia
  `contents: write` teisės workflow faile).
- Markė ir metai (iki 1989 m.) jau užfiltruoti pačiuose URL adresuose, tad
  skriptui nereikia papildomai filtruoti – tik sekti, kas nauja.
- Norėdamas pridėti/pakeisti markes ar metus, tiesiog pasikeisk atitinkamą
  platformos paieškos filtrą pačioje svetainėje ir nukopijuok naują URL į
  `scraper.py`.
