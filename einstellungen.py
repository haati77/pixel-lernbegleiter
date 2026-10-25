"""
Einstellungsdatei für Pixel (einstellungen.json).

Die Datei wird später von der Handy-Oberfläche geschrieben und von gespraech.py vor jeder Frage
gelesen. Übernommen werden nur Werte, die sich in der Datei geändert haben. Ungültige Werte werden
mit einer Meldung ignoriert, dann gilt der bisherige Wert weiter.
"""
import json
import os
import re
from pathlib import Path

DATEI = Path(__file__).parent / "einstellungen.json"


def _zahl(von, bis, ganz=False):
    def pruefe(wert):
        if isinstance(wert, bool) or not isinstance(wert, (int, float)):
            raise ValueError("keine Zahl")
        if ganz and int(wert) != wert:
            raise ValueError("keine ganze Zahl")
        if not von <= wert <= bis:
            raise ValueError(f"nicht zwischen {von} und {bis}")
        return int(wert) if ganz else float(wert)
    return pruefe


def _ja_nein(wert):
    if not isinstance(wert, bool):
        raise ValueError("nicht ja oder nein")
    return wert


def _prompt(wert):
    """Anweisungen an Claude: beliebiger Text, leer = Standard aus prompts.py."""
    if not isinstance(wert, str):
        raise ValueError("kein Text")
    wert = wert.strip()
    if len(wert) > 10_000:
        raise ValueError("länger als 10.000 Zeichen")
    if wert and len(wert) < 20:
        raise ValueError("zu kurz, mindestens 20 Zeichen oder leer für den Standard")
    return wert


def _text(muster, beispiel):
    def pruefe(wert):
        if not isinstance(wert, str) or not re.fullmatch(muster, wert.strip()):
            raise ValueError(f"Format wie {beispiel}")
        return wert.strip()
    return pruefe


# Name -> (Standardwert, Prüfung). Die Standardwerte entsprechen den bisherigen Startoptionen.
FELDER = {
    # Aktive Persönlichkeit (persoenlichkeiten.json). Modell, Stimme, Lautstärke und Prompts gehören dorthin.
    "persoenlichkeit": ("pixel", _text(r"[a-z0-9_]{1,30}", "pixel")),
    # Aktives Kind (kinder.json), leer = keins. Bleibt, bis sich ein anderes Kind meldet ("Ich bin …").
    "kind": ("", _text(r"|[a-z0-9_]{1,30}", "anna oder leer")),
    "pause": (1.2, _zahl(0.5, 3.0)),
    "folge": (6.0, _zahl(0, 30)),
    "ww_schwelle": (0.5, _zahl(0.05, 0.95)),
    # Name eines Modells: eigenes in wakewords/ (hey_pixel) oder mitgeliefert (hey_mycroft)
    "wakeword": ("hey_pixel", _text(r"[a-z0-9_]+", "hey_pixel")),
    "schlafenszeit": ("20:00-07:00", _text(r"aus|\d{1,2}:\d{2}-\d{1,2}:\d{2}", "20:00-07:00 oder aus")),
    "tageslimit_cent": (50.0, _zahl(0, 10_000)),
    "max_fragen": (0, _zahl(0, 10_000, ganz=True)),
    # Erwachsene (Profil-Klasse 14): eigenes Kostenlimit, keine Schlafenszeit, keine Fragengrenze
    "tageslimit_cent_erwachsene": (50.0, _zahl(0, 10_000)),
    # Bis wann während der Schlafenszeit noch eine Gute-Nacht-Geschichte erlaubt ist ("aus" = keine Ausnahme)
    "geschichte_bis": ("20:30", _text(r"aus|\d{1,2}:\d{2}", "20:30 oder aus")),
    # Tagesziel: so viele richtige Aufgaben am Tag (alle Fächer, 0 = aus), Pixel gratuliert beim Erreichen
    "tagesziel": (15, _zahl(0, 200, ganz=True)),
}
# Früher hier, seit den Persönlichkeiten dort: werden beim Lesen beiseitegelegt und nach "pixel" übernommen
UMGEZOGEN = {"modell", "stimme", "lautstaerke", "modell_geschichte", "stimme_geschichte", "system_prompt",
             "geschichten_prompt"}


class Einstellungen:
    def __init__(self, pfad=DATEI):
        self.pfad = Path(pfad)
        self.werte = {name: standard for name, (standard, _) in FELDER.items()}
        self._stand = None  # Änderungszeit der Datei beim letzten Lesen
        self.umgezogen = {}  # alte Werte für die Persönlichkeit Pixel, siehe UMGEZOGEN
        if self.pfad.exists():
            self.werte.update(self._lies())
            self._stand = self._zeit()
        else:
            self.speichere()
            print(f"Einstellungsdatei angelegt: {self.pfad}")

    def __getitem__(self, name):
        return self.werte[name]

    def _zeit(self):
        try:
            return os.stat(self.pfad).st_mtime_ns
        except OSError:
            return None

    def _lies(self):
        """Gültige Werte aus der Datei. Ungültige und unbekannte Werte werden gemeldet und ausgelassen."""
        try:
            roh = json.loads(self.pfad.read_text(encoding="utf-8"))
            if not isinstance(roh, dict):
                raise ValueError("kein JSON-Objekt")
        except (OSError, ValueError) as fehler:
            print(f"  [Einstellungen] {self.pfad.name} nicht lesbar: {fehler}")
            return {}
        gueltig = {}
        for name, wert in roh.items():
            if name in UMGEZOGEN:
                self.umgezogen[name] = wert
                continue
            if name not in FELDER:
                print(f"  [Einstellungen] unbekannter Eintrag '{name}' wird ignoriert")
                continue
            try:
                gueltig[name] = FELDER[name][1](wert)
            except ValueError as fehler:
                print(f"  [Einstellungen] {name} = {wert!r} ungültig ({fehler}), bleibt {self.werte[name]!r}")
        return gueltig

    def aenderungen(self):
        """Prüft, ob die Datei geändert wurde. Gibt die geänderten gültigen Werte zurück ({} wenn nichts)."""
        stand = self._zeit()
        if stand is None or stand == self._stand:
            return {}
        self._stand = stand
        neu = {name: wert for name, wert in self._lies().items() if wert != self.werte[name]}
        self.werte.update(neu)
        return neu

    def entferne_umgezogene(self):
        """Nach dem Umzug in die Persönlichkeiten die alten Einträge aus der Datei entfernen."""
        if self.umgezogen:
            self.speichere()  # schreibt nur die Felder aus FELDER
            self.umgezogen = {}

    def setze(self, name, wert):
        """Wert ändern und sofort speichern (z. B. nach dem Sprachbefehl 'lauter')."""
        self.werte[name] = FELDER[name][1](wert)
        self.speichere()

    def speichere(self):
        """Atomar schreiben: erst in eine Hilfsdatei, dann ersetzen. So liest niemand eine halbe Datei."""
        hilfsdatei = self.pfad.with_suffix(".tmp")
        try:
            hilfsdatei.write_text(json.dumps(self.werte, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(hilfsdatei, self.pfad)
            self._stand = self._zeit()
        except OSError as fehler:
            print(f"  [Einstellungen] Speichern fehlgeschlagen: {fehler}")
