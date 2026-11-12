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

## NEU: SwingPilot Options Evolution (Paper-only)

**Das Dashboard zeigt jetzt ausschliesslich Optionsbots.** Der frühere Aktien-Paper-Test ist unter `docs/legacy.html` archiviert. Der zuvor geplante Aktienhandel wurde im GitHub-Workflow durch die Options-Engine ersetzt; es werden keine neuen Aktienorders generiert.

### Einmalig einrichten – zwei GitHub Actions Secrets

1. Erstelle einen Optionsdaten-API-Schlüssel bei [MarketData.app](https://www.marketdata.app/). Die Historical/EOD Options Chain und Option Quotes API ist nötig; der Umfang und Preis richten sich nach dem Datenabonnement.
2. Im GitHub-Repository zu **Settings → Secrets and variables → Actions** gehen, **New repository secret** wählen und als `MARKETDATA_TOKEN` den Schlüssel speichern. **Nicht in ein File oder in den Chat kopieren.**
3. `TWELVEDATA_API_KEY` muss weiterhin als GitHub Secret vorhanden sein (historische Schlusskurse der Basiswerte und USD/CHF).
4. **Actions → SwingPilot Options Evolution (Paper) → Run workflow** starten und den Lauf prüfen.
5. Im [Options-Dashboard](https://lorisbuercher-png.github.io/trading/) die aktuelle Datenzeit und Warnungen kontrollieren. Ohne API-Zugang werden **keine Orders** erfunden. Der Workflow zeigt `setup_required` oder `attention`.

### Handelsregeln

- Fünf virtuelle Portfolios à CHF 2’000, ausschliesslich gekaufte US-Calls und US-Puts (Standardkontrakt mit 100 Anteilen), nicht Aktien.
- Beobachtete Basiswerte: SPY, QQQ, AAPL, MSFT, NVDA. Andere Titel folgen nur nach Prüfung der Datenqualität.
- Maximal **ein offener Kontrakt pro Bot**, maximal **30 %** des aktuellen Portfoliowerts an neuer Prämie plus Gebühren und mindestens **50 %** Liquidität beim Einstieg.
- Standardoptionen, ungefähr 20–65 Tage bis Verfall, OI und Spread geprüft. Beim Kauf mindestens 10 Resttage; keine 0DTE- oder ungedeckten Optionen.
- Regelbasierte Alpha/Hunter/Shield/Scout/Nova-Signale nutzen abgeschlossene Underlying-Tageskerzen. Ein Signal erzeugt **nur eine vorgemerkte Order**. Eine Ausführung wird erst mit dem Geld-/Briefkurs des **folgenden Handelstags** gebucht. Fehlende oder veraltete Daten blockieren die Ausführung.
- Long Options werden für die Depotbewertung zum Geldkurs markiert. Verkauf wird spätestens ab ungefähr 10 Tagen bis zum Ablauf vorgemerkt, ist jedoch nur bei neuem handelbaren Schlusskurs ausführbar. **Keine Ausübung oder Zuteilung** ist implementiert; fehlende Kurse nahe oder nach Verfall führen zur Warnung und zu einer Sperre der betroffenen Strategie.
- Die automatische Evolution erfordert Mindestlaufzeit und Verlustgrenzen. Das Restkapital wird von der nächsten Generation übernommen. **Dies ist regelbasierte Optimierung, noch kein trainierendes KI-Modell.**
- Vergleich und Backtesting dürfen die simulierten Folgetagsausführungen nicht mit real ausführbaren Preisen verwechseln; verzögerte EOD-Daten und Tagesendkurse können nicht garantieren, dass Bid/Ask-Preise am Schlusskurs tatsächlich handelbar waren.
- Start des Options-Experiments: 11.11.2026 mit frischen CHF 10’000 virtuellem Kapital. Das historische Aktien-Paper-Portfolio wird **nicht** mitgerechnet.

### Automatischer Ablauf

GitHub Actions läuft **Dienstag bis Samstag 07:40 UTC** (nach dem vorherigen US-Handelstag). Der Runner versucht bis zu drei noch nicht verarbeitete Wochentage geordnet nachzuholen. US-Börsenfeiertage und Datenverzögerungen werden **nicht übersprungen**, sondern bei fehlender Datenlage zur Prüfung markiert. Das Dashboard zeigt Fehler und die letzte verarbeitete Sitzung; es wird nur der Options-Status `docs/data/options.json` geschrieben.
