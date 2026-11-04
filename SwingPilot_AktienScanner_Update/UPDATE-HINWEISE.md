# SwingPilot — Aktien-Scanner Update (04.11.2026)

## Was neu ist

- Erweiterung der Watchlist von 6 auf 50 Aktien (USA und Schweiz).
- Täglich bis zu **32 Symbole** prüfen; andere Titel kommen in den nächsten Läufen dran.
- Bereits gehaltene Aktien werden bei jedem Lauf zuerst geprüft, damit Verkaufssignale nicht wegen der Rotation übersprungen werden.
- Minimal 9 Sekunden Abstand pro API-Abfrage, um die Basic-Begrenzung von Twelve Data von 8 Credits/Minute nicht zu überschreiten.
- 1 simulierter Kauf oder Verkauf je Börsensitzung, max. 35 % des Depotwerts pro neuer Position, 10 % Cashreserve, keine Hebel/Shorts.
- Prüfung erst nach abgeschlossenem US-Handel: GitHub Actions Dienstag–Samstag, 03:25 UTC.
- Anzahl geprüfter Titel und Datenfehler in `docs/data/state.json` unter `scan`.

## Wichtig: keine Vollmarkt-Abdeckung

**50 Aktien sind eine Startliste, keine Abdeckung aller Börsenwerte.** Mit kostenlosem Twelve Data kann der Bot technisch nicht jeden weltweit handelbaren Titel täglich prüfen. Die Liste ist in `config.json` erweiterbar, es gelten jedoch Datenzugang, Markt-/Landesabdeckung und API-Kontingent. Schweizer SIX-Titel können je nach Datenabo weiterhin nicht verfügbar sein. Bei fehlenden Daten wird nicht gehandelt.

## Installation in bestehendes GitHub-Repository

Repository: `lorisbuercher-png/trading`.

Ersetze die folgenden drei **gleichnamigen** Dateien im Branch `main` (Pfad beibehalten):

1. `config.json`
2. `bot/trader.py`
3. `.github/workflows/paper-trade.yml`

**Nicht** `docs/data/state.json` oder `state.json` ersetzen! Darin liegen die bisherigen simulierten Trades und das Depot. Die vorhandene `docs/index.html` bleibt unverändert.

Für GitHub-Weboberfläche: Im Repository die jeweilige Datei öffnen, mit dem Stiftsymbol bearbeiten, vollständigen neuen Inhalt einfügen und `Commit changes` wählen. Die Datei `tests/test_scanner.py` ist optional und prüft die Scannerlogik offline.

Danach unter **Actions → SwingPilot Paper Trading → Run workflow** den Testlauf starten. Das Ergebnis steht nach dem Lauf unter `docs/data/state.json` und im bestehenden GitHub-Pages-Dashboard. Falls ein Lauf keine gültigen Daten findet, tätigt er keine simulierte Order.

## Sicherheit und Grenzen

- Nur simulierte Trades, keine Anbindung an Swissquote, kein echtes Kapital.
- Kurse: Twelve Data, nicht Swissquote. Intraday-Börsenhandel wird nicht simuliert; EOD-Ausführungen sind Näherungen.
- Aktuell regelbasierte SMA-/RSI-/Momentum-Heuristik, **keine KI mit eigenständigem Marktwissen**.
- Gebühren nur modellierte Beispielwerte; Steuer- und Slippage-Effekte nicht vollständig enthalten.
- Datenlizenz und Anzeige auf einer öffentlichen GitHub-Pages-Seite müssen für die gewählte Twelve-Data-Lizenz separat geprüft werden.
