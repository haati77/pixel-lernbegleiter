"""
Lern-Tagebuch je Kind (lernstand/<kind>_tage.json, nicht in Git): Tageswerte für den Wochenbericht und das
Tagesziel (Wünsche der Eltern, 18.10.2026).

Je Tag: Aufgaben je Fach (richtig, gesamt), ungefähre Lernzeit, gespielte Minuten, ob das Tagesziel erreicht wurde.
Lernzeit: Zeit zwischen zwei bewerteten Antworten, höchstens PAUSE_S (längere Pausen zählen nicht).
Nur Zahlen, nichts aus den Gesprächen.
"""
import json
import os
import time
from pathlib import Path

ORDNER = Path(__file__).parent / "lernstand"
PAUSE_S = 180
TAGE_MERKEN = 120


def _tag(zeit=None):
    return time.strftime("%Y-%m-%d", time.localtime(zeit))


class Tagebuch:
    def __init__(self, kind, ordner=ORDNER):
        self.pfad = Path(ordner) / f"{kind}_tage.json"
        self.tage = {}
        if self.pfad.exists():
            try:
                daten = json.loads(self.pfad.read_text(encoding="utf-8"))
                self.tage = {d: v for d, v in daten.items() if isinstance(v, dict)}
            except (OSError, ValueError) as fehler:
                print(f"  [Tagebuch] {self.pfad.name} nicht lesbar: {fehler}")

    def speichere(self):
        self.pfad.parent.mkdir(exist_ok=True)
        tage = dict(sorted(self.tage.items())[-TAGE_MERKEN:])
        hilfsdatei = self.pfad.with_suffix(".tmp")
        hilfsdatei.write_text(json.dumps(tage, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(hilfsdatei, self.pfad)

    def heute(self, jetzt=None):
        return self.tage.setdefault(_tag(jetzt), {"faecher": {}, "lern_s": 0.0, "gespielt": 0.0, "ziel": False})

    def antwort(self, fach, richtig, jetzt=None):
        """Eine bewertete Antwort. Zählt sie und die Lernzeit seit der vorigen."""
        jetzt = jetzt or time.time()
        tag = self.heute(jetzt)
        r, n = tag["faecher"].get(fach, [0, 0])
        tag["faecher"][fach] = [r + bool(richtig), n + 1]
        abstand = jetzt - tag.get("letzte_s", 0)
        if 0 < abstand <= PAUSE_S:
            tag["lern_s"] += abstand
        tag["letzte_s"] = jetzt

    def richtig_heute(self, jetzt=None):
        return sum(r for r, _ in self.heute(jetzt)["faecher"].values())

    def gespielt(self, minuten, jetzt=None):
        self.heute(jetzt)["gespielt"] += minuten

    def woche(self, tage=7, versatz=0, jetzt=None):
        """Summen über `tage` Tage, `versatz` Tage zurück (versatz=7: Vorwoche)."""
        jetzt = jetzt or time.time()
        daten = [self.tage.get(_tag(jetzt - (versatz + i) * 86400)) for i in range(tage)]
        daten = [d for d in daten if d]
        faecher = {}
        for d in daten:
            for fach, (r, n) in d["faecher"].items():
                fr, fn = faecher.get(fach, [0, 0])
                faecher[fach] = [fr + r, fn + n]
        richtig = sum(r for r, _ in faecher.values())
        gesamt = sum(n for _, n in faecher.values())
        return {"richtig": richtig, "gesamt": gesamt, "faecher": faecher,
                "lern_min": round(sum(d.get("lern_s", 0) for d in daten) / 60),
                "gespielt": round(sum(d.get("gespielt", 0) for d in daten)),
                "lerntage": sum(1 for d in daten if d["faecher"]), "ziele": sum(1 for d in daten if d.get("ziel"))}
