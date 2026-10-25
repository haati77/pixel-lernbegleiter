# Pixel – der sprechende Lernbegleiter (Windows-Version)

Pixel ist ein sprechender Lernbegleiter für Grundschulkinder. Auf „Hey Pixel“ hört er zu, beantwortet Fragen in kurzen, kindgerechten Sätzen und übt Englisch, Mathe, Deutsch und Sachkunde nach dem bayerischen Lehrplan (LehrplanPLUS Grundschule). Die Eltern stellen alles über eine Seite auf dem Handy ein.

Diese Version läuft auf einem normalen **Windows-Laptop** mit eingebautem Mikrofon und Lautsprecher, ohne zusätzliche Hardware. Kosten entstehen nur für die Cloud-Dienste (Spracherkennung und KI), mit einem einstellbaren Tageslimit.

> Pixel ist ein privates Familienprojekt. Eine Beitragsreihe mit allen Problemen und Lösungen erscheint auf finanzrechner.trade in der Rubrik Technik.

## Was Pixel kann

- **Fragen beantworten** in zwei bis drei einfachen Sätzen. Bei Hausaufgaben gibt er Denkanstöße statt Lösungen.
- **Englisch üben** mit britischer Aussprache: Vokabeln, Nachsprechen, Rätsel und kleine Rollenspiele nach dem verbindlichen Wortschatz der Grundschule. Eine Lernkartei fragt Wörter nach 1, 3, 7 und 21 Tagen wieder ab.
- **Mathe, Deutsch, Sachkunde:** Das Kind wählt Thema und Schwierigkeit selbst („Ich will Malrechnen“, „Mach es schwerer“), Pixel schlägt Themen der Klasse vor und merkt sich den Stand. Einmaleins mit Karteikasten.
- **Zuhören üben:** Pixel liest einen Text vor und stellt fünf Fragen, wie bei der Zuhörprobe.
- **Gute-Nacht-Geschichten** zum Wunschthema.
- **Belohnung:** Sticker-Album mit 60 Tieren, Serien, Tagesrekord und Tagesziel.
- **Persönlichkeiten:** Pirat, Forscher, Mister Pixel (Englisch), Deutsch-Pixel, Sachkunde-Pixel, Zuhör-Pixel und Schlafmütze, jede mit eigener Stimme und eigenen Regeln. Wechsel per Sprache („Sei ein Pirat“).
- **Für Eltern:** Handy-Seite im Heimnetz mit Kinderprofilen, Lernstand je Fach, Wochenbericht, Schlafenszeit, Kostenlimit und Auswertung.

## So funktioniert es

```
Mikrofon → Wake Word „Hey Pixel“ (lokal) → Sprechpause erkennen (lokal) → Deepgram (Spracherkennung)
         → Claude (Antwort) → Stimme (Piper lokal oder Google) → Lautsprecher
```

Bis „Hey Pixel“ geht nichts ins Netz. Danach geht nur die Aufnahme bis zur Sprechpause an Deepgram und nur Text an Claude. Namen der Kinder ersetzt Pixel vorher durch `[Name]`, Claude erfährt nur die Klasse.

## Was du brauchst

- Windows 10 oder 11 mit Mikrofon und Lautsprecher (ein Laptop hat beides; ein Headset versteht Kinder oft besser)
- Python von [python.org](https://www.python.org/downloads/), getestet mit 3.13 und 3.14 (bei der Installation „Add python.exe to PATH“ anhaken)
- Ein Konto mit API-Schlüssel bei **Anthropic** für Claude ([platform.claude.com](https://platform.claude.com)), mit Guthaben
- Ein Konto mit API-Schlüssel bei **Deepgram** für die Spracherkennung ([deepgram.com](https://deepgram.com))
- Optional ein API-Schlüssel für **Google Cloud Text-to-Speech** (schönere Stimmen, Freimenge 1 Mio. Zeichen pro Monat). Ohne ihn sprechen alle Persönlichkeiten mit der lokalen Stimme Piper.

## Installation

In PowerShell im Ordner des Projekts:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### API-Schlüssel hinterlegen

Schlüssel gehören nur in Umgebungsvariablen, nie in Dateien. Einmalig in PowerShell (der Schlüssel wird nicht angezeigt), danach ein neues Fenster öffnen:

```powershell
[Environment]::SetEnvironmentVariable("PIDOG_ANTHROPIC_API_KEY", (Read-Host "Claude-Schlüssel"), "User")
[Environment]::SetEnvironmentVariable("DEEPGRAM_API_KEY", (Read-Host "Deepgram-Schlüssel"), "User")
[Environment]::SetEnvironmentVariable("GOOGLE_TTS_API_KEY", (Read-Host "Google-Schlüssel (optional)"), "User")
[Environment]::SetEnvironmentVariable("PIDOG_ELTERN_PIN", (Read-Host "Eltern-PIN (optional)"), "User")
```

`PIDOG_ANTHROPIC_API_KEY` heißt bewusst nicht `ANTHROPIC_API_KEY`, damit andere Programme den Schlüssel nicht mitbenutzen (`ANTHROPIC_API_KEY` wird als Ersatz trotzdem gelesen).

## Starten

Doppelklick auf **`starte.cmd`**. Das startet das Gespräch und die Handy-Seite zusammen in einem Fenster, Strg+C beendet beides. Beim ersten Start lädt Pixel die Stimme Kerstin (ca. 63 MB) herunter und legt `einstellungen.json` und `persoenlichkeiten.json` an.

Dann „**Hey Pixel**“ sagen, auf „Ja?“ warten und sprechen. Ein aufsteigender Ton nach der Antwort heißt: Du kannst direkt weiterreden. Ein absteigender Ton heißt: Das Gespräch ist zu Ende.

Die Adresse der Handy-Seite steht im Fenster (z. B. `http://192.168.x.y:8080`). Auf dem Handy im selben WLAN öffnen. Beim ersten Start fragt Windows nach der Firewall: Zugriff nur für **private Netzwerke** erlauben. Ohne Eltern-PIN ist die Seite für jeden im Heimnetz offen.

```powershell
python starte.py --nur-lokal            # Handy-Seite nur auf diesem Rechner
python starte.py -- --modus taste       # Enter statt Wake Word (alles nach -- geht an gespraech.py)
python gespraech.py --debug             # Wake-Word-Werte anzeigen, hilft beim Einstellen
python sprachtest.py --geraete          # Mikrofone und Lautsprecher anzeigen
python gespraech.py --mikrofon Headset  # bestimmtes Gerät (Nummer oder Teil des Namens)
```

## Erste Schritte auf dem Handy

1. **Profile:** je Kind ein Profil mit Name und Klasse anlegen. Die Kinder melden sich mit „Ich bin Anna“ an. Nach 30 Minuten ohne Gespräch oder mit „Tschüss“ ist niemand mehr angemeldet.
2. **Lernen:** je Kind und Fach Thema, Schwierigkeit und Stand, Sticker-Album und Tagesziel.
3. **Persönlichkeiten:** alle bearbeiten, Stimmen probehören („Anhören“), eigene als Kopie anlegen.
4. **Einstellungen:** Wake Word und Empfindlichkeit, Sprechpause, Schlafenszeit (Standard 20:00 bis 07:00) und Tageslimit für die Kosten (Standard 50 US-Cent).
5. **Anleitung:** alle Sprachbefehle zum Nachlesen.

## Wichtige Sprachbefehle

| Sagen | Wirkung |
|---|---|
| „Ich bin Anna“, „Hier ist …“ | Kind anmelden |
| „Ich will Mathe üben“, „Lass uns Englisch machen“ | passende Lern-Persönlichkeit legt los |
| „Mach es schwerer“ / „leichter“ | Schwierigkeit ändern |
| „Sei ein Pirat“, „Sei wieder normal“ | Persönlichkeit wechseln |
| „Erzähl mir eine Gute-Nacht-Geschichte über …“ | ruhige Geschichte, danach ist Schluss |
| „Wie viele Sticker habe ich?“ | Pixel erzählt vom Album |
| „Tschüss“ | Gespräch beenden und abmelden (das Programm läuft weiter) |
| „Pause“, „Sei still“ | Gespräch sofort beenden |
| „Nochmal“, „Lauter“, „Leiser“ | letzte Antwort wiederholen, Lautstärke ändern |
| „Klugmodus“ / „Schnellmodus“ | Claude Sonnet (genauer, teurer) oder Haiku (schnell, günstig) |

## Kosten

Pixel schreibt zu jeder Anfrage die Kosten in `protokoll/kosten.csv` (nur Zahlen, keine Texte), die Handy-Seite zeigt sie unter „Auswertung“. Gemessen mit zwei Kindern im Oktober 2026: eine Antwort von Claude Haiku kostete rund 0,04 US-Cent, von Claude Sonnet rund 0,5 US-Cent, eine Spracherkennung rund 0,02 US-Cent. Lerntage mit überwiegend Sonnet kosteten meist 30 bis 45 US-Cent. Ist das Tageslimit erreicht, macht Pixel Pause. Die Preise im Programm (`PREISE`, `DEEPGRAM_PREIS_MIN` in `gespraech.py`) sind Schätzungen nach den Preisseiten; maßgeblich ist die Abrechnung der Anbieter.

## Datenschutz

- **Bleibt auf dem Rechner:** Mikrofon bis „Hey Pixel“, Sprechpausen-Erkennung, Profile, Lernstand, Sticker und Protokolle.
- **Deepgram:** nur die Aufnahme zwischen Sprechbeginn und Sprechpause.
- **Anthropic (Claude):** nur Text, Namen als `[Name]`, dazu die Klasse.
- **Google (nur mit Google-Stimme):** die Antworttexte zum Vorlesen.

Die Regeln für Kinder stehen in den Anweisungen jeder Persönlichkeit: Pixel fragt nie nach Namen, Alter oder Adresse, verweist bei Gefahr oder Kummer an die Eltern und antwortet in der Schlafenszeit nicht.

## Dateien

| Datei | Inhalt |
|---|---|
| `gespraech.py` | Hauptprogramm: Wake Word, Spracherkennung, Claude, Sprecher, Befehle, Lernen |
| `hoeren.py` | Wake Word (openWakeWord) und Sprechpausen-Erkennung (Silero VAD) |
| `stimmen.py` | Stimmen: Piper (lokal), Google Cloud TTS, Deepgram Aura |
| `oberflaeche.py`, `oberflaeche.html` | Handy-Seite (nur Python-Standardbibliothek, Port 8080) |
| `starte.py`, `starte.cmd` | Gespräch und Handy-Seite zusammen starten |
| `prompts.py`, `persoenlichkeiten.py` | Anweisungen an Claude und die Persönlichkeiten |
| `kinder.py`, `lernkartei.py`, `lernthemen.py`, `einmaleins.py` | Profile, Englisch-Lernkartei, Lernpläne Mathe/Deutsch/HSU, Einmaleins |
| `sticker.py`, `tagebuch.py` | Sticker-Album, Wochenbericht und Tagesziel |
| `lernplan_englisch.json`, `baue_lernplan.py` | Englisch-Wortschatz (erzeugt mit dem Skript, dort ändern) |
| `sprachtest.py` | Hilfsprogramm: Geräte anzeigen, Stimmen und Spracherkennung vergleichen |
| `wakewords/hey_pixel.onnx` | eigenes Wake-Word-Modell „Hey Pixel“ |

Daten der Familie (`einstellungen.json`, `persoenlichkeiten.json`, `kinder.json`, `lernstand/`, `sticker/`, `protokoll/`) liegen nur lokal und stehen in `.gitignore`.

Für den Vergleich mit lokaler Spracherkennung (`python sprachtest.py --vergleich small deepgram`) zusätzlich `pip install faster-whisper`.

## Lizenz

Der Programmcode steht unter der **GNU General Public License v3.0** (siehe [LICENSE](LICENSE)), passend zur Sprachausgabe Piper. Für das Wake-Word-Modell, die Stimmen und den Lernplan gelten eigene Bedingungen, siehe [LIZENZEN.md](LIZENZEN.md). Insbesondere ist das Wake-Word-Modell **nur für nicht kommerzielle Zwecke** freigegeben.

Keine Gewähr: Pixel ersetzt keine Aufsicht. Prüft die Antworten und Einstellungen selbst, bevor Kinder allein mit ihm sprechen.
