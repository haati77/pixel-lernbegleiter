"""
Kinderprofile für Pixel (kinder.json, nicht in Git).

Ein Profil hat einen Namen, die Klasse und weitere Wörter, an denen Pixel das Kind erkennt (Spitznamen,
oder wie die Spracherkennung den Namen schreibt). Welches Kind gerade spricht, steht in einstellungen.json
("kind"). Ein Kind meldet sich per Sprache an: "Ich bin Anna", "Hier ist Anna".

Datenschutz: Namen bleiben auf dem Pi. An Claude geht nur die Klasse, nie der Name. Pixel sagt den Namen
zur Begrüßung laut, bei einer Cloud-Stimme geht er dabei an deren Anbieter (so gewünscht).
"""
import json
import os
import re
from pathlib import Path

from einstellungen import _zahl
from persoenlichkeiten import _woerter, normalisiere

DATEI = Path(__file__).parent / "kinder.json"


def _name(wert):
    if not isinstance(wert, str) or not 1 <= len(wert.strip()) <= 30:
        raise ValueError("Name mit 1 bis 30 Zeichen")
    return wert.strip()


# Klasse 14 = Erwachsene: Hochschulniveau, keine Schlafenszeit, eigenes Kostenlimit
ERWACHSEN = 14

# Feld -> (Standardwert, Prüfung). Klasse 0 = Kindergarten oder Vorschule.
FELDER = {
    "name": ("", _name),
    "klasse": (4, _zahl(0, ERWACHSEN, ganz=True)),
    "woerter": ([], _woerter),
    # Sekunden Stille, bis Pixel die Antwort für fertig hält. 0 = automatisch: Klasse 0 bis 2 bekommt
    # PAUSE_JUENGERE (jüngere Kinder machen beim Sprechen längere Denkpausen), sonst gilt die Einstellung
    "sprechpause": (0.0, _zahl(0, 3)),
}
PAUSE_JUENGERE = 1.6


def klasse_text(klasse):
    """'in die 4. Klasse' bzw. 'in den Kindergarten oder die Vorschule'."""
    if klasse == ERWACHSEN:
        return "erwachsen (Hochschulniveau)"
    return "in den Kindergarten oder die Vorschule" if klasse == 0 else f"in die {klasse}. Klasse"


def ist_erwachsen(kind):
    return bool(kind) and kind["klasse"] == ERWACHSEN


class Kinder:
    def __init__(self, pfad=DATEI):
        self.pfad = Path(pfad)
        self._stand = None
        self.daten = self._lies() if self.pfad.exists() else {}
        self._stand = self._zeit()

    # ------------------------------------------------------------------ Lesen und Schreiben
    def _zeit(self):
        try:
            return os.stat(self.pfad).st_mtime_ns
        except OSError:
            return None

    def _lies(self):
        try:
            roh = json.loads(self.pfad.read_text(encoding="utf-8"))
            if not isinstance(roh, dict):
                raise ValueError("kein JSON-Objekt")
        except (OSError, ValueError) as fehler:
            print(f"  [Kinder] {self.pfad.name} nicht lesbar: {fehler}")
            return getattr(self, "daten", {})
        daten = {}
        for kid, werte in roh.items():
            if not re.fullmatch(r"[a-z0-9_]{1,30}", str(kid)) or not isinstance(werte, dict):
                print(f"  [Kinder] Eintrag '{kid}' ungültig, wird ignoriert")
                continue
            try:
                daten[kid] = {feld: pruefe(werte.get(feld, standard)) for feld, (standard, pruefe) in FELDER.items()}
            except ValueError as fehler:
                print(f"  [Kinder] Eintrag '{kid}' ungültig ({fehler}), wird ignoriert")
        return daten

    def speichere(self):
        hilfsdatei = self.pfad.with_suffix(".tmp")
        try:
            hilfsdatei.write_text(json.dumps(self.daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(hilfsdatei, self.pfad)
            self._stand = self._zeit()
        except OSError as fehler:
            print(f"  [Kinder] Speichern fehlgeschlagen: {fehler}")

    def aenderungen(self):
        """Datei neu lesen, wenn sie geändert wurde (z. B. von der Oberfläche). True bei Änderung."""
        stand = self._zeit()
        if stand == self._stand:
            return False
        self._stand = stand
        alt, self.daten = self.daten, (self._lies() if stand is not None else {})
        return alt != self.daten

    # ------------------------------------------------------------------ Zugriff
    def hole(self, kid):
        return self.daten.get(kid)

    def neu(self, name, klasse):
        """Neues Profil anlegen. Gibt die Kennung zurück. Wirft ValueError (auch bei doppeltem Namen)."""
        name, klasse = FELDER["name"][1](name), FELDER["klasse"][1](klasse)
        if self.finde(name):
            raise ValueError("Diesen Namen gibt es schon.")
        basis = re.sub(r"[^a-z0-9]+", "_", normalisiere(name).replace("ä", "ae").replace("ö", "oe")
                       .replace("ü", "ue").replace("ß", "ss")).strip("_")[:24] or "kind"
        kid, n = basis, 2
        while kid in self.daten:
            kid, n = f"{basis}_{n}", n + 1
        self.daten[kid] = {"name": name, "klasse": klasse, "woerter": [], "sprechpause": 0.0}
        self.speichere()
        return kid

    def setze(self, kid, feld, wert):
        self.daten[kid][feld] = FELDER[feld][1](wert)
        self.speichere()

    def loesche(self, kid):
        if kid in self.daten:
            del self.daten[kid]
            self.speichere()

    def finde(self, wort):
        """Kennung zu einem gesprochenen Namen ("anna", "die anna") oder None."""
        wort = re.sub(r"^(die|der|das)\s+", "", normalisiere(wort))
        for kid, k in self.daten.items():
            if wort == normalisiere(k["name"]) or wort in k["woerter"]:
                return kid
        for kid, k in self.daten.items():  # anders geschrieben, gleicher Klang ("Dominique")
            if klingt_wie(wort, k["name"]) or any(klingt_wie(wort, w) for w in k["woerter"]):
                return kid
        return None


def sprechpause(kind, standard):
    """Sprechpause für dieses Kind: eigener Wert, sonst automatisch nach Klasse, sonst die Einstellung."""
    if not kind:
        return standard
    if kind.get("sprechpause"):
        return kind["sprechpause"]
    return max(standard, PAUSE_JUENGERE) if kind["klasse"] <= 2 else standard


# Klang-Vergleich (Kölner Phonetik): Deepgram schreibt Namen manchmal anders, vor allem mit language=multi
# (Mister Pixel): "Ich bin Yannick" statt Jannik. Nur für Klangcodes ab KLANG_MIN Ziffern,
# kurze Codes sind zu ungenau (Hanna und Anna klingen nach dem Verfahren gleich: "06").
KLANG_MIN = 3


def klang(wort):
    """Kölner Phonetik: 'Jannik' und 'Yannick' haben denselben Code."""
    w = re.sub(r"[^a-z]", "", wort.lower().replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "s"))
    codes = []
    for i, z in enumerate(w):
        vor = w[i - 1] if i else ""
        nach = w[i + 1] if i + 1 < len(w) else ""
        if z in "aeijouy":
            c = "0"
        elif z == "h":
            c = ""
        elif z == "b" or (z == "p" and nach != "h"):
            c = "1"
        elif z in "dt":
            c = "8" if nach in ("c", "s", "z") and nach else "2"
        elif z in "fvw" or z == "p":
            c = "3"
        elif z in "gkq":
            c = "4"
        elif z == "c":
            if i == 0:
                c = "4" if nach and nach in "ahkloqrux" else "8"
            else:
                c = "4" if nach and nach in "ahkoqux" and vor not in ("s", "z") else "8"
        elif z == "x":
            c = "8" if vor in ("c", "k", "q") and vor else "48"
        elif z == "l":
            c = "5"
        elif z in "mn":
            c = "6"
        elif z == "r":
            c = "7"
        else:  # s, z
            c = "8"
        codes.append(c)
    folge = "".join(codes)
    ohne_doppelte = "".join(c for i, c in enumerate(folge) if i == 0 or c != folge[i - 1])
    return ohne_doppelte[:1] + ohne_doppelte[1:].replace("0", "")


def klingt_wie(gesprochen, name):
    code = klang(name)
    return len(code) >= KLANG_MIN and klang(gesprochen) == code


def ohne_namen(text, kinder):
    """Namen und weitere Wörter aller Profile durch [Name] ersetzen, bevor ein Text an Claude geht, auch gleich
    klingende Schreibweisen ("Yannick" für Jannik)."""
    namen = {k["name"] for k in kinder.daten.values()} | {w for k in kinder.daten.values() for w in k["woerter"]}
    for name in sorted(namen, key=len, reverse=True):  # "Benjamin" vor "Ben"
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", "[Name]", text, flags=re.IGNORECASE)
    codes = {klang(n) for n in namen if len(klang(n)) >= KLANG_MIN}
    if codes:
        text = re.sub(r"(?<![\w\[])[A-Za-zÄÖÜäöüß]+(?![\w\]])",
                      lambda t: "[Name]" if klang(t.group()) in codes else t.group(), text)
    return text


# "Ich bin Anna", "Hier ist Anna", "Ich heiße Anna", "Hier spricht Anna" (ganze Äußerung)
_ANMELDUNG = re.compile(r"^(ich bin|hier ist|hier spricht|ich heiße|ich heisse|jetzt ist|jetzt bin ich) (?P<n>.+)$")


def pruefe_anmeldung(text):
    """Gesprochene Bezeichnung bei "Ich bin …", sonst None. Ob es ein bekanntes Kind ist, prüft der Aufrufer
    ("Ich bin müde" ist keine Anmeldung und geht normal an Claude)."""
    treffer = _ANMELDUNG.match(normalisiere(text))
    return treffer.group("n") if treffer else None
