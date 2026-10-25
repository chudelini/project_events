# Kraków po godzinach

Strona wydarzeń w Krakowie: historia, sztuczna inteligencja i kultura, na najbliższe 30 dni. Wydarzenia płatne i bezpłatne, po polsku i angielsku (brak potwierdzenia języka oznaczany jako „do sprawdzenia”).

Publiczna strona: **https://chudelini.github.io/project_events/**

## Funkcje

- Lista i miesięczny kalendarz, filtry tematu, terminu, bezpłatnych wydarzeń i wyszukiwanie.
- Opis, źródło i link wydarzenia, miejsce, termin, data sprawdzenia.
- Google Maps: mapa, dojazd i dwa najbliższe parkingi w publicznej bazie OSM (w promieniu 1,8 km; odległość w linii prostej, bez danych o wolnych miejscach).
- Subskrypcje: `wydarzenia.ics`, `historia.ics`, `ai.ics`, `kultura.ics`. Przycisk subskrypcji i instrukcje dla Apple, Google Calendar i Outlooka na stronie.
- Stałe UID, SEQUENCE i LAST-MODIFIED: zmiana terminu istniejącego wydarzenia aktualizuje wpis w kalendarzu.
- Obsługa jawnie odwołanych wydarzeń; brak wpisu na liście nie jest sam w sobie dowodem odwołania.

## Automatyczne aktualizacje

GitHub Actions uruchamia import i publikację w **środy i soboty o 08:17, Europe/Warsaw** (z uwzględnieniem zmiany czasu). Możliwe są opóźnienia infrastruktury GitHuba. Można też wybrać **Actions → Aktualizuj wydarzenia i publikuj → Run workflow**.

Aktualizacje działają po stronie GitHuba, bez uruchomionego komputera i bez kluczy płatnych API. Workflow zapisuje stan pobrania w repozytorium, co utrzymuje historię, zapobiega utracie danych po restarcie i zapewnia regularną aktywność repozytorium.

Monitorowane źródła to Muzeum Krakowa, Muzeum Archeologiczne, AI × Voices, Nowohuckie Centrum Kultury i Sii Polska. To wybór z monitorowanych źródeł, nie kompletny spis wszystkich wydarzeń w mieście. Zmiana struktury strony organizatora może wymagać aktualizacji parsera.

W razie awarii źródła zachowywane są ostatnie dane i ich rzeczywista data sprawdzenia. Strona wyświetla komunikat o błędzie / danych starszych niż 5 dni. Całkowity błąd importu zatrzymuje publikację. Historia 90 dni pozwala kalendarzom zsynchronizować zmiany. Aplikacje kalendarza samodzielnie ustalają częstotliwość odświeżania; pobranie .ics jest jednorazowym importem, nie subskrypcją.

## Uruchomienie lokalne

Wymagany Python 3.12+ oraz Node.js do opcjonalnego sprawdzenia składni JS.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/update.py
.venv/bin/python scripts/validate.py
python3 -m http.server 8765 --directory site --bind 127.0.0.1
```

Podgląd: http://127.0.0.1:8765/. `scripts/update.py --offline` regeneruje kalendarze i plik danych z zapisanej historii bez kontaktowania się ze źródłami.

## GitHub Pages

Publikacja: **Settings → Pages → Build and deployment → Source: GitHub Actions**. Kod strony znajduje się w `site/`, a workflow w `.github/workflows/update-and-deploy.yml`. Repozytorium publiczne umożliwia GitHub Pages na planie Free. W razie przeniesienia strony zaktualizuj `site_url` w `config.json`.

## Dane i licencje

Wydarzenia: krótkie informacje i odnośniki do organizatorów; ich serwisy pozostają źródłem zasad wstępu i zapisów. Nie przenosimy zdjęć ani pełnych programów organizatorów.

Lokalizacje i parkingi: © OpenStreetMap contributors, [ODbL 1.0](https://www.openstreetmap.org/copyright), wyszukiwanie Nominatim oraz Overpass. Dane pochodne parkingów i geokodowania przechowujemy jawnie w `site/data/` z datą pobrania. Dostęp do parkingów w OSM bywa niepełny; sprawdź oznakowanie na miejscu.

Dokumentacja techniczna: [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages), [harmonogramy Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [Google Maps URLs](https://developers.google.com/maps/documentation/urls/get-started).
