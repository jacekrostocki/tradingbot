# Autonomous Trading Bot — Strategia i kryteria walidacji v1.0

**Data:** 2026-11-01  
**Status:** CANDIDATE / RESEARCH ONLY — niezweryfikowana rentowność; LIVE zabroniony do ukończenia testów  
**Docelowy rynek:** Kraken Futures, liniowy BTC perpetual; opcjonalnie ETH po odrębnej walidacji  
**Alternatywa:** niezależny adapter giełdy i Spot, jeśli futures nie są dostępne lub nie przechodzą analizy kosztów/ryzyka.

## 0. Cel i granice wiedzy

Budujemy system autonomiczny 24/7, który stara się uzyskać dodatnią **wartość oczekiwaną netto po prowizjach, spreadzie, slippage, funding i kosztach operacyjnych**, z priorytetem ochrony kapitału. Nie obiecujemy dodatnich wyników ani wysokiego odsetka zyskownych dni. System może nie otwierać pozycji przez dłuższy czas. Horyzont transakcji: godziny–dni, bez wymogu zamknięcia o północy.

**Nie przeprowadzono jeszcze własnego backtestu na danych Kraken.** Poniższe parametry to hipotezy badawcze i limity projektowe, nie empirycznie potwierdzony optimum.

## 1. Konkluzje rewalidacji

1. Zachować prostą rodzinę strategii typu **time-series momentum / trend following** jako hipotezę główną; szczególnie uważać na kosztowny noise trading na 1m–5m. Badania nie gwarantują rentowności konkretnej konfiguracji.
2. Zamiast początkowej 15m EMA + ADX + wolumen: wprowadzić filtr kierunku na 4H i sygnał na 1H. 15m pozostawić wyłącznie opcjonalnie do analizy egzekucji.
3. Nie przyjmować sztywnego TP 1,5R bez testowania; preferować porównanie trailing exit z TP i time stop. Trend following wymaga miejsca na nieliczne duże zyskowne ruchy.
4. **Nie włączać** na starcie uczenia maszynowego ani adaptacyjnych zmian parametrów przez LLM. Ograniczyć liczbę porównań i prerejestrować testy.
5. Ryzyko zależne od odległości do stop, nie od samej dźwigni; cap realnego notionalu i marginu. Zabezpieczenia na giełdzie, deterministyczna logika wykonania, brak pyramidingu/martingale.
6. Kraken EEA: sprawdzić uprawnienia oraz konkretny produkt przed uruchomieniem LIVE. Dla multi-collateral **cross margin jest domyślne** — bot musi jawnie wymusić i zweryfikować isolated margin.

## 2. Hipoteza A — 4H Trend Filter + 1H Donchian Breakout

### Rynek, dane i zegar

- BTC perpetual, liniowy; ETH tylko w testach porównawczych, osobny wynik i parametry.
- Świece OHLCV: 4H do oceny trendu, 1H do wejścia, ATR i wyjść. Wszystkie obliczenia na **zamkniętych świecach**; brak look-ahead.
- Sygnał po zamknięciu świecy 1H; symulowane wejście **najwcześniej na następnej dostępnej transakcji/otwarciu kolejnego okresu**, z modelowaniem slippage. Dane giełdowe o mark, trade, index i funding synchronizowane według historycznej dostępności informacji.

### Filtr trendu (4H)

- LONG: `EMA50(4H) > EMA200(4H)` oraz ostatnia zamknięta cena 4H > EMA200(4H).
- SHORT: `EMA50(4H) < EMA200(4H)` oraz ostatnia zamknięta cena 4H < EMA200(4H).
- W innym przypadku: FLAT / NO NEW TRADE.
- EMA50/200 są **punktami startowymi**, nie potwierdzonym optimum.

### Wejście (1H)

- LONG: zamknięcie bieżącej świecy 1H **powyżej** najwyższego `high` **poprzednich** 24 kompletnych świec 1H, zgodnie z filtrem 4H.
- SHORT: zamknięcie bieżącej świecy 1H **poniżej** najniższego `low` poprzednich 24 kompletnych świec 1H, zgodnie z filtrem 4H.
- ATR(14, 1H) dodatni i poprawnie liczony, wymagana kompletna rozgrzewka EMA/ATR; nie otwieramy na niekompletnych świecach.
- Brak nowych pozycji podczas degradacji feedu, niestabilności API, niedopuszczalnego spreadu/slippage, naruszenia limitów ryzyka lub nieakceptowalnego funding — progi spread/funding określamy **przed końcowym backtestem** na części treningowej, bez strojenia na ostatniej próbce.
- Nie stosować jednocześnie filtra ADX i wolumenu jako obowiązkowych warunków. Można przetestować **jeden** jako prerejestrowany eksperyment dodatkowy.

### Wyjście i ochrona pozycji

- Po wejściu, po potwierdzeniu **faktycznie zrealizowanej** ilości, wystawić/zweryfikować giełdowy **reduce-only stop-market**, z jawnym trybem trigger (preferencyjnie mark, po potwierdzeniu zachowania kontraktu).
- Początkowy stop: `2.0 × ATR(14, 1H)` od rzeczywistej średniej ceny wejścia. Odległość i bufor likwidacyjny muszą spełniać limity kontraktu i ryzyka.
- Główny wariant wyjścia (kandydat): trailing/chandelier `3.0 × ATR(14, 1H)` od ekstremum osiągniętego **po wejściu**, aktywowany po korzystnym ruchu o co najmniej `1R` (wariant do testu), nigdy nie przesuwający stop w kierunku zwiększania ryzyka.
- Alternatywa do osobnego porównania: stały TP `2R` i pierwotny SL; odrębny wariant `exit on 1H Donchian(10)`.
- Dodatkowe wyjście: zamknięcie pozycji przy zmianie kierunku trendu 4H (zarejestrować slippage). Time stop 72h tylko jako **oddzielny wariant testowy**, nie mieszać z innymi bez kontroli eksperymentów.
- Pozycja zawsze może być zamknięta awaryjnie przez moduł Risk Engine, a ryzyko wykonania stop-market pozostaje niezerowe.

## 3. Hipoteza B (challenger) i benchmarki

- **B: Trend-filtered pullback**: kierunek 4H jak powyżej; wejście 1H po kontrolowanym cofnięciu w okolice EMA20 i powrocie powyżej/poniżej EMA20; ten sam model kosztów, sizing i ryzyka. Reguły szczegółowe zdefiniować przed testami.
- **Benchmark 0:** brak handlu (cash), jako minimalny punkt odniesienia dla strat/ryzyka.
- **Benchmark 1:** prosty trendowy long/flat BTC o dopasowanej zmienności ekspozycji; oddzielnie buy-and-hold BTC (nieporównywalne ryzyko, podać również drawdown).
- **Benchmark 2:** losowe wejścia z tym samym czasem ekspozycji, wyjściami i kosztami; ocena, czy sygnał faktycznie dodaje wartość.
- Do implementacji LIVE wybrać jeden wariant na podstawie walidacji **netto out-of-sample**, nie najwyższego zysku in-sample.

## 4. Risk Engine: twarde limity projektowe

| Reguła | Wartość startowa | Konsekwencja |
|---|---:|---|
| Ryzyko na 1 trade (PAPER) | maksimum 0,25% equity | odrzucenie/zmniejszenie ilości |
| Ryzyko na 1 trade (początkowy LIVE) | maksimum 0,10% equity | zmniejszenie ilości, jeżeli minima kontraktu nie pozwalają — brak transakcji |
| Maks. liczba jednoczesnych pozycji | 1 | nie otwierać kolejnej |
| Maks. notional / equity | 0,75× | odrzucenie/zmniejszenie |
| Maks. zadeklarowana dźwignia | 2× (isolated) | odrzucenie zlecenia |
| Drawdown od początku dnia UTC | 1% equity dnia | halt nowych wejść; procedura ograniczania ryzyka |
| Drawdown od początku tygodnia UTC | 3% equity tygodnia | halt do ręcznej autoryzacji |
| Drawdown od szczytu equity od uruchomienia | 6% | twardy halt i ręczna analiza |
| Uśrednianie strat, martingale, pyramiding | ZABRONIONE | odrzucenie |
| Zwiększanie wielkości w reakcji na serię strat | ZABRONIONE | odrzucenie |
| Nieaktualne dane, błąd połączenia, brak potwierdzonego stopa | FAIL CLOSED | nowe wejścia zablokowane; awaryjna procedura |

Liczba pozycji i limity odnoszą się do całego bota, także różnych instrumentów. W przypadku awaryjnego spadku płynności, luk cenowych i częściowego fill stop strata może przekroczyć zaplanowane 0,1%/0,25%. Limity drawdown również nie są twardą gwarancją straty maksymalnej.

**SIZING:**

`notional_USD = (equity_USD × risk_fraction) / (abs(entry-stop)/entry + expected_round_trip_execution_cost_fraction + expected_adverse_funding_fraction)`

- Przed obliczeniem ilości zweryfikować minimalny notional/lot step/tick size; zaokrąglać w dół.
- Weryfikować margin ratio i dystans do poziomu likwidacji; planowany stop musi mieć znaczący bufor przed likwidacją, po uwzględnieniu wymaganych maintenance margin, zmian mark price i opłat. Jeśli nie — BRAK TRANSAKCJI.
- Zamrozić handel po niezgodności stanu pozycji, historii fill lub ochrony SL.
- Przed live: jawny wybór isolated margin i oddzielny portfel zabezpieczenia, brak automatycznego uzupełniania marginu; weryfikacja waluty collateral i opłat konwersji.

## 5. Model kosztów: niepomijalny

Kraken Pro tier 1: **0,02% maker / 0,05% taker za stronę** (stan na 2026-11-01). Wariant konserwatywny zakłada taker wejście + taker wyjście = **0,10% notional round-trip**. Do tego rzeczywisty spread/slippage i historyczny funding (Kraken perpetual funding jest rozliczany godzinowo / w sposób ciągły zgodnie ze specyfikacją kontraktu), konwersje i opłaty szczególne.

Scenariusze laboratoryjne (**założenia, nie zmierzone spready**):

1. **Bazowy:** 0,10% fees + 0,06% łącznej frikcji wykonania = 0,16% notional/trade + historyczny funding.
2. **Stress:** 0,10% fees + 0,15% łącznej frikcji = 0,25% + funding powiększony zgodnie z konserwatywnym scenariuszem.
3. **Tylko-maker** jako test opcjonalny, przy modelowaniu niepełnych fill, opóźnień i braku realizacji; nie kredytować automatycznie zniżką maker wszystkich zleceń limit.

Przykład wpływu kosztów: przy SL 1,0%, TP 1,5% i round-trip 0,16% notional zysk wygranej = 1,34% notional, strata przegranej = 1,16%; break-even win rate = 1,16/(1,34+1,16)=**46,4%**, jeszcze **przed funding**. Nie używać tego jako prognozy skuteczności strategii.

## 6. Engine i bezpieczeństwo zleceń

1. Stan maszyny: `FLAT -> SIGNAL -> ORDER_PENDING -> PARTIAL_FILL/OPEN -> PROTECTED -> EXIT_PENDING -> FLAT`; każda operacja idempotentna i audytowana.
2. `clientOrderId`/przypisanie identyfikatora po stronie giełdy, potwierdzanie execution przez WebSocket i REST reconciliation, brak ślepych retry po timeout.
3. Stop-market / reduce-only po faktycznym fill; jeśli pozycja nie może zostać chroniona, awaryjne zamykanie zgodnie z runbookiem. Zarówno stop jak i awaryjny close wymagają testu zachowania przy częściowym wykonaniu.
4. Cena aktywacji stopa: dokumentacja Kraken wskazuje mark jako domyślny, dostępne też last/index. Zapis i walidacja rzeczywistego rodzaju aktywacji. Nie wykorzystywać wyłącznie trade OHLC do symulacji stopów aktywowanych mark.
5. Kraken stosuje ograniczenie ochronne wykonania stop-market: zlecenie może zostać wykonane częściowo albo nie wykonać się w całości, jeśli ceny są poza dozwolonym pasmem. Monitor pozycję i residual exposure.
6. **Dead Man's Switch Kraken `cancelallordersafter`** anuluje wszystkie zlecenia po utracie połączenia — może więc anulować także ochronny stop. Na start nie uruchamiać tego mechanizmu bez uprzedniego testu i odrębnego bezpiecznego wzorca ochrony; w zamian wdrożyć własny watchdog/halt + narzędzie awaryjne.
7. Rozdzielić read-only data keys od trading keys; brak withdrawal permission, whitelist IP, secret manager, zasada minimalnych uprawnień.
8. Osobne procesy/monitory dla data integrity, order execution, reconciliation, account equity i alertów. VPS niezależny od komputera użytkownika.
9. Po restartach pełna rekonstrukcja pozycji/SL/pending orders z giełdy **przed** dopuszczeniem nowych wejść.
10. `LIVE_ENABLED=false` domyślnie i bezpośredni ręczny przełącznik z logiem audytu.

## 7. Walidacja: od hipotezy do decyzji GO / NO-GO

### A. Integralność danych

- Preferować co najmniej **3 lata** 1H/4H, obejmujące różne reżimy rynkowe; jeśli Kraken nie udostępnia pełnej historii, rozróżnić dane badawcze innych giełd i dane egzekucji Kraken.
- Konieczna synchronizacja trade OHLC, mark/index, funding, opłat, tick/lot spec. Uzupełnienia luk muszą być jawne; brak forward fill do tworzenia sztucznych sygnałów.
- W każdym backteście zapisywać wersję datasetu, checksum, timezone, data cut-off, wersję kodu i strategii.

### B. Projekt eksperymentu

- Zarejestrować hipotezę A, challenger B, benchmarki i niewielką siatkę wariantów (`Donchian 20/24/30`, `ATR stop 1.5/2/2.5`, `trailing 2.5/3/3.5`), bez masowego przeszukiwania ustawień.
- Podział chronologiczny; walk-forward na kolejnych oknach z **nieruszanym końcowym holdoutem**. Odrębne testy wysokiej, niskiej zmienności, hossy, bessy i trendów bocznych.
- Dokładne modelowanie czasu informacji: sygnał na zamknięciu, wykonanie później, funding według danych dostępnych na moment pozycji, rozliczenie likwidacji/margin.
- Stress tests: podwojony slippage, opóźnienie wejścia, odrzucony stop, częściowe fill, downtime API, nagłe skoki i zmiany spreadu.
- Monte Carlo / block bootstrap ścieżek; szerokie przedziały ufności przy małej liczbie zleceń. Kontrola overfittingu i próby wielokrotnej selekcji.

### C. Kryteria GO dla paper / demo (warunki konieczne, nie dowód trwałej przewagi)

- Raport **net-of-all-costs** dodatni out-of-sample w okresie final holdout, Profit Factor docelowo ≥1,20.
- W stress fees/slippage strategia nie przechodzi w wyraźnie nieakceptowalną stratę; jeśli dodatni wynik nie jest stabilny dla sąsiednich parametrów — NO-GO.
- Drawdown mieści się w zadeklarowanym budżecie; nie jest napędzany przez jeden przypadkowy dzień lub 1–2 trade'y.
- Podać liczbę niezależnych setupów, koncentrację P&L, gross vs net, Sharpe/Sortino, avg trade / R, worst streak, expectancy i ekspozycję czasową.
- Mała próbka jest statystycznie **nierozstrzygająca**, nawet gdy PF >1,20.

### D. Forward testing / LIVE

- Paper 24/7 przynajmniej 8–12 tygodni w celu sprawdzenia procesu; jeśli sygnałów mało, testy przedłużyć. Dodatni paper nie wystarcza do ogłoszenia strategii zyskowną.
- Demo/Exchange test zleceń i scenariuszy awaryjnych, test minimów kontraktu, isolated margin, stop trigger, częściowych fill, reconcile, recovery. Test również zlecenia odrzuconego.
- LIVE tylko po pełnej autoryzacji konta, akceptacji konkretnego instrumentu, podpisaniu checklisty GO i ręcznej decyzji użytkownika. Start risk ≤0,10% equity/trade; minimalny notional może wykluczać niektóre konta.
- Stop skalowania po 1.0% daily loss, 3% weekly i 6% peak drawdown. Wyłączenie LIVE jest obowiązkowe, jeśli połączenie/ochrona pozycji nie jest zweryfikowana.

## 8. Dokumenty i zdarzenia, które bot zapisuje

- Każda świeca/mark, snapshot funding, spread, sygnał i przyczyna jego odrzucenia.
- Strategia, hash kodu, wersja konfiguracji, timestamp UTC, equity snapshot, risk budget, pozycja notional, target SL/exit.
- Ack zlecenia, fill i partial fill, reject reason, exchange order ID, wszystkie fees, funding, real P&L i decyzja reconciliation.
- Log pełnej historii alertów, blokad, restartów i decyzji ręcznych.

## 9. Źródła do ponownej weryfikacji podczas implementacji

- Deprez & Frömmel (2024), badanie reguł BTC i OOS: https://ideas.repec.org/a/eee/reveco/v93y2024ipbp858-874.html
- Kang & Ryu (2026), wolniejsze momentum BTC: https://ideas.repec.org/a/pal/risman/v28y2026i3d10.1057_s41283-026-00234-7.html
- Hudson & Urquhart (2021), brak przewidywalności OOS dla BTC w badanym okresie: https://ideas.repec.org/a/spr/annopr/v297y2021i1d10.1007_s10479-019-03357-1.html
- Bailey et al., PBO: https://scholarworks.wmich.edu/math_pubs/42/
- Kraken Futures fee schedule: https://www.kraken.com/pl/pro/fees
- Kraken EEA cross/isolated margin: https://support.kraken.com/pl/articles/multi-collateral-derivatives-contracts-eea
- Kraken order types i ryzyko SL stop-market: https://support.kraken.com/pl/articles/13944617482900-futures-order-types
- Kraken API charts: https://docs.kraken.com/api/docs/futures-api/charts/candles
- Kraken API analytics/funding: https://docs.kraken.com/api/docs/futures-api/charts/market-analytics
- Kraken DMS: https://docs.kraken.com/api/docs/futures-api/trading/cancel-all-orders-after
- Kraken perpetual contract specs: https://support.kraken.com/in/articles/4844359082772-linear-multi-collateral-derivatives-contract-specifications
- Kraken EEA eligibility: https://support.kraken.com/articles/derivatives-eligibility-requirements-eea

## 10. Decyzja dla rozwoju

**Do implementacji jako pierwsze:** data ingestion + reproducible event-driven backtester + risk ledger + strategy A + test costs/funding + benchmarks. **Nie implementować jako pierwszych:** dashboard live, LLM-autotrading, wielu altcoinów, automatycznej optymalizacji parametrów. Dopiero wyniki OOS i testy awaryjne uzasadnią dalsze kroki.
