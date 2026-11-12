# SwingPilot — 30-Tage Paper-Trading (03.11.–03.12.2026)

**Reine Simulation.** Keine Swissquote-Kontoverbindung, keine echten Broker-Orders, keine Gelder.

## In GitHub starten
1. Neues **separates** Repository `swingpilot-demo` erstellen (bevorzugt privat; für GitHub Pages können je nach Plan Einschränkungen gelten).
2. Alle Dateien **inklusive `.github/workflows/paper-trade.yml`** in den Standardbranch `main` hochladen.
3. API-Key von [Twelve Data](https://twelvedata.com/) erstellen und unter **Settings → Secrets and variables → Actions → New repository secret** als `TWELVEDATA_API_KEY` speichern. **Niemals ins Repository schreiben.** Die Verfügbarkeit von SIX-Symbolen hängt vom Datentarif ab.
4. Unter **Actions → SwingPilot Paper Trading → Run workflow** den ersten Test auslösen. Bei fehlenden Daten wird nicht gehandelt.
5. Für statisches Dashboard: **Settings → Pages → Deploy from a branch → main → /docs**. Danach liefert GitHub die tatsächliche Pages-URL.
6. Actions läuft an Werktagen um **23:47 UTC** (nach US-Tagesschluss, nicht intraday) und schreibt simulierte Depotsnapshots. GitHub kann geplante Jobs verzögern oder ausfallen lassen; im Dashboard Daten-Zeitstempel prüfen.

## Simulationsregeln
- Startkapital CHF 10'000.00 **als reines Bargeld**, nicht mit den echten Beständen.
- Handelsuniversum ANET, CB, HOLN, NOVN, ABBN, MSFT. Verfügbarkeit anhand des Datenproviders prüfen.
- Ein Papiertrade pro Handelssitzung, max. 35% NAV pro neue Position, mindestens 10% Liquidität, keine Hebel/Shorts.
- Signale aus **vorhergehendem abgeschlossenem Tageskurs**; simulierte Ausführung auf **nächstem verfügbaren Tages-Schlusskurs** (kein Nachweis einer tatsächlich ausführbaren Order; Tageskurs-Approximation).
- Für USD CHF-Währungsumrechnung auf Basis USD/CHF vom Datenprovider; Gebühren modelliert: CHF 4.80 US/CHF 5 SIX plus 0.5% angenommene USD-Umrechnung. **Keine verbindlichen Swissquote-Gebühren.** Dies ist kein realistisch vollständiger Intraday-Backtest.
- Strategie: SMA20 > SMA50, Kurs > SMA20, RSI14 43–72 und 5-Tage-Momentum positiv. Exit unter SMA20 oder RSI >=79. Einfache heuristische Strategie, **keine lernende KI**.
- Keine Handelsgarantie; an vielen Tagen keine Orders. Bei fehlenden Daten **keine Orders**.
- Grundlogik ist öffentlich einsehbar. Repository nicht mit echten Kontosalden, personenbezogenen Daten, Tokens oder Secrets befüllen.

## Sicherheitsstand
- Kein Konto-Login, keine Swissquote API, kein Echtgeldmodus im Code.
- Für Produktion: Datenlizenz, Kursqualitätsüberwachung, Brokerautorisierung, serverseitige Auditlogs, unveränderliche Transaktionsjournale, stärkere Risikosteuerung und unabhängige Prüfung nötig.

## SwingPilot Evolution (neue 5-Bot-Simulation)

- Öffne dieselbe Dashboard-Seite und scrolle zu **Evolution · 5 Bots**.
- 5 voneinander getrennte virtuelle Depots zu je CHF 2’000: Alpha (Momentum), Hunter (Ausbruch), Shield (defensiv), Scout (Trendfolge), Nova (adaptiv).
- Separater State unter `docs/data/evolution.json` mit fünf Portfolios, Rangliste, Orders und einem dauerhaften Archiv ausgeschiedener Generationen. Die alte 30-Tage-Simulation bleibt als Vergleich erhalten und wird **nicht** zum neuen Kapital hinzugerechnet.
- Aus einer Strategie wird nur nach **mindestens 15 Handelstagen**, mehreren abgeschlossenen Trades und deutlichen Verlusten/Drawdowns eine neue Generation. Bei extremen Verlusten kann nach 20 Handelstagen ebenfalls ein Wechsel erfolgen. Bei fehlendem Kurs für eine gehaltene Aktie ist eine Eliminierung blockiert.
- Der Nachfolger erbt **nur das Restkapital**. Parameter werden regelbasiert innerhalb begrenzter Schwellen mutiert und können einen Wert eines erfolgreicheren Bots übernehmen. Dies ist ein Evolutionsexperiment, **kein nachweislich profitables trainiertes KI-Modell**.
- Keine weiteren Datenprovider-API-Aufrufe: Der Evolution-Teil benutzt den vorhandenen rotierenden Tageskurs-Scanner und bevorzugt gehaltene Aktien.
- Modellannahme: Signale aus dem Vortag, Ausführung zum Schlusskurs des nächsten verfügbaren Handelstags, Gebühren und FX-Aufschläge simuliert. Kein Intraday-Trading, kein echtes Orderrouting. Unvollständige Kursdaten blockieren betroffene Orders.
- Die bisherige 30-Tage-Strategie stoppt gemäss ihrem Enddatum; die Evolution läuft auch danach weiter. Jeder GitHub-Actions-Durchlauf prüft vor Trades die Evolution-Unit-Tests.
