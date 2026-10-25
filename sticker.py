"""
Sticker-Album, Serien und Tagesrekord je Kind (sticker/<kind>.json, nicht in Git).

Damit Lernen Spaß macht (Wunsch der Eltern, 18.10.2026):
- Für jedes geschaffte Thema in Mathe, Deutsch, Sachkunde gibt es einen Tier-Sticker, für ein Thema, das auch
  auf "schwer" sitzt, einen goldenen. In Englisch gibt es für je STICKER_JE_WOERTER gekonnte Wörter einen.
  Welches Tier es wird, ist Zufall unter den noch fehlenden (Sammeln wie bei Sammelkarten).
- Serie: richtige Antworten in Folge im laufenden Gespräch (im Speicher von gespraech.py), bei SERIE_ALLE
  eine Fanfare.
- Tagesrekord: richtige Antworten an einem Tag über alle Fächer, Pixel freut sich einmal am Tag über einen
  neuen Rekord (erst ab REKORD_AB, damit es am ersten Tag nicht ständig passiert).
Gespeichert werden nur Tiernamen, Gründe (Thema) und Zahlen, nichts aus den Gesprächen.
"""
import json
import os
import random
import time
from pathlib import Path

ORDNER = Path(__file__).parent / "sticker"
STICKER_JE_WOERTER = 10
SERIE_ALLE = 5
REKORD_AB = 10

# (Name mit Artikel im Nominativ, Emoji für die Oberfläche). Heimische und bekannte Tiere, kindgerecht.
TIERE = [
    ("der Feuersalamander", "🦎"), ("der Igel", "🦔"), ("das Eichhörnchen", "🐿️"), ("der Fuchs", "🦊"),
    ("der Dachs", "🦡"), ("die Eule", "🦉"), ("der Specht", "🐦"), ("der Biber", "🦫"), ("der Hirsch", "🦌"),
    ("das Wildschwein", "🐗"), ("der Hase", "🐇"), ("der Maulwurf", "🐾"), ("die Fledermaus", "🦇"),
    ("der Marienkäfer", "🐞"), ("die Biene", "🐝"), ("der Schmetterling", "🦋"), ("die Schnecke", "🐌"),
    ("der Frosch", "🐸"), ("die Libelle", "🐾"), ("der Storch", "🐦"), ("der Steinadler", "🦅"), ("die Gämse", "🐐"),
    ("das Murmeltier", "🐾"), ("der Steinbock", "🐐"), ("die Forelle", "🐟"), ("der Schwan", "🦢"),
    ("die Ente", "🦆"), ("der Pinguin", "🐧"), ("der Eisbär", "🐻‍❄️"), ("der Wal", "🐋"), ("der Delfin", "🐬"),
    ("der Oktopus", "🐙"), ("die Schildkröte", "🐢"), ("das Seepferdchen", "🐠"), ("der Hai", "🦈"),
    ("der Elefant", "🐘"), ("die Giraffe", "🦒"), ("das Zebra", "🦓"), ("der Löwe", "🦁"), ("der Tiger", "🐯"),
    ("das Nashorn", "🦏"), ("das Nilpferd", "🦛"), ("das Krokodil", "🐊"), ("der Gorilla", "🦍"),
    ("das Faultier", "🦥"), ("der Koala", "🐨"), ("das Känguru", "🦘"), ("der Panda", "🐼"), ("das Kamel", "🐫"),
    ("der Flamingo", "🦩"), ("der Papagei", "🦜"), ("der Pfau", "🦚"), ("das Erdmännchen", "🐾"),
    ("der Waschbär", "🦝"), ("das Lama", "🦙"), ("der Wolf", "🐺"), ("der Otter", "🦦"), ("das Stinktier", "🦨"),
    ("der Dinosaurier", "🦕"), ("der Tyrannosaurus", "🦖"),
]


def _heute():
    return time.strftime("%Y-%m-%d")


class Album:
    def __init__(self, kind, ordner=ORDNER):
        self.pfad = Path(ordner) / f"{kind}.json"
        daten = {}
        if self.pfad.exists():
            try:
                daten = json.loads(self.pfad.read_text(encoding="utf-8"))
            except (OSError, ValueError) as fehler:
                print(f"  [Sticker] {self.pfad.name} nicht lesbar: {fehler}")
        self.sticker = [s for s in daten.get("sticker", []) if isinstance(s, dict) and s.get("tier")]
        self.tage = {d: n for d, n in (daten.get("tage") or {}).items() if isinstance(n, int)}
        self.rekord_gemeldet = daten.get("rekord_gemeldet", "")
        self.englisch_belohnt = int(daten.get("englisch_belohnt", 0))  # so viele gekonnte Wörter sind belohnt

    def speichere(self):
        self.pfad.parent.mkdir(exist_ok=True)
        tage = dict(sorted(self.tage.items())[-120:])
        hilfsdatei = self.pfad.with_suffix(".tmp")
        hilfsdatei.write_text(json.dumps({"sticker": self.sticker, "tage": tage,
                                          "rekord_gemeldet": self.rekord_gemeldet,
                                          "englisch_belohnt": self.englisch_belohnt}, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        os.replace(hilfsdatei, self.pfad)

    def neuer_sticker(self, grund, gold=False):
        """Zieht einen Sticker (bevorzugt ein Tier, das noch fehlt). Gibt den Eintrag zurück."""
        vorhanden = {s["tier"] for s in self.sticker if bool(s.get("gold")) == gold}
        fehlend = [t for t in TIERE if t[0] not in vorhanden] or TIERE
        tier, emoji = random.choice(fehlend)
        eintrag = {"tier": tier, "emoji": emoji, "gold": gold, "grund": grund, "datum": _heute()}
        self.sticker.append(eintrag)
        return eintrag

    @staticmethod
    def name(eintrag):
        """'der Igel', golden 'der goldene Igel'."""
        tier = eintrag["tier"]
        if eintrag.get("gold"):
            artikel, rest = tier.split(" ", 1)
            tier = f"{artikel} goldene {rest}"
        return tier

    def ansage(self, eintraege):
        """Ein Satz für einen oder mehrere neue Sticker (beim ersten Mal kann Englisch mehrere nachreichen)."""
        if isinstance(eintraege, dict):
            eintraege = [eintraege]
        namen = [self.name(e) for e in eintraege]
        liste = namen[0] if len(namen) == 1 else ", ".join(namen[:-1]) + " und " + namen[-1]
        anfang = "ein neuer Sticker" if len(namen) == 1 else f"{len(namen)} neue Sticker"
        return f"Juhu, {anfang} für dein Album: {liste}! Du hast jetzt {len(self.sticker)} Sticker."

    def zaehle_richtig(self):
        """Eine richtige Antwort heute. Gibt die neue Rekordzahl zurück, wenn heute erstmals der Tagesrekord
        überboten wird (höchstens einmal am Tag), sonst None."""
        heute = _heute()
        self.tage[heute] = self.tage.get(heute, 0) + 1
        frueher = max((n for d, n in self.tage.items() if d != heute), default=0)
        if self.rekord_gemeldet != heute and frueher >= REKORD_AB and self.tage[heute] == frueher + 1:
            self.rekord_gemeldet = heute
            return self.tage[heute]
        return None

    def zusammenfassung(self):
        if not self.sticker:
            return "Du hast noch keine Sticker. Wenn du ein Thema schaffst, bekommst du deinen ersten."
        gold = sum(1 for s in self.sticker if s.get("gold"))
        neu = self.name(self.sticker[-1])
        return (f"Du hast {len(self.sticker)} Sticker" + (f", davon {gold} goldene" if gold else "")
                + f". Dein neuester ist {neu}. Insgesamt gibt es {len(TIERE)} Tiere zu sammeln.")

    def uebersicht(self):
        return {"sticker": self.sticker, "anzahl_tiere": len(TIERE),
                "verschiedene": len({s["tier"] for s in self.sticker}),
                "rekord": max(self.tage.values(), default=0), "heute": self.tage.get(_heute(), 0)}
