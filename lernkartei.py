"""
Lernplan und Lernkartei je Kind (Englisch).

Lernplan: lernplan_englisch.json (im Repository), vier Stufen mit Wörtern und Sätzen nach dem LehrplanPLUS
Grundschule Bayern (Englisch 3/4: verbindlicher Wortschatz, empfohlene Redemittel). "pflicht" markiert diese
Einträge, "rollenspiel" persönliche Angaben, die nur mit erfundenen Personen geübt werden.
Lernkartei: lernstand/<kind>.json (nicht in Git), eine Karteikarte je geübtem Eintrag:
    Fach 1 bis 5. Richtig: ein Fach höher, nächste Abfrage nach INTERVALL_TAGE. Falsch: zurück in Fach 1.
    Gekonnt ab Fach GEKONNT_AB. Sind AUFSTIEG_ANTEIL der aktuellen Stufe gekonnt, kommt die nächste Stufe.

Mister Pixel bekommt vor jeder Antwort eine kurze Liste (fällige Wiederholungen zuerst, dann neue Einträge der
aktuellen Stufe) und bewertet die Antwort des Kindes versteckt mit <ergebnis>richtig</ergebnis>. Welcher Eintrag
gemeint war, steht in der versteckten Lösung seiner vorigen Frage (<loesung>…</loesung>).
"""
import datetime
import json
import os
import re
import time
from pathlib import Path

BASIS = Path(__file__).parent
LERNPLAN = BASIS / "lernplan_englisch.json"
ORDNER = BASIS / "lernstand"

INTERVALL_TAGE = {1: 0, 2: 1, 3: 3, 4: 7, 5: 21}  # nach "richtig" in Fach n: nächste Abfrage in n Tagen
GEKONNT_AB = 4
AUFSTIEG_ANTEIL = 0.8
MAX_WIEDERHOLEN = 6        # fällige Karten pro Liste
MAX_NEU = 4                # neue Einträge pro Liste
MAX_NEU_PRO_TAG = 12       # danach nur noch Wiederholungen, damit es nicht zu viel wird
SPERRE_S = 120             # gerade abgefragte Karten nicht sofort wieder anbieten

# Themen zum Auswählen (Wunsch der Eltern, 18.10.2026: Kinder wählen selbst): Gruppe -> Themen im Lernplan
THEMEN_GRUPPEN = {
    "Tiere": {"Tiere"}, "Farben": {"Farben"},
    "Zahlen": {"Zahlen", "Zahlen bis 10", "Zahlen und Geld", "Uhrzeit"},
    "Essen und Trinken": {"Essen und Trinken", "Essen"}, "Familie und Freunde": {"Familie", "Familie und Freunde"},
    "Schule": {"Schule"}, "Kleidung": {"Kleidung"}, "Körper und Gefühle": {"Körper", "Gefühle"},
    "Wetter und Kalender": {"Wetter", "Monate", "Wochentage", "Feste"}, "Freizeit": {"Freizeit", "Tätigkeiten"},
    "Zuhause": {"Zuhause", "Wo ist es?"}, "Einkaufen": {"Einkaufen"},
    "Begrüßen und höflich sein": {"Begrüßung", "Höflichkeit"}, "Eigenschaften": {"Eigenschaften"},
    "Länder und Sprachen": {"Länder und Sprachen"}, "Sätze": {"Sätze", "Ausblick Klasse 5"},
}
NIVEAUS = ("leicht", "mittel", "schwer")
NIVEAU_TEXT = {
    "leicht": "einzelne Wörter, vor allem Deutsch nach Englisch, langsam, mit Tipp (Anfangsbuchstabe oder Reim)",
    "mittel": "Wörter und kurze Sätze, abwechselnd in beide Richtungen",
    "schwer": "auch ganze Sätze, Englisch nach Deutsch ohne Tipp, kleine Hörübungen und Rollenspiele auf Englisch",
}


def gruppe(thema):
    """Gruppe zu einem Thema im Lernplan (unbekannte Themen sind ihre eigene Gruppe)."""
    return next((g for g, themen in THEMEN_GRUPPEN.items() if thema in themen), thema)


def schluessel(text):
    """Vergleichsform: klein, ohne Satzzeichen und doppelte Leerzeichen ("I'm fine." -> "im fine")."""
    text = text.lower().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^\wäöüß ]", " ", text).split())


def startstufe(klasse):
    """Klasse 0 bis 2 -> Stufe 1, Klasse 3 -> 2, Klasse 4 -> 3, ab Klasse 5 -> 4."""
    return 1 if klasse <= 2 else min(4, klasse - 1)


class Lernplan:
    def __init__(self, pfad=LERNPLAN):
        roh = json.loads(Path(pfad).read_text(encoding="utf-8"))
        self.fach = roh.get("fach", "Englisch")
        self.stufen = sorted(roh["stufen"], key=lambda s: s["stufe"])
        self.eintraege = {}  # Kennung (englischer Text in Vergleichsform) -> Eintrag mit "stufe"
        self._index = {}     # Vergleichsform von en, de und auch -> Kennung
        for s in self.stufen:
            for e in s["eintraege"]:
                kid = schluessel(e["en"])
                if kid in self.eintraege:
                    raise ValueError(f"Eintrag '{e['en']}' kommt im Lernplan doppelt vor")
                self.eintraege[kid] = dict(e, stufe=s["stufe"], typ=e.get("typ", "wort"))
                for text in (e["en"], e["de"], *e.get("auch", [])):
                    self._index.setdefault(schluessel(text), kid)

    @property
    def hoechste(self):
        return self.stufen[-1]["stufe"]

    def stufe(self, nr):
        return next(s for s in self.stufen if s["stufe"] == nr)

    def der_stufe(self, nr):
        return [k for k, e in self.eintraege.items() if e["stufe"] == nr]

    def finde(self, text):
        """Kennung zu einer Lösung ("dog", "Hund", "I like apples.") oder None."""
        return self._index.get(schluessel(text or ""))


class Lernkartei:
    def __init__(self, kind, klasse, plan, ordner=ORDNER):
        self.plan = plan
        self.pfad = Path(ordner) / f"{kind}.json"
        if self.pfad.exists():
            daten = json.loads(self.pfad.read_text(encoding="utf-8"))
        else:
            daten = {"stufe": startstufe(klasse), "karten": {}}
        self.stufe = min(max(int(daten.get("stufe", 1)), 1), plan.hoechste)
        self.karten = {k: v for k, v in daten.get("karten", {}).items() if k in plan.eintraege}
        self.thema = daten.get("thema") if daten.get("thema") in self.themen() else ""  # "" = gemischt
        self.niveau = daten.get("niveau") if daten.get("niveau") in NIVEAUS else "mittel"

    def themen(self):
        """Wählbare Themengruppen in der Reihenfolge des Lernplans."""
        return list(dict.fromkeys(gruppe(e.get("thema", "")) for e in self.plan.eintraege.values() if e.get("thema")))

    def im_thema(self, kennung):
        return not self.thema or gruppe(self.plan.eintraege[kennung].get("thema", "")) == self.thema

    def speichere(self):
        self.pfad.parent.mkdir(exist_ok=True)
        hilfsdatei = self.pfad.with_suffix(".tmp")
        inhalt = {"stufe": self.stufe, "thema": self.thema, "niveau": self.niveau, "karten": self.karten}
        hilfsdatei.write_text(json.dumps(inhalt, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(hilfsdatei, self.pfad)

    # ------------------------------------------------------------------ Auswahl
    def faellig(self, heute=None, jetzt=None):
        heute = (heute or datetime.date.today()).isoformat()
        jetzt = jetzt or time.time()
        karten = [(k, c) for k, c in self.karten.items()
                  if c["faellig"] <= heute and jetzt - c.get("zuletzt_s", 0) >= SPERRE_S and self.im_thema(k)]
        return [k for k, _ in sorted(karten, key=lambda kc: (kc[1]["fach"], kc[1]["faellig"]))]

    def neue(self, heute=None):
        heute = (heute or datetime.date.today()).isoformat()
        heute_neu = sum(1 for c in self.karten.values() if c.get("seit") == heute)
        frei = max(0, min(MAX_NEU, MAX_NEU_PRO_TAG - heute_neu))
        if self.thema:  # gewähltes Thema: neue Wörter daraus, auch aus anderen Stufen (leichtere zuerst)
            kandidaten = sorted((k for k in self.plan.eintraege if k not in self.karten and self.im_thema(k)),
                                key=lambda k: self.plan.eintraege[k]["stufe"])
            return kandidaten[:frei]
        return [k for k in self.plan.der_stufe(self.stufe) if k not in self.karten][:frei]

    def auswahl(self, heute=None, jetzt=None):
        """(Wiederholen, Neu): Kennungen für die nächste Antwort von Mister Pixel."""
        return self.faellig(heute, jetzt)[:MAX_WIEDERHOLEN], self.neue(heute)

    def prompt_abschnitt(self, heute=None, jetzt=None):
        """Abschnitt für den System-Prompt. Enthält nur Wörter, keine Namen."""
        wiederholen, neu = self.auswahl(heute, jetzt)
        s = self.plan.stufe(self.stufe)
        def zeile(k):
            e = self.plan.eintraege[k]
            return f"{e['en']} = {e['de']}" + (" (nur im Rollenspiel)" if e.get("rollenspiel") else "")
        teile = [f"Lernplan für dieses Kind: {self.plan.fach}, Stufe {self.stufe} von {self.plan.hoechste} "
                 f"({s['name']}: {s['beschreibung']}).",
                 f"Gewähltes Thema: {self.thema or 'gemischt, alle Themen der Stufe'}. Das Kind darf selbst ein "
                 f"Thema wählen: {', '.join(self.themen())} oder gemischt. Nennt es eins (auch mit eigenen Worten, "
                 "zum Beispiel Tiere oder Essen), schreib einmal die versteckte Marke mit dem Namen aus der Liste, "
                 "zum Beispiel <thema>Tiere</thema>, für alle Themen <thema>gemischt</thema>, und übe ab jetzt das.",
                 f"Schwierigkeit: {self.niveau} ({NIVEAU_TEXT[self.niveau]}). Sagt das Kind leichter oder schwerer, "
                 "machst du es genau so und schreibst einmal <niveau>leicht</niveau>, <niveau>mittel</niveau> oder "
                 "<niveau>schwer</niveau>. Leicht: " + NIVEAU_TEXT["leicht"] + ". Schwer: " + NIVEAU_TEXT["schwer"] + "."]
        if wiederholen:
            teile.append("Zuerst wiederholen (diese Wörter hat das Kind schon geübt):\n- "
                         + "\n- ".join(zeile(k) for k in wiederholen))
        if neu:
            teile.append("Neu einführen (erst erklären oder vorsprechen, dann abfragen):\n- "
                         + "\n- ".join(zeile(k) for k in neu))
        if not wiederholen and not neu:
            teile.append("Für heute ist alles geübt" + (f" im Thema {self.thema}. Lobe das Kind und schlag ein "
                                                        "anderes Thema vor" if self.thema else
                                                        ". Lobe das Kind, spiel frei mit bekannten Wörtern oder "
                                                        "plaudere auf Englisch") + ".")
        teile.append(
            "Frage nur Wörter und Sätze aus dieser Liste ab, Sätze genau so wie sie dastehen, abwechselnd Englisch "
            "nach Deutsch und Deutsch nach Englisch. Auch bei Rätseln, Hörübungen und Rollenspielen ist die "
            "gesuchte Antwort ein Eintrag aus dieser Liste. Hier sind Wiederholungen erwünscht. Die versteckte Lösung "
            "<loesung> enthält genau das Wort oder den Satz aus der Liste in der gefragten Sprache.\n"
            "Hat das Kind gerade auf eine deiner Abfragen geantwortet, beginnt deine Antwort mit <ergebnis>richtig"
            "</ergebnis> oder <ergebnis>falsch</ergebnis> (wird nicht vorgelesen). Weiß das Kind es nicht, ist es "
            "falsch. Ähnlich klingende Verhörer zählen als richtig.\n"
            "Persönliche Angaben (Name, Alter, Herkunft, Geburtstag, Schule, Lehrkraft) übst du nur im Rollenspiel "
            "mit erfundenen Personen (This is Tom. He's nine.) oder als Satz zum Nachsprechen und Übersetzen. Frag "
            "das Kind nie nach seinen echten Daten.")
        return "\n".join(teile)

    # ------------------------------------------------------------------ Bewertung
    def bewerte(self, kennung, richtig, heute=None, jetzt=None):
        """Karte nach einer Antwort weiterschieben. Gibt die neue Stufe zurück, wenn aufgestiegen, sonst None."""
        heute = heute or datetime.date.today()
        k = self.karten.setdefault(kennung, {"fach": 1, "faellig": heute.isoformat(), "richtig": 0, "falsch": 0,
                                             "seit": heute.isoformat()})
        if richtig and k["faellig"] > heute.isoformat():
            # Noch nicht wieder dran (Mister Pixel fragt dasselbe Wort öfter): zählt, rückt aber nicht auf. Sonst
            # war ein Wort nach viermal "dog" an einem Tag im letzten Fach und kam erst nach 21 Tagen wieder.
            k["richtig"] += 1
            k["zuletzt_s"] = jetzt or time.time()
            return None
        if richtig:
            k["fach"] = min(5, k["fach"] + 1)
            k["richtig"] += 1
        else:
            k["fach"] = 1
            k["falsch"] += 1
        k["faellig"] = (heute + datetime.timedelta(days=INTERVALL_TAGE[k["fach"]] if richtig else 0)).isoformat()
        k["zuletzt_s"] = jetzt or time.time()
        if self.stufe < self.plan.hoechste and self.anteil_gekonnt(self.stufe) >= AUFSTIEG_ANTEIL:
            self.stufe += 1
            return self.stufe
        return None

    def anteil_gekonnt(self, stufe):
        eintraege = self.plan.der_stufe(stufe)
        gekonnt = sum(1 for k in eintraege if self.karten.get(k, {}).get("fach", 0) >= GEKONNT_AB)
        return gekonnt / len(eintraege) if eintraege else 1.0

    # ------------------------------------------------------------------ Übersicht für die Oberfläche
    def uebersicht(self, heute=None):
        heute_s = (heute or datetime.date.today()).isoformat()
        stufen = []
        for s in self.plan.stufen:
            eintraege = self.plan.der_stufe(s["stufe"])
            pflicht = [k for k in eintraege if self.plan.eintraege[k].get("pflicht")]
            stufen.append({"stufe": s["stufe"], "name": s["name"], "beschreibung": s["beschreibung"],
                           "eintraege": len(eintraege), "pflicht": len(pflicht),
                           "pflicht_gekonnt": sum(1 for k in pflicht
                                                  if self.karten.get(k, {}).get("fach", 0) >= GEKONNT_AB),
                           "geuebt": sum(1 for k in eintraege if k in self.karten),
                           "gekonnt": sum(1 for k in eintraege if self.karten.get(k, {}).get("fach", 0) >= GEKONNT_AB)})
        karten = [dict(c, kennung=k, en=self.plan.eintraege[k]["en"], de=self.plan.eintraege[k]["de"],
                       stufe=self.plan.eintraege[k]["stufe"]) for k, c in self.karten.items()]
        for c in karten:
            c.pop("zuletzt_s", None)
        schwierig = sorted([c for c in karten if c["falsch"]], key=lambda c: (-c["falsch"], c["fach"]))[:8]
        themen = []
        for name in self.themen():
            alle = [k for k, e in self.plan.eintraege.items() if gruppe(e.get("thema", "")) == name]
            themen.append({"name": name, "eintraege": len(alle), "geuebt": sum(k in self.karten for k in alle),
                           "gekonnt": sum(self.karten.get(k, {}).get("fach", 0) >= GEKONNT_AB for k in alle)})
        return {"stufe": self.stufe, "hoechste": self.plan.hoechste, "stufen": stufen, "thema": self.thema,
                "niveau": self.niveau, "niveaus": list(NIVEAUS), "themen": themen,
                "pflicht": sum(s["pflicht"] for s in stufen),
                "pflicht_gekonnt": sum(s["pflicht_gekonnt"] for s in stufen),
                "faellig_heute": sum(1 for c in self.karten.values() if c["faellig"] <= heute_s),
                "gekonnt": sum(1 for c in self.karten.values() if c["fach"] >= GEKONNT_AB),
                "karten": sorted(karten, key=lambda c: (c["stufe"], c["fach"], c["en"].lower())),
                "schwierig": schwierig}
