"""
Einmaleins-Karteikasten je Kind (lernstand/<kind>_einmaleins.json, nicht in Git).

Der Lehrplan verlangt, das kleine Einmaleins und die Umkehraufgaben zu automatisieren. Dafür ist ein Karteikasten
besser als ein Thema: Jede Aufgabe ist eine eigene Karte ("7x8" mal, "56:7" geteilt), mit denselben Pausen wie die
Englisch-Lernkartei (lernkartei.INTERVALL_TAGE). Nur fällige Karten rücken nach "richtig" ein Fach auf, falsch
geht zurück in Fach 1 und kommt heute noch einmal.

Er gilt, wenn das Kind in Mathe eines der Themen in THEMEN übt. Welche Aufgaben dran sind, bekommt Claude als Notiz
an der Äußerung des Kindes (nicht im System-Prompt, sonst wäre der Cache bei jeder Frage weg). Claude markiert die
gestellte Aufgabe mit <aufgabe>7x8</aufgabe> bzw. <aufgabe>56:7</aufgabe>.
"""
import datetime
import json
import os
import random
import time
from pathlib import Path

from lernkartei import GEKONNT_AB, INTERVALL_TAGE, SPERRE_S

ORDNER = Path(__file__).parent / "lernstand"
# Thema in lernthemen.py -> welche Karten
THEMEN = {"m2_einmaleins_kern": "kern", "m2_einmaleins": "mal", "m3_einmaleins": "mal", "m2_teilen": "geteilt"}
MAX_FAELLIG = 5
MAX_NEU = 3
MAX_NEU_PRO_TAG = 15


def alle_karten(art):
    """Kennungen der Karten: 'kern' = Reihen 1, 2, 5, 10 und Quadrataufgaben, 'mal' = alle 100, 'geteilt' = 56:7."""
    karten = []
    for a in range(1, 11):
        for b in range(1, 11):
            if art == "kern" and not (b in (1, 2, 5, 10) or a in (1, 2, 5, 10) or a == b):
                continue
            karten.append(f"{a * b}:{a}" if art == "geteilt" else f"{a}x{b}")
    return karten


def sprechen(kennung):
    """'7x8' -> '7 mal 8', '56:7' -> '56 geteilt durch 7' (Ziffern liest die Stimme richtig)."""
    if "x" in kennung:
        a, b = kennung.split("x")
        return f"{a} mal {b}"
    a, b = kennung.split(":")
    return f"{a} geteilt durch {b}"


def ergebnis(kennung):
    if "x" in kennung:
        a, b = kennung.split("x")
        return int(a) * int(b)
    a, b = kennung.split(":")
    return int(a) // int(b)


class Kartei:
    def __init__(self, kind, ordner=ORDNER):
        self.pfad = Path(ordner) / f"{kind}_einmaleins.json"
        daten = {}
        if self.pfad.exists():
            try:
                daten = json.loads(self.pfad.read_text(encoding="utf-8"))
            except (OSError, ValueError) as fehler:
                print(f"  [Einmaleins] {self.pfad.name} nicht lesbar: {fehler}")
        gueltig = set(alle_karten("mal")) | set(alle_karten("geteilt"))
        self.karten = {k: v for k, v in (daten.get("karten") or {}).items() if k in gueltig}

    def speichere(self):
        self.pfad.parent.mkdir(exist_ok=True)
        hilfsdatei = self.pfad.with_suffix(".tmp")
        hilfsdatei.write_text(json.dumps({"karten": self.karten}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(hilfsdatei, self.pfad)

    def auswahl(self, art, heute=None, jetzt=None):
        """(fällige, neue) Kennungen für die nächsten Aufgaben."""
        heute = (heute or datetime.date.today()).isoformat()
        jetzt = jetzt or time.time()
        moegliche = alle_karten(art)
        faellig = [k for k in moegliche if k in self.karten and self.karten[k]["faellig"] <= heute
                   and jetzt - self.karten[k].get("zuletzt_s", 0) >= SPERRE_S]
        faellig.sort(key=lambda k: (self.karten[k]["fach"], self.karten[k]["faellig"]))
        heute_neu = sum(1 for c in self.karten.values() if c.get("seit") == heute)
        frei = max(0, min(MAX_NEU, MAX_NEU_PRO_TAG - heute_neu))
        neue = [k for k in moegliche if k not in self.karten]
        random.shuffle(neue)  # nicht immer 1 mal 1 zuerst
        return faellig[:MAX_FAELLIG], neue[:frei]

    def notiz(self, art, heute=None, jetzt=None):
        """Notiz für Claude: welche Aufgaben als Nächstes dran sind."""
        faellig, neue = self.auswahl(art, heute, jetzt)
        if not faellig and not neue:
            return ("Notiz von Pixel, nicht vom Kind: Im Einmaleins-Karteikasten ist für heute alles geübt. Stell "
                    "gemischte Aufgaben aus dem Thema oder schlag ein anderes Thema vor.")
        liste = ", ".join(sprechen(k) + f" <aufgabe>{k}</aufgabe>" for k in faellig + neue)
        return ("Notiz von Pixel, nicht vom Kind: Nimm für deine nächste Aufgabe eine aus dem Einmaleins-Karteikasten, "
                f"die fälligen zuerst: {liste}. Schreib die Marke <aufgabe> der gewählten Aufgabe mit ans Ende.")

    def bewerte(self, kennung, richtig, heute=None, jetzt=None):
        if kennung not in set(alle_karten("mal")) | set(alle_karten("geteilt")):
            return False
        heute = heute or datetime.date.today()
        k = self.karten.setdefault(kennung, {"fach": 1, "faellig": heute.isoformat(), "richtig": 0, "falsch": 0,
                                             "seit": heute.isoformat()})
        k["zuletzt_s"] = jetzt or time.time()
        if richtig and k["faellig"] > heute.isoformat():
            k["richtig"] += 1  # noch nicht wieder dran: zählt, rückt aber nicht auf
            return True
        if richtig:
            k["fach"] = min(5, k["fach"] + 1)
            k["richtig"] += 1
        else:
            k["fach"] = 1
            k["falsch"] += 1
        k["faellig"] = (heute + datetime.timedelta(days=INTERVALL_TAGE[k["fach"]] if richtig else 0)).isoformat()
        return True

    def uebersicht(self):
        """Für die Oberfläche: Fach je Aufgabe (0 = noch nie geübt), getrennt nach mal und geteilt."""
        def tabelle(art):
            return {k: self.karten.get(k, {}).get("fach", 0) for k in alle_karten(art)}
        mal, geteilt = tabelle("mal"), tabelle("geteilt")
        return {"mal": mal, "geteilt": geteilt, "gekonnt_ab": GEKONNT_AB,
                "mal_gekonnt": sum(f >= GEKONNT_AB for f in mal.values()),
                "geteilt_gekonnt": sum(f >= GEKONNT_AB for f in geteilt.values()),
                "schwierig": sorted((k for k, c in self.karten.items() if c.get("falsch")),
                                    key=lambda k: -self.karten[k]["falsch"])[:8]}
