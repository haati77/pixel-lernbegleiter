"""
Pixel, der sprechende Lernbegleiter (Windows-Version)

Kette: Mikrofon -> Wake Word -> Sprechpausen-Erkennung -> Deepgram (STT) -> Claude -> Piper (TTS)

Benötigt die Umgebungsvariablen (Schlüssel nie in Dateien schreiben):
    DEEPGRAM_API_KEY    Spracherkennung
    PIDOG_ANTHROPIC_API_KEY   Claude (eigener Name, damit Claude Code ihn nicht nutzt;
                              ANTHROPIC_API_KEY geht auch)

Start:
    python gespraech.py                          # Wake Word "Hey Pixel", dann sprechen
    python gespraech.py --wakeword hey_mycroft   # anderes Wake Word (eigenes in wakewords/ oder mitgeliefert)
    python gespraech.py --modus taste            # Enter statt Wake Word (zum Testen)
    python gespraech.py --modus dauerhaft        # ohne Wake Word, jede Sprache wird verarbeitet
    python gespraech.py --debug                  # Wake-Word-Scores anzeigen (zum Einstellen)

Ablauf im Modus "wakeword":
    1. Warten auf das Wake Word (alles lokal, nichts geht ins Netz)
    2. Kurze Bestätigung ("Ja?"), dann sprechen
    3. Aufnahme endet automatisch bei einer Sprechpause
    4. Deepgram -> Claude -> Piper
    5. Danach kurzes Zeitfenster für eine Folgefrage ohne Wake Word, dann wieder Schritt 1

Sprachbefehle (lokal erkannt, gehen nicht an Claude, nur als ganze Äußerung):
    "Tschüss" / "Gespräch beenden"    Verlauf löschen, verabschieden, zurück zum Wake Word
    "Pause" / "Sei still"             zurück zum Wake Word, Verlauf bleibt
    "Neues Gespräch" / "Vergiss alles" Verlauf löschen, weiter zuhören
    "Wiederhole"                      letzte Antwort noch einmal
    "Modell Sonnet" / "Klugmodus"     auf claude-sonnet-5-5 wechseln
    "Modell Haiku" / "Schnellmodus"   auf claude-haiku-5-5 wechseln
    "Welches Modell?"                 aktuelles Modell ansagen
"""
import argparse
from collections import Counter
import csv
import io
from concurrent.futures import ThreadPoolExecutor
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

import stimmen
from prompts import GESCHICHTEN_PROMPT, SYSTEM_PROMPT  # Standardtexte, editierbar in der Oberfläche
import kinder as kinder_mod
import lernkartei
import lernthemen
import einmaleins
import persoenlichkeiten as pers
import sticker as sticker_mod
import tagebuch as tagebuch_mod
from einstellungen import FELDER as EINSTELLUNGEN_FELDER, Einstellungen
from hoeren import RATE, Hoerer, anzeigename
from sprachtest import SAMPLERATE_AUFNAHME, STILLE_SCHWELLE, baue_cloud_erkenner, nimm_auf, spiele

EINSTELLUNGEN_DATEI = Path(__file__).parent / "einstellungen.json"
PERSOENLICHKEITEN_DATEI = Path(__file__).parent / "persoenlichkeiten.json"
MAX_TOKENS = 1024                     # Obergrenze; kurze Antworten kommen über den System-Prompt
MAX_TOKENS_GESCHICHTE = 4096          # Gute-Nacht-Geschichte: ca. 1.200 bis 1.600 Tokens, mit Reserve
MAX_NACHRICHTEN = 20                  # höchstens so viele Nachrichten im Verlauf, dann …
VERLAUF_KUERZEN_AUF = 10              # … auf so viele kürzen (in einem Schritt, damit der Cache lange passt)
VERLAUF_VERGESSEN_S = 300             # nach so langer Pause beginnt ein neues Gespräch
WARTEN_NACH_WAKEWORD_S = 5.0          # so lange auf den Sprechbeginn nach dem Wake Word warten
CLAUDE_TIMEOUT_S = 10.0               # SDK-Standard wäre 600 s, so lange wartet kein Kind
CLAUDE_WIEDERHOLUNGEN = 1             # SDK-Standard wäre 2
CLAUDE_VERBINDUNG_OFFEN_S = 60.0      # Standard 5 s, zwischen zwei Fragen liegen meist 15 bis 20 s
LAUTSTAERKE_STUFEN = [0.2, 0.35, 0.5, 0.65, 0.8, 1.0]  # Faktor auf die Piper-Ausgabe, Stufe 1 bis 6
SCHLAFENSZEIT = "Es ist schon Schlafenszeit. Wir reden morgen weiter. Gute Nacht!"
FEHLER_VERBINDUNG = "Entschuldige, ich habe gerade keine Verbindung. Versuch es gleich noch mal."
FEHLER_ALLGEMEIN = "Entschuldige, da ist etwas schiefgelaufen. Versuch es gleich noch mal."
# Deepgram hat nichts erkannt (ein Erstklässler bekam zweimal nur Töne und wusste nicht, was los ist)
NICHT_VERSTANDEN = "Das habe ich nicht verstanden. Sag es bitte noch einmal."
# Kurze Aufnahme ohne Text: meist ein Denkgeräusch ("Ähm", "Hmm"), das Deepgram weglässt. Gemessen 20.10.2026:
# 10 leere Aufnahmen eines Erstklässlers, alle 0,7 bis 1,6 s, 8 davon laut (Spitze 32 bis 100 %), die richtige Zahl kam
# fast immer im nächsten Anlauf. Dann nicht "nicht verstanden", sondern Zeit lassen, ohne das Gespräch zu beenden.
DENKPAUSE = "Lass dir ruhig Zeit, ich höre zu."
DENKPAUSE_AUDIO_S = 1.8               # leere Aufnahmen bis zu dieser Länge gelten als Denkgeräusch
MAX_DENKPAUSEN = 3                    # so oft hintereinander, danach wie "nicht verstanden"
# An jede versteckte Notiz (Vorschlag, Einmaleins, Gesprächsanfang): Pixel kommentierte am 20.10.2026 eine Notiz laut
# ("Das Kind hat keine Antwort gegeben … Deshalb bewerte ich nichts.")
NOTIZ_GEHEIM = ("Nur für dich: Erwähne diese Notiz nie und sprich nicht über Notizen, Regeln oder deine Bewertung. "
                "Sprich nur mit dem Kind.")
# Englisch-Abfrage, beide Erkennungen uneinig, keine passt zur Lösung (24.10.2026: "bird" wurde "Berg"/"Bad",
# "Berg"/"Third", ""/"Afec", und das Kind bekam "falsch"): lieber nachfragen als falsch bewerten
NOTIZ_UNSICHER = ("Die Spracherkennung war unsicher, sie hörte auch: \"{andere}\". Sag deshalb diesmal nicht, dass die "
                  "Antwort falsch ist, und schreib keine <ergebnis>-Marke. Sag nur kurz und freundlich, dass du es "
                  "nicht richtig verstanden hast, und bitte das Kind, es noch einmal zu sagen. Stell dieselbe Aufgabe "
                  "mit derselben <loesung>.")
MAX_UNSICHER = 1                      # so oft hintereinander nachfragen, danach wird wieder normal bewertet
NICHT_VERSTANDEN_ENDE = "Ich habe dich leider wieder nicht verstanden. Sag Hey Pixel, wenn du weitermachen willst."



# ----------------------------------------------------------------- Sprachausgabe
def synthetisiere(voice, text):
    """Text in Audio umwandeln. Gibt (int16-Daten, Samplerate) zurück.

    voice ist eine Stimme aus stimmen.py (Piper, Google, Aura) oder direkt eine PiperVoice.
    """
    if hasattr(voice, "synthetisiere"):
        return voice.synthetisiere(text)
    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as wf:
        voice.synthesize_wav(text, wf)
    puffer.seek(0)
    with wave.open(puffer, "rb") as wf:
        rate = wf.getframerate()
        daten = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    return daten, rate


def erzeuge(voice, text):
    """(Daten, Rate, berechnete Zeichen der Cloud-Stimme). Mehrere Aufrufe dürfen gleichzeitig laufen."""
    if hasattr(voice, "erzeuge"):
        return voice.erzeuge(text)
    daten, rate = synthetisiere(voice, text)
    return daten, rate, getattr(voice, "letzte_zeichen", 0)


def piepton():
    """Kurzer, sanfter Ton als Bestätigung. Gibt (int16-Daten, Samplerate) zurück."""
    t = np.linspace(0, 0.15, int(RATE * 0.15), endpoint=False)
    ton = 0.3 * np.sin(2 * np.pi * 880 * t) * np.hanning(len(t))
    return (ton * 32767).astype(np.int16), RATE


def _toene(*noten, dauer=0.09, luecke=0.03, staerke=0.25):
    """Kurze, weiche Tonfolge (Hz). Gibt (int16-Daten, Samplerate) zurück."""
    t = np.linspace(0, dauer, int(RATE * dauer), endpoint=False)
    stille = np.zeros(int(RATE * luecke))
    teile = []
    for hz in noten:
        teile += [staerke * np.sin(2 * np.pi * hz * t) * np.hanning(len(t)), stille]
    return (np.concatenate(teile[:-1]) * 32767).astype(np.int16), RATE


# Signaltöne im Gespräch: aufsteigend = "Ich bin fertig, du kannst antworten",
# absteigend = "Gespräch zu Ende, jetzt wieder mit Hey Pixel ansprechen"
TON_BEREIT = _toene(660, 990)
TON_ENDE = _toene(784, 523, dauer=0.12)
# Belohnungen: kurzes "Pling" bei richtig (vor Pixels Antwort), Fanfare bei einer Serie, Glitzern beim Sticker
TON_RICHTIG = _toene(1047, 1568, dauer=0.07, staerke=0.18)
TON_SERIE = _toene(523, 659, 784, 1047, dauer=0.11)
TON_STICKER = _toene(1319, 1568, 2093, 2637, dauer=0.06, luecke=0.02, staerke=0.18)


def signalton(ton, gespraech):
    daten, rate = ton
    spiele(mit_lautstaerke(daten, gespraech.lautstaerke), rate)


def mit_lautstaerke(daten, faktor):
    """int16-Audio leiser machen (Faktor 0 bis 1)."""
    return (daten.astype(np.float32) * faktor).astype(np.int16)


class Sprecher:
    """Spricht Sätze nacheinander in einem Hintergrund-Thread, während Claude noch schreibt."""

    def __init__(self, voice, lautstaerke=1.0, englisch=None, jubel=False, beim_ton=None):
        self.voice = voice
        self.beim_ton = beim_ton      # wird einmal aufgerufen, wenn der erste Satz zu hören ist (Zustand "spricht")
        self.jubel = jubel          # bei <ergebnis>richtig</ergebnis> vorher TON_RICHTIG spielen (einmal)
        self.englisch = englisch    # Stimme für <en>…</en>, None = Markierungen werden nur entfernt
        self._in_englisch = False   # Markierung aus einem früheren Satz noch offen
        self.lautstaerke = lautstaerke
        self.erster_ton = None      # Zeitpunkt (time.time), an dem der erste Satz zu hören ist
        self.tts_erster_s = None    # Rechenzeit der Sprachausgabe für den ersten Satz
        self.zeichen_erster_satz = None
        self.zeichen = {}           # Stimme -> berechnete Zeichen der Cloud-Stimme (nicht bei Piper-Ersatz)
        # Deutsche und englische Teile eines Satzes gleichzeitig erzeugen (Google braucht je Teil ca. 0,6 s)
        self._pool = ThreadPoolExecutor(max_workers=4)
        self.warteschlange = queue.Queue()
        self.thread = threading.Thread(target=self._arbeite, daemon=True)
        self.thread.start()

    def _arbeite(self):
        while True:
            satz = self.warteschlange.get()
            if satz is None:
                return
            try:
                t0 = time.time()
                if self.jubel and stimmen.ergebnis(satz) is True:
                    self.jubel = False
                    spiele(mit_lautstaerke(TON_RICHTIG[0], self.lautstaerke), TON_RICHTIG[1])
                teile, self._in_englisch = stimmen.zerlege_sprachen(satz, self._in_englisch)
                if not self.englisch:  # ohne englische Stimme alles mit der normalen sprechen
                    teile = [("de", " ".join(text for _, text in teile))] if teile else []
                # erst alle Teile erzeugen (gleichzeitig), dann ohne Lücke nacheinander abspielen
                auftraege = [(self.englisch if sprache == "en" else self.voice, text) for sprache, text in teile]
                if len(auftraege) > 1:
                    ergebnisse = list(self._pool.map(lambda a: erzeuge(*a), auftraege))
                else:
                    ergebnisse = [erzeuge(*a) for a in auftraege]
                audio = []
                for (voice, _), (daten, rate, zeichen) in zip(auftraege, ergebnisse):
                    audio.append((daten, rate))
                    self.zeichen[voice] = self.zeichen.get(voice, 0) + zeichen
                if audio and self.erster_ton is None:
                    self.tts_erster_s = time.time() - t0
                    self.erster_ton = time.time()
                    if self.beim_ton:
                        self.beim_ton()
                    self.zeichen_erster_satz = len(stimmen.ohne_marken(satz))
                for daten, rate in audio:
                    spiele(mit_lautstaerke(daten, self.lautstaerke), rate)
            except Exception as fehler:
                print(f"  [TTS] FEHLER: {fehler}")

    def sprich(self, satz):
        self.warteschlange.put(satz)

    def fertig(self):
        """Wartet, bis alle Sätze gesprochen sind."""
        self.warteschlange.put(None)
        self.thread.join()
        self._pool.shutdown(wait=False)


# ------------------------------------------------------------------- Satzzerlegung
_SATZENDE = re.compile(r"(?<=[.!?])\s+|\n+")
MIN_SATZLAENGE = 12  # sehr kurze Sätze werden mit dem nächsten verbunden (flüssigere Sprache)
# Nach diesen Abkürzungen endet kein Satz ("z. B.", "d. h.", "ca." ...)
_ABKUERZUNG = re.compile(
    r"(?:\bz\. ?B|\bd\. ?h|\bu\. ?a|\bz\. ?T|\bca|\busw|\bbzw|\bvgl|\bDr|\bNr)\.$", re.IGNORECASE
)


def zerlege_in_saetze(puffer, ende=False):
    """Teilt gepufferten Text in fertige Sätze und einen Rest. Gibt (Sätze, Rest) zurück."""
    teile = _SATZENDE.split(puffer)
    rest = "" if ende else teile.pop()  # letztes Stück ist noch unvollständig
    saetze, aktuell = [], ""
    for teil in teile:
        teil = teil.strip()
        if not teil:
            continue
        aktuell = f"{aktuell} {teil}".strip()
        if len(aktuell) >= MIN_SATZLAENGE and not _ABKUERZUNG.search(aktuell):
            saetze.append(aktuell)
            aktuell = ""
    if aktuell:
        if ende:
            saetze.append(aktuell)
        else:
            rest = f"{aktuell} {rest}"  # Leerzeichen bewusst behalten, es kommt noch Text
    return saetze, rest


# ----------------------------------------------------------------- Sprachbefehle
# Befehle werden lokal erkannt und gehen nicht an Claude. Sie zählen nur, wenn die ganze
# Äußerung der Befehl ist ("Wie sagt man Tschüss auf Englisch?" beendet nichts).
BEFEHLE = {
    "beenden": {"tschüss", "tschüs", "ende", "gespräch beenden", "schlaf gut", "danke das wars",
                "danke das war es", "auf wiedersehen", "bis bald"},
    "pause": {"pause", "sei still", "stopp", "stop", "ruhe"},
    "neu": {"neues gespräch", "vergiss alles", "von vorn", "von vorne", "fang von vorne an"},
    "wiederholen": {"wiederhole", "wiederhol das", "wiederhole das", "bitte wiederholen", "noch mal",
                    "nochmal", "was hast du gesagt", "wie bitte"},
    "welches_modell": {"welches modell", "welches modell benutzt du", "modell"},
    "persoenlichkeiten": {"welche persönlichkeiten gibt es", "welche persönlichkeiten hast du", "persönlichkeiten",
                          "wer kannst du alles sein", "was kannst du alles sein", "welche persönlichkeit bist du"},
    "lauter": {"lauter", "sprich lauter", "lauter bitte", "bitte lauter", "etwas lauter", "mach lauter",
               "noch lauter"},
    "leiser": {"leiser", "sprich leiser", "leiser bitte", "bitte leiser", "etwas leiser", "mach leiser",
               "noch leiser"},
}
# Modelle mit Sprechnamen und Aliasen. Deepgram schreibt die Namen oft anders ("Sonett", "Hai Ku").
MODELLE = {
    "claude-haiku-5-5": {
        "name": "Haiku", "modus": "Schnellmodus",
        "aliase": {"haiku", "hai ku", "heiku", "haiko", "eiku", "schnell", "schnellmodus", "schnell modus"},
    },
    "claude-sonnet-5-5": {
        # Nicht "Denkmodus": Sonnet denkt bei uns nicht vorab (between_tools), ist aber das stärkere Modell
        "name": "Sonnet", "modus": "Klugmodus",
        "aliase": {"sonnet", "sonett", "sonnett", "sonet", "sonnet modus", "klug", "klugmodus",
                   "klug modus", "schlau"},
    },
}


def normalisiere(text):
    """Kleinbuchstaben, ohne Satzzeichen, einfache Leerzeichen."""
    text = text.lower().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^\wäöüß ]", " ", text).split())


def pruefe_befehl(text):
    """Gibt (Art, Wert) zurück, wenn der Text ein Sprachbefehl ist, sonst None."""
    t = normalisiere(text)
    for art, saetze in BEFEHLE.items():
        if t in saetze:
            return art, None
    # "Modell Sonnet", "Model Haiku" oder direkt "Klugmodus", "Schnellmodus"
    rest = re.sub(r"^(modell|model)\s+", "", t)
    if rest != t or rest.endswith("modus"):
        for modell, info in MODELLE.items():
            if rest in info["aliase"]:
                return "modell", modell
        if rest != t:
            return "modell", None  # "Modell ..." gesagt, aber unbekannter Name
    return None


_GESCHICHTE = re.compile(
    r"\b(erzähl\w*|lies|vorlesen|vorles\w*)\b.*\bgeschichte\b"
    r"|\bgeschichte\b.*\b(erzähl\w*|vorlesen|vorles\w*|hören)\b"
    r"|^(eine |noch eine )?gute nacht geschichte\b"
)


def ist_geschichtenwunsch(text):
    """Wünscht sich das Kind eine Geschichte? 'Erzähl mir eine Geschichte über einen Drachen' ja,
    'Was ist eine Geschichte?' nein."""
    t = normalisiere(text).replace("gutenacht", "gute nacht")
    t = re.sub(r"(\w)geschichte\b", r"\1 geschichte", t)  # "Drachengeschichte" -> "drachen geschichte"
    return bool(_GESCHICHTE.search(t))


# Verabschiedung am Ende einer längeren Äußerung ("Ich muss jetzt los, also tschüss"). Ein einzelnes
# "Tschüss" ist ein fester Befehl (BEFEHLE). Bewusst nur Deutsch: "Goodbye" ist bei Mister Pixel oft
# die Antwort auf eine Vokabelfrage.
_ABSCHIED = re.compile(
    r"\b(tschüss|tschüs|tschau|ciao|auf wiedersehen|bis bald|bis morgen|bis später|bis dann"
    r"|bis zum nächsten mal)$"
    r"|\bich muss (jetzt |leider |jetzt leider )?(los|gehen|weg|aufhören|schluss machen)\b"
)


def hinweiswoerter(antwort):
    """Englische Wörter und Sätze aus Pixels letzter Antwort (<en>…</en>). Das Kind antwortet meist mit
    genau diesen ("Wie heißt Hund auf Englisch? … <en>dog</en>"), Deepgram verhört sich sonst bei
    einzelnen Wörtern leicht (dog -> Talk, Doc). Ohne Satzzeichen am Rand, jedes nur einmal."""
    antwort = antwort or ""
    hinweise = []
    # Mehrere Lösungen in einer Marke ("Lena, Jonas, sieben Uhr") einzeln: Deepgram ignoriert Hinweise mit Komma
    loesungen = [teil for loesung in stimmen.loesungen(antwort) for teil in re.split(r",|;| oder ", loesung)]
    # Zuerst die versteckte Lösung (die gesuchte Vokabel), dann alles, was Pixel auf Englisch gesagt hat
    for stelle in [*loesungen, *stimmen.englische_stellen(stimmen.ohne_loesung(antwort))]:
        stelle = stelle.strip(" .,!?;:\"'")
        if len(stelle) >= 2 and stelle.lower() not in {h.lower() for h in hinweise}:  # keine Tipps wie "b"
            hinweise.append(stelle)
    return hinweise[:MAX_HINWEISE]


def ist_abschied(text):
    return bool(_ABSCHIED.search(normalisiere(text)))


_STICKER_FRAGE = re.compile(r"\bsticker\b.*\b(habe|hab|zeig|sag|wie viele|welche)\b"
                            r"|\b(wie viele|welche|zeig|meine)\b.*\bsticker\b|^(mein )?(sticker|stickeralbum|album)$")


def ist_stickerfrage(text):
    return bool(_STICKER_FRAGE.search(normalisiere(text)))


# "Ich will Mathe üben", "Lass uns Englisch machen": direkt zur passenden Persönlichkeit (Lernplan oder Zuhören)
_FACHWUNSCH = re.compile(r"^(ich will|ich möchte|ich würde gerne?|ich mag|lass uns|lasst uns|können wir|kann ich|"
                         r"darf ich|wir wollen|wir möchten)\b")
FACH_WOERTER = {
    "mathe": ("mathe", "mathematik", "rechnen", "malrechnen", "einmaleins", "plus und minus", "kopfrechnen",
              "geteilt rechnen", "rechenaufgaben"),
    "deutsch": ("deutsch", "rechtschreibung", "grammatik", "nomen", "verben", "adjektive", "wortarten",
                "buchstabieren"),
    "englisch": ("englisch", "english", "vokabeln"),
    "hsu": ("sachkunde", "sachunterricht", "hsu", "heimat und sachunterricht", "heimatkunde"),
    "zuhoeren": ("zuhören", "zuhörprobe", "hörprobe", "zuhör übung", "zuhörübung"),
}


# Kurzform als ganze Äußerung: "Mathematik üben.", "Englisch lernen"
_FACH_KURZ = re.compile(r"^(?P<w>.+?) (üben|machen|lernen)$")


def fachwunsch(text):
    """Fach ("mathe", "deutsch", "englisch", "hsu", "zuhoeren") aus einem Wunsch wie "Ich will Mathe üben"
    oder kurz "Mathe üben"."""
    t = normalisiere(text)
    kurz = _FACH_KURZ.match(t)
    if kurz:
        for fach, woerter in FACH_WOERTER.items():
            if kurz.group("w") in woerter:
                return fach
    if not _FACHWUNSCH.search(t):
        return None
    for fach, woerter in FACH_WOERTER.items():
        if any(re.search(rf"\b{re.escape(w)}\b", t) for w in woerter):
            return fach
    return None


# Gemischte Erkennung (Deepgram language=multi, Mister Pixel) kennt neben Deutsch und Englisch auch Hindi, Spanisch,
# Französisch … und lässt sich laut Doku nicht beschränken. Am 23.10.2026 wurde daraus "खाने कीलन", "¿Cuál es su
# fecha?", "Ça est profasant flexur" (für "Sei Professor Pixel"). Schrift oder Zeichen, die es weder im Deutschen
# noch im Englischen gibt, verraten so eine Fehlerkennung.
_FREMD = re.compile(r"[^\x00-\x7FäöüÄÖÜß„“‚‘’–…€]")


def fremde_zeichen(text):
    return bool(_FREMD.search(text or ""))


def _woerter(text):
    return re.sub(r"[^\w\s]", " ", (text or "").lower()).split()


def passt_zur_loesung(text, loesungen):
    """Enthält der erkannte Text eine der erwarteten Lösungen als ganze Wörter ("Bird." passt zu "bird")?"""
    woerter = _woerter(text)
    for loesung in loesungen:
        gesucht = _woerter(loesung)
        if gesucht and any(woerter[i:i + len(gesucht)] == gesucht for i in range(len(woerter) - len(gesucht) + 1)):
            return True
    return False


# "Ich bin Anna und ich will Mathe üben", "Ich bin Ben, kann ich Englisch üben?"
_ANMELDUNG_MIT_REST = re.compile(r"^(?P<anmeldung>.+?)(?:\s*,\s*|\s+und\s+)(?P<rest>.+)$")


# ---------------------------------------------------------------------- Claude
def denk_einstellung(modell):
    """Nachdenken ausschalten: Es kostet Zeit, und die Denk-Tokens zählen gegen max_tokens.

    Laut Claude-Doku ist Nachdenken bei Haiku 5.5 und Sonnet 5.5 standardmäßig an.
    Haiku 5.5: thinking disabled. Sonnet 5.5: thinking between_tools (disabled ist dort ein Fehler).
    Bei anderen Modellen bleibt der Standard, dort sorgt nur das große max_tokens für Platz.
    """
    if "haiku" in modell:
        return {"thinking": {"type": "disabled"}}
    if "sonnet" in modell:
        return {"thinking": {"type": "between_tools"}}
    return {}


def frage_claude(client, modell, system, verlauf, sprecher, max_tokens=MAX_TOKENS, cache=False):
    """Streamt Claudes Antwort und übergibt fertige Sätze sofort an den Sprecher.

    cache: Prompt Caching (5 Minuten). Nur sinnvoll, wenn der System-Prompt von Frage zu Frage gleich bleibt;
    sonst kostet jedes Schreiben 1,25-fach ohne späteres Lesen. Zwei Merkpunkte: einer am System-Prompt (bleibt
    gültig, wenn der Verlauf gekürzt wird) und der automatische am Ende des Verlaufs. Mit nur dem automatischen
    kostete nach dem Kürzen jede Antwort den vollen Preis (19.10.2026: 31 Antworten zu 1,1 bis 1,9 statt 0,2 Cent,
    Tageslimit erreicht). Laut Doku zählt der automatische als einer von höchstens 4 Merkpunkten.

    Gibt (komplette Antwort, Sekunden bis zum ersten Satz, Gesamtsekunden, Stopp-Grund, Usage) zurück.
    """
    t0 = time.time()
    erster_satz = None
    puffer, gesamt = "", ""
    if cache:
        system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    with client.messages.stream(
        model=modell, max_tokens=max_tokens, system=system, messages=verlauf,
        **denk_einstellung(modell), **({"cache_control": {"type": "ephemeral"}} if cache else {}),
    ) as strom:
        for stueck in strom.text_stream:
            gesamt += stueck
            puffer += stueck
            saetze, puffer = zerlege_in_saetze(puffer)
            for satz in saetze:
                if erster_satz is None:
                    erster_satz = time.time() - t0
                sprecher.sprich(satz)
        nachricht = strom.get_final_message()
        stopp_grund = getattr(nachricht, "stop_reason", None)
        nutzung = getattr(nachricht, "usage", None)
    saetze, puffer = zerlege_in_saetze(puffer, ende=True)
    for satz in saetze:
        if erster_satz is None:
            erster_satz = time.time() - t0
        sprecher.sprich(satz)
    return gesamt.strip(), erster_satz, time.time() - t0, stopp_grund, nutzung


# US-Dollar pro Million Tokens: (Eingabe, Ausgabe). Quelle: platform.claude.com/docs/en/about-claude/pricing
# (Stand Oktober 2026). Haiku: Preis für Anfragen bis 100.000 Tokens, darüber kommen wir mit
# MAX_NACHRICHTEN nicht.
# Prompt Caching (5 Minuten): Schreiben 1,25-fach, Lesen 0,1-fach des Eingabepreises, bei Sonnet 5.5 nur
# 0,05-fach (Quelle: platform.claude.com/docs/en/about-claude/pricing, geprüft 18.10.2026). Mindestens 512 Tokens.
CACHE_SCHREIBEN = 1.25
CACHE_LESEN = {"claude-sonnet-5-5": 0.05}  # sonst CACHE_LESEN_STANDARD
CACHE_LESEN_STANDARD = 0.1
PREISE = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}


# Deepgram Nova-3 Monolingual (language=de), vorab aufgenommen, US-Dollar pro Minute.
# Quelle: deepgram.com/pricing (Stand Oktober 2026), abgerechnet sekundengenau.
DEEPGRAM_PREIS_MIN = 0.0043
DEEPGRAM_PREIS_MIN_MULTI = 0.0052  # Nova-3 Multilingual (language=multi, Deutsch und Englisch gemischt)
DEEPGRAM_PREIS_KEYTERM_MIN = 0.0013  # Aufschlag für Keyterm Prompting (Hinweiswörter), nur wenn welche gesendet werden
MAX_HINWEISE = 20                     # Deepgram empfiehlt 20 bis 50, Grenze 500 Tokens
ANMELDUNG_GILT_S = 30 * 60            # so lange bleibt ein Kind nach dem letzten Gespräch angemeldet

PROTOKOLL = Path(__file__).parent / "protokoll" / "kosten.csv"
PROTOKOLL_SPALTEN = ["zeitpunkt", "sitzung", "dienst", "modell", "audio_s", "tokens_ein", "tokens_aus",
                     "kosten_usd", "dauer_s", "status", "zeichen", "profil"]  # profil: "erwachsen" oder leer
# Wartezeit pro Antwort, alles in Sekunden. warten_s = pause_s + stt_s + Zeit bis zum ersten Ton
ZEITEN = Path(__file__).parent / "protokoll" / "zeiten.csv"
ZEITEN_SPALTEN = ["zeitpunkt", "sitzung", "modell", "audio_s", "pause_s", "stt_s", "claude_erster_satz_s",
                  "tts_erster_satz_s", "warten_s", "claude_gesamt_s", "zeichen_erster_satz", "stimme", "art"]
# Alte Spaltennamen in bestehenden Protokollen, werden beim Start umbenannt
SPALTEN_UMBENANNT = {"piper_erster_satz_s": "tts_erster_satz_s"}


def berechne_kosten(modell, nutzung):
    """Kosten einer Anfrage in US-Dollar, None bei unbekanntem Modell."""
    preise = PREISE.get(modell)
    if preise is None or nutzung is None:
        return None
    geschrieben = getattr(nutzung, "cache_creation_input_tokens", 0) or 0
    gelesen = getattr(nutzung, "cache_read_input_tokens", 0) or 0
    lesen = CACHE_LESEN.get(modell, CACHE_LESEN_STANDARD)
    eingabe = (nutzung.input_tokens + geschrieben * CACHE_SCHREIBEN + gelesen * lesen) * preise[0]
    return (eingabe + nutzung.output_tokens * preise[1]) / 1_000_000


class Protokoll:
    """Schreibt jede kostenpflichtige Anfrage als Zeile in eine CSV-Datei (für Excel: Semikolon,
    Dezimalkomma). Datensparsam: nur Zahlen, keine Texte von Fragen oder Antworten."""

    def __init__(self, pfad=PROTOKOLL, spalten=PROTOKOLL_SPALTEN, sitzung=None):
        self.pfad = pfad
        self.spalten = spalten
        self.sitzung = sitzung or time.strftime("%Y-%m-%d_%H-%M-%S")
        self.pfad.parent.mkdir(exist_ok=True)
        if not self.pfad.exists():
            with open(self.pfad, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f, delimiter=";").writerow(spalten)
        else:
            self._spalten_angleichen()

    def _spalten_angleichen(self):
        """Ältere Protokolle auf die aktuellen Spalten bringen (neue Spalten leer, alte Namen umbenannt),
        damit die Zeilen weiter zur Kopfzeile passen und die Tagessumme stimmt."""
        try:
            with open(self.pfad, newline="", encoding="utf-8-sig") as f:
                leser = csv.reader(f, delimiter=";")
                kopf = next(leser, [])
                zeilen = list(leser)
            kopf = [SPALTEN_UMBENANNT.get(s, s) for s in kopf]
            if kopf == self.spalten:
                return
            daten = [dict(zip(kopf, z)) for z in zeilen]
            with open(self.pfad, "w", newline="", encoding="utf-8-sig") as f:
                schreiber = csv.writer(f, delimiter=";")
                schreiber.writerow(self.spalten)
                for d in daten:
                    schreiber.writerow(d.get(s, "") for s in self.spalten)
            print(f"  [Protokoll] {self.pfad.name}: Spalten aktualisiert")
        except OSError as fehler:
            print(f"  [Protokoll] {self.pfad.name} nicht angepasst: {fehler}")

    def schreibe(self, **werte):
        def zelle(wert):
            if isinstance(wert, float):
                return f"{wert:.8f}".rstrip("0").rstrip(".").replace(".", ",")
            return "" if wert is None else wert

        werte = {"zeitpunkt": time.strftime("%Y-%m-%d %H:%M:%S"), "sitzung": self.sitzung, **werte}
        try:
            with open(self.pfad, "a", newline="", encoding="utf-8") as f:
                csv.writer(f, delimiter=";").writerow(zelle(werte.get(s)) for s in self.spalten)
        except OSError as fehler:  # z. B. Datei in Excel geöffnet: Gespräch läuft trotzdem weiter
            print(f"  [Protokoll] FEHLER: {fehler}")

    def summe_heute(self, erwachsen=False):
        """(Kosten in US-Dollar, Anzahl Claude-Antworten) von heute, auch aus früheren Sitzungen. Kinder und
        Erwachsene getrennt (eigene Limits); Zeilen ohne Profil zählen zu den Kindern."""
        heute = time.strftime("%Y-%m-%d")
        kosten, fragen = 0.0, 0
        try:
            with open(self.pfad, newline="", encoding="utf-8-sig") as f:
                for zeile in csv.DictReader(f, delimiter=";"):
                    if not (zeile.get("zeitpunkt") or "").startswith(heute):
                        continue
                    if (zeile.get("profil") == "erwachsen") != erwachsen:
                        continue
                    kosten += float((zeile.get("kosten_usd") or "0").replace(",", "."))
                    if zeile.get("dienst") == "claude" and zeile.get("status") != "fehler":
                        fragen += 1
        except (OSError, ValueError) as fehler:
            print(f"  [Protokoll] Tagessumme nicht lesbar: {fehler}")
        return kosten, fragen

    def zeichen_im_monat(self):
        """Gesprochene Zeichen der Cloud-Stimmen im laufenden Monat, je Preisgruppe (für die Freimenge)."""
        monat = time.strftime("%Y-%m")
        summen = {}
        try:
            with open(self.pfad, newline="", encoding="utf-8-sig") as f:
                for zeile in csv.DictReader(f, delimiter=";"):
                    if zeile.get("dienst") != "tts" or not (zeile.get("zeitpunkt") or "").startswith(monat):
                        continue
                    gruppe = zeile.get("status") or ""  # bei tts steht die Preisgruppe in status
                    summen[gruppe] = summen.get(gruppe, 0) + int(zeile.get("zeichen") or 0)
        except (OSError, ValueError) as fehler:
            print(f"  [Protokoll] Monatszeichen nicht lesbar: {fehler}")
        return summen


STATUS = Path(__file__).parent / "status.json"
LAEUFT_SCHON = 3     # Rückgabewert, wenn schon eine Instanz läuft (starte.py startet dann nicht neu)
STATUS_TAKT_S = 10  # so oft wird status.json auch ohne Zustandswechsel erneuert (Lebenszeichen)


class Status:
    """Schreibt status.json für die Oberfläche: Zustand und die tatsächlich laufenden Werte.

    Zustände: startet, wartet (auf das Wake Word), hoert_zu, antwortet (denkt nach), spricht, pausiert (Schlafenszeit
    oder Limit), aus. Ein Hintergrund-Thread frischt die Datei regelmäßig auf, damit die Oberfläche
    an 'aktualisiert' erkennt, ob das Programm noch läuft.
    """

    def __init__(self, pfad=STATUS):
        self.pfad = Path(pfad)
        self.zustand = "startet"
        self.hinweis = ""
        self.quelle = None  # Funktion, die die laufenden Werte liefert (Gespraech.status_werte)
        self.gestartet = time.strftime("%Y-%m-%d %H:%M:%S")
        self._sperre = threading.Lock()
        threading.Thread(target=self._takt, daemon=True).start()

    def melde(self, zustand, hinweis=""):
        self.zustand, self.hinweis = zustand, hinweis
        self.schreibe()

    def _takt(self):
        while True:
            time.sleep(STATUS_TAKT_S)
            if self.zustand != "aus":
                self.schreibe()

    def schreibe(self):
        daten = {"zustand": self.zustand, "hinweis": self.hinweis, "gestartet": self.gestartet,
                 "aktualisiert": time.time(), "pid": os.getpid()}
        if self.quelle:
            try:
                daten.update(self.quelle())
            except Exception as fehler:  # Status darf das Gespräch nie stören
                daten["fehler"] = str(fehler)
        with self._sperre:
            try:
                hilfsdatei = self.pfad.with_suffix(".tmp")
                hilfsdatei.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(hilfsdatei, self.pfad)
            except OSError as fehler:
                print(f"  [Status] FEHLER: {fehler}")


def prozess_laeuft(pid):
    """Ob der Prozess noch läuft. Unter Windows nicht mit os.kill(pid, 0): Das schickt dort Strg+C."""
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        griff = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not griff:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(griff, ctypes.byref(code))
        kernel32.CloseHandle(griff)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True


def laufende_instanz(pfad=STATUS):
    """Prozessnummer eines anderen laufenden Gesprächsprogramms laut status.json, sonst None."""
    try:
        daten = json.loads(Path(pfad).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = daten.get("pid")
    frisch = time.time() - daten.get("aktualisiert", 0) < 3 * STATUS_TAKT_S
    if daten.get("zustand") != "aus" and frisch and pid and pid != os.getpid() and prozess_laeuft(pid):
        return pid
    return None


# ------------------------------------------------------------------ Tagesgrenzen
class Grenzen:
    """Schlafenszeit und Tageslimits. Später einmal pro Kinderprofil denkbar."""

    def __init__(self, schlafenszeit="20:00-07:00", limit_cent=50.0, max_fragen=0, limit_cent_erwachsene=0.0):
        self.schlafenszeit = self._lies_zeitraum(schlafenszeit)
        self.limit_cent = limit_cent      # 0 = aus
        self.max_fragen = max_fragen      # 0 = aus
        # Erwachsene: keine Schlafenszeit, keine Fragengrenze, eigenes Kostenlimit (0 = aus)
        self.limit_cent_erwachsene = limit_cent_erwachsene

    @staticmethod
    def _lies_zeitraum(text):
        """'20:00-07:00' -> ((20, 0), (7, 0)), 'aus' -> None."""
        if not text or text.strip().lower() == "aus":
            return None
        try:
            von, bis = (tuple(int(x) for x in teil.strip().split(":")) for teil in text.split("-"))
        except ValueError:
            sys.exit(f"Schlafenszeit '{text}' nicht lesbar. Beispiel: 20:00-07:00 oder aus")
        return von, bis

    def ist_schlafenszeit(self, jetzt=None):
        if self.schlafenszeit is None:
            return False
        jetzt = jetzt or time.localtime()
        uhr = (jetzt.tm_hour, jetzt.tm_min)
        von, bis = self.schlafenszeit
        if von <= bis:
            return von <= uhr < bis
        return uhr >= von or uhr < bis  # über Mitternacht

    def minuten_bis_schlafenszeit(self, jetzt=None):
        """Ganze Minuten bis zum Beginn der Schlafenszeit (0 = schon Schlafenszeit), None = keine eingestellt."""
        if self.schlafenszeit is None:
            return None
        jetzt = jetzt or time.localtime()
        if self.ist_schlafenszeit(jetzt):
            return 0
        (vh, vm), _ = self.schlafenszeit
        return (vh * 60 + vm - jetzt.tm_hour * 60 - jetzt.tm_min) % (24 * 60)

    def beschreibung(self):
        teile = []
        if self.schlafenszeit:
            (vh, vm), (bh, bm) = self.schlafenszeit
            teile.append(f"Schlafenszeit {vh:02d}:{vm:02d}-{bh:02d}:{bm:02d}")
        if self.limit_cent:
            teile.append(f"höchstens {self.limit_cent:g} US-Cent pro Tag")
        if self.max_fragen:
            teile.append(f"höchstens {self.max_fragen} Fragen pro Tag")
        if self.limit_cent_erwachsene:
            teile.append(f"Erwachsene höchstens {self.limit_cent_erwachsene:g} US-Cent pro Tag")
        return ", ".join(teile) or "keine"


def lies_anthropic_schluessel():
    # Eigener Name zuerst: ANTHROPIC_API_KEY global gesetzt würde auch Claude Code benutzen
    for variable in ("PIDOG_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"):
        schluessel = os.environ.get(variable, "").strip()
        if schluessel:
            return schluessel
    sys.exit(
        "Umgebungsvariable PIDOG_ANTHROPIC_API_KEY fehlt.\n"
        "Schlüssel erzeugen in der Claude Console (platform.claude.com), dann einmalig in PowerShell:\n"
        "  [Environment]::SetEnvironmentVariable(\"PIDOG_ANTHROPIC_API_KEY\", (Read-Host \"Schlüssel\"), \"User\")\n"
        "Danach ein neues Fenster öffnen."
    )


class Gespraech:
    """Bündelt Claude-Client, Verlauf und Sprachausgabe für ein laufendes Gespräch."""

    schlafenszeit_kind = False  # Schlafenszeit, aber ein Erwachsener könnte sich noch anmelden (grenze_erreicht)
    einstellungen = None        # Einstellungsdatei (Tests bauen Gespraech teils ohne __init__)
    unsicher = None             # andere Erkennung, wenn beide uneinig sind und keine zur Lösung passt
    unsicher_folge = 0          # so oft hintereinander deshalb nachgefragt

    def __init__(self, client, modell, system, voice, erkenne, protokoll=None, grenzen=None, stufe=5,
                 zeiten=None, einstellungen=None, folge_s=6.0, ack="Ja?", status=None,
                 persoenlichkeiten=None, aktiv=pers.STANDARD, kinder=None):
        self.client = client
        self.kinder = kinder                        # kinder.json, None = keine (z. B. in Tests)
        self.lernplan = ""                          # Lernplan der aktiven Persönlichkeit ("englisch" oder "")
        self.gute_nacht = True                      # Gute-Nacht-Modus bei Geschichtenwunsch (Persönlichkeit)
        self.lernzeit = False                       # Aufgaben werden bewertet, Sticker (Persönlichkeit)
        self.serie = 0                              # richtige Antworten in Folge im laufenden Gespräch
        self.stickerordner = sticker_mod.ORDNER     # Sticker-Alben je Kind
        self.sticker_anlass = []                    # (Grund, golden) aus lerne/lerne_thema, in beantworte verteilt
        self._plan = None                           # geladener Lernplan (lernplan_englisch.json)
        self.lernordner = lernkartei.ORDNER         # Lernkarteien je Kind
        # Sprechpause aus den Einstellungen (Kinder können abweichen)
        self.pause_basis = einstellungen.werte.get("pause", 1.2) if einstellungen else 1.2
        self.kind = (einstellungen["kind"] if einstellungen else "") or ""
        if self.kind and not (kinder and kinder.hole(self.kind)):
            self.kind = ""                          # Profil gelöscht
        self.persoenlichkeiten = persoenlichkeiten  # persoenlichkeiten.json, None = keine (z. B. in Tests)
        self.aktiv = aktiv                          # Kennung der aktiven Persönlichkeit
        self.status = status                # status.json für die Oberfläche, None = keine
        self.hoerer = None                  # wird in main gesetzt, für Status und Wake-Word-Wechsel
        werte = einstellungen.werte if einstellungen else {}
        self.modell_geschichte = werte.get("modell_geschichte", "claude-sonnet-5-5")
        self.stimme_geschichte = werte.get("stimme_geschichte", "")  # "" = wie im Gespräch
        self._geschichten_voice = None      # geladene Stimme für Geschichten (Kennung, Stimme)
        self.erkennung = "de"               # Deepgram: "de" oder "multi" (Deutsch und Englisch gemischt)
        self.stimme_englisch = ""           # Stimme für <en>…</en>, "" = keine
        self._englische_voice = None        # geladene englische Stimme (Kennung, Stimme)
        self.geschichte_bis = werte.get("geschichte_bis", "20:30")
        self.geschichten_prompt = werte.get("geschichten_prompt") or GESCHICHTEN_PROMPT
        self.letzte_geschichte = 0.0        # Zeitpunkt der letzten Geschichte (eine pro Abend)
        self.nur_geschichte = False         # Schlafenszeit, aber eine Geschichte ist noch erlaubt
        self.einstellungen = einstellungen  # Einstellungsdatei, None = keine (z. B. in Tests)
        self.folge_s = folge_s              # Sekunden für Folgefragen ohne Wake Word
        self.ack = ack                      # Text nach dem Wake Word, leer = Piepton
        self._bestaetigung = None
        self._ersatz = voice if getattr(voice, "kennung", None) == stimmen.STANDARD_STIMME else None
        self.modell = modell
        self.system = system
        self.voice = voice
        self.erkenne = erkenne
        self.protokoll = protokoll
        self.zeiten = zeiten          # Protokoll für die Wartezeiten
        self.messung = None           # Zeiten der laufenden Frage, ab Ende der Aufnahme
        self.wartezeiten = []         # Wartezeit bis zum ersten Ton, je Antwort dieser Sitzung
        self.grenzen = grenzen or Grenzen(schlafenszeit="aus", limit_cent=0)
        self.stufe = stufe  # Lautstärke 1 bis len(LAUTSTAERKE_STUFEN)
        self.verlauf = []
        self.letzte_antwort = ""
        self.letzte_aktivitaet = time.time()
        self.kosten = {"claude": 0.0, "deepgram": 0.0, "tts": 0.0}  # seit Programmstart, in US-Dollar
        self.anfragen = {"claude": 0, "deepgram": 0, "tts": 0}
        # Tageswerte, auch aus früheren Sitzungen von heute
        self.heute = time.strftime("%Y-%m-%d")
        self.heute_kosten, self.heute_fragen = protokoll.summe_heute() if protokoll else (0.0, 0)
        self.heute_kosten_erwachsene = protokoll.summe_heute(erwachsen=True)[0] if protokoll else 0.0
        self.schlafenszeit_kind = False     # Schlafenszeit, aber ein Erwachsener könnte sich noch anmelden
        # Zeichen der Cloud-Stimmen in diesem Monat, je Preisgruppe (Google-Freimenge)
        self.monat = time.strftime("%Y-%m")
        self.monatszeichen = protokoll.zeichen_im_monat() if protokoll else {}
        # Geschichten-Werte der aktiven Persönlichkeit (Modell, Stimme und Prompt für Gespräche kommen
        # als Parameter, damit Startoptionen sie für einen Lauf überschreiben können)
        aktuelle = persoenlichkeiten.hole(aktiv) if persoenlichkeiten else None
        if aktuelle:
            self.modell_geschichte = aktuelle["modell_geschichte"]
            self.stimme_geschichte = aktuelle["stimme_geschichte"]
            self.geschichten_prompt = aktuelle["geschichten_prompt"] or GESCHICHTEN_PROMPT
            self.erkennung = aktuelle["erkennung"]
            self.stimme_englisch = aktuelle["stimme_englisch"]
            self.lernplan = aktuelle["lernplan"]
            self.gute_nacht = aktuelle["gute_nacht"]
            self.lernzeit = aktuelle["spielzeit"]
            self.englische_stimme()  # vorladen, sonst dauert die erste Antwort mehrere Sekunden länger

    @property
    def lautstaerke(self):
        return LAUTSTAERKE_STUFEN[self.stufe - 1]

    def grenze_erreicht(self):
        """Gibt einen Satz zum Vorlesen zurück, wenn gerade nicht geantwortet werden soll, sonst None."""
        if time.strftime("%Y-%m-%d") != self.heute:  # neuer Tag
            self.heute = time.strftime("%Y-%m-%d")
            self.heute_kosten, self.heute_fragen, self.heute_kosten_erwachsene = 0.0, 0, 0.0
        g = self.grenzen
        self.nur_geschichte = False
        self.schlafenszeit_kind = False
        if self.ist_erwachsen:  # keine Schlafenszeit, keine Fragengrenze, eigenes Kostenlimit
            if g.limit_cent_erwachsene and self.heute_kosten_erwachsene * 100 >= g.limit_cent_erwachsene:
                print(f"  [Grenze] Tageslimit Erwachsene erreicht: {self.heute_kosten_erwachsene * 100:.2f} US-Cent")
                self.melde("pausiert", "Tageslimit Kosten (Erwachsene)")
                return "Das Kostenlimit für Erwachsene ist für heute erreicht. Morgen geht es weiter."
            return None
        if g.ist_schlafenszeit():
            erwachsene = self.kinder and any(kinder_mod.ist_erwachsen(k) for k in self.kinder.daten.values())
            if self.geschichte_erlaubt():
                print("  [Grenze] Schlafenszeit, eine Gute-Nacht-Geschichte ist noch erlaubt")
                self.nur_geschichte = True
                self.schlafenszeit_kind = True
                self.melde("pausiert", "Schlafenszeit, nur Geschichte")
                return None
            if erwachsene:  # zuhören, falls sich ein Erwachsener anmeldet ("Ich bin Papa")
                print("  [Grenze] Schlafenszeit, nur Erwachsene")
                self.schlafenszeit_kind = True
                self.melde("pausiert", "Schlafenszeit, nur Erwachsene")
                return None
            print("  [Grenze] Schlafenszeit")
            self.melde("pausiert", "Schlafenszeit")
            return SCHLAFENSZEIT
        if g.limit_cent and self.heute_kosten * 100 >= g.limit_cent:
            print(f"  [Grenze] Tageslimit erreicht: {self.heute_kosten * 100:.2f} US-Cent")
            self.melde("pausiert", "Tageslimit Kosten")
            return "Ich habe heute schon so viel geredet und brauche eine Pause. Morgen bin ich wieder für dich da."
        if g.max_fragen and self.heute_fragen >= g.max_fragen:
            print(f"  [Grenze] Tageslimit erreicht: {self.heute_fragen} Fragen")
            self.melde("pausiert", "Tageslimit Fragen")
            return "Ich habe heute schon so viel geredet und brauche eine Pause. Morgen bin ich wieder für dich da."
        return None

    def geschichte_erlaubt(self, jetzt=None):
        """Während der Schlafenszeit: noch eine Geschichte, wenn es vor 'geschichte_bis' ist, die
        Schlafenszeit erst am Abend begonnen hat und heute Abend noch keine erzählt wurde."""
        if self.geschichte_bis == "aus" or not self.grenzen.schlafenszeit:
            return False
        if time.time() - self.letzte_geschichte < 12 * 3600:
            return False
        jetzt = jetzt or time.localtime()
        uhr = (jetzt.tm_hour, jetzt.tm_min)
        von = self.grenzen.schlafenszeit[0]
        bis = tuple(int(x) for x in self.geschichte_bis.split(":"))
        return von <= uhr < bis

    # ------------------------------------------------------------------- Status
    def melde(self, zustand, hinweis=""):
        if self.status:
            self.status.melde(zustand, hinweis)

    def status_werte(self):
        """Tatsächlich laufende Werte für status.json (können von der Einstellungsdatei abweichen)."""
        w = sorted(self.wartezeiten)
        return {
            "wakeword": getattr(self.hoerer, "wakeword", None),
            "persoenlichkeit": self.aktiv,
            "persoenlichkeit_name": self.persoenlichkeit_name,
            "kind": self.kind,
            "lernplan": self.lernplan,
            "modell": self.modell,
            "stimme": getattr(self.voice, "kennung", None),
            "lautstaerke": self.stufe,
            "folge": self.folge_s,
            "heute_kosten_cent": round(self.heute_kosten * 100, 4),
            "heute_fragen": self.heute_fragen,
            "heute_kosten_erwachsene_cent": round(self.heute_kosten_erwachsene * 100, 4),
            "erwachsen": self.ist_erwachsen,
            "limit_cent": self.grenzen.limit_cent,
            "max_fragen": self.grenzen.max_fragen,
            "schlafenszeit_jetzt": self.grenzen.ist_schlafenszeit(),
            "sitzung_kosten_cent": {k: round(v * 100, 4) for k, v in self.kosten.items()},
            "letzte_wartezeit_s": round(self.wartezeiten[-1], 2) if w else None,
            "median_wartezeit_s": round(w[len(w) // 2], 2) if w else None,
            "antworten": len(w),
            "modell_geschichte": self.modell_geschichte,
            "stimme_geschichte": self.stimme_geschichte,
            "erkennung": self.erkennung,
            "stimme_englisch": self.stimme_englisch,
            "geschichte_bis": self.geschichte_bis,
            "geschichte_heute": time.time() - self.letzte_geschichte < 12 * 3600,
            "system_prompt_eigen": self.system != SYSTEM_PROMPT,
            "geschichten_prompt_eigen": self.geschichten_prompt != GESCHICHTEN_PROMPT,
        }

    # ------------------------------------------------------------- Einstellungen
    def merke(self, name, wert):
        """Änderung speichern, damit die Oberfläche sie zeigt: Modell, Stimme, Lautstärke usw. in der aktiven
        Persönlichkeit, alles andere in der Einstellungsdatei."""
        if name in pers.FELDER and self.persoenlichkeiten:
            self.persoenlichkeiten.setze(self.aktiv, name, wert)
        elif self.einstellungen:
            self.einstellungen.setze(name, wert)

    # ---------------------------------------------------------------- Persönlichkeiten
    @property
    def persoenlichkeit_name(self):
        p = self.persoenlichkeiten.hole(self.aktiv) if self.persoenlichkeiten else None
        return p["name"] if p else "Pixel"

    def wende_persoenlichkeit_an(self, pid):
        """Alle Werte einer Persönlichkeit übernehmen. Nicht vorgesehene Modelle und nicht ladbare
        Stimmen werden gemeldet und in der Datei durch den laufenden Wert ersetzt."""
        p = self.persoenlichkeiten.hole(pid)
        self.aktiv = pid
        for feld in ("modell", "modell_geschichte"):
            if p[feld] in MODELLE:
                setattr(self, feld, p[feld])
            else:
                print(f"  [Persönlichkeit] {feld} {p[feld]} nicht vorgesehen, bleibt {getattr(self, feld)}")
                self.persoenlichkeiten.setze(pid, feld, getattr(self, feld))
        self.system = p["system_prompt"] or SYSTEM_PROMPT
        self.geschichten_prompt = p["geschichten_prompt"] or GESCHICHTEN_PROMPT
        self.stimme_geschichte = p["stimme_geschichte"]
        self.erkennung = p["erkennung"]
        self.stimme_englisch = p["stimme_englisch"]
        self.lernplan = p["lernplan"]
        self.gute_nacht = p["gute_nacht"]
        self.lernzeit = p["spielzeit"]
        self.stufe = p["lautstaerke"]
        self.ack = p["bestaetigung"]
        if p["stimme"] != getattr(self.voice, "kennung", None) and not self.wechsle_stimme(p["stimme"]):
            self.persoenlichkeiten.setze(pid, "stimme", self.voice.kennung)
        self.englische_stimme()  # jetzt laden, nicht erst bei der ersten Antwort (Piper-Ersatz dauert Sekunden)
        print(f"  Persönlichkeit: {p['name']} ({self.modell}, {getattr(self.voice, 'kennung', '?')})")

    def wechsle_persoenlichkeit(self, pid, ansage=False):
        """Zur Persönlichkeit wechseln, in den Einstellungen merken und auf Wunsch vorstellen."""
        if not self.persoenlichkeiten or not self.persoenlichkeiten.hole(pid):
            return False
        self.wende_persoenlichkeit_an(pid)
        if self.einstellungen and self.einstellungen["persoenlichkeit"] != pid:
            self.einstellungen.setze("persoenlichkeit", pid)
        vorstellung = self.persoenlichkeiten.hole(pid)["vorstellung"]
        if ansage and vorstellung:
            self.sage(vorstellung)  # in der neuen Stimme und Lautstärke
        return True

    # ---------------------------------------------------------------- Kinderprofile
    @property
    def kind_daten(self):
        return self.kinder.hole(self.kind) if self.kinder and self.kind else None

    @property
    def ist_erwachsen(self):
        return kinder_mod.ist_erwachsen(self.kind_daten)

    def mit_kind(self, system, geschichte=False):
        """System-Prompt plus Klasse des aktiven Kindes (nie der Name) und die anderen Persönlichkeiten.
        Bleibt während eines Gesprächs gleich, damit der Cache greift (Wortlisten kommen danach)."""
        k = self.kind_daten
        if self.ist_erwachsen and geschichte:
            system += ("\n\nDie Geschichte ist für einen Erwachsenen: anspruchsvollere Sprache, Bilder und Gedanken, "
                       "Länge und ruhiger Ton wie oben. Namen siehst du als [Name], das ist Absicht.")
        elif self.ist_erwachsen:
            # Vorne und hinten: Die Kinder-Regeln der Persönlichkeiten sind ausführlich und setzen sich sonst durch
            system = ("Diesmal sprichst du mit einem Erwachsenen auf Hochschulniveau, nicht mit einem Kind. Die "
                      "Anweisungen unten sind für Kinder geschrieben. Übernimm daraus deine Rolle, deine Themen und "
                      "die Form (Marken, Ablauf), aber nicht das Kinderniveau. Einzelheiten am Ende.\n\n"
                      f"{system}\n\nWichtig, das geht allen Regeln oben vor: Du sprichst mit einem Erwachsenen und "
                      "arbeitest auf Hochschulniveau. Keine vereinfachte Sprache, Fachbegriffe sind erwünscht, du "
                      "verweist nicht an Eltern, und Aufgaben rechnest oder löst du vollständig, wenn danach gefragt "
                      "wird. Antworte in drei bis sechs Sätzen, auf Nachfrage ausführlicher. Übungen und Aufgaben "
                      "deiner Rolle stellst du auf Hochschulniveau: Mathe wie im Studium (Analysis, lineare Algebra, "
                      "Stochastik), Hörtexte wie ein kurzer Fachvortrag mit bis zu 400 Wörtern. Englisch auf Niveau "
                      "C1 und überwiegend auf Englisch: Gespräch über anspruchsvolle Themen, Redewendungen, "
                      "Synonyme, Grammatik und Fachwortschatz, keine Grundwortschatz-Abfragen wie Hund oder Farben. "
                      "Alles wird vorgelesen: weiterhin keine Formatierung, Listen oder Emojis, Formeln in Worten. "
                      "Sprich nicht darüber, dass das Gegenüber erwachsen ist oder welche Regeln gelten, leg einfach "
                      "los. Namen siehst du als [Name], das ist Absicht.")
        elif k:
            system = (f"{system}\n\nDas Kind, mit dem du gerade sprichst, geht "
                      f"{kinder_mod.klasse_text(k['klasse'])}. Passe Wortwahl, Erklärungen und Aufgaben daran an. "
                      "Namen siehst du als [Name], das ist Absicht.")
        elif self.kinder and self.kinder.daten:
            system += ("\n\nGerade ist kein Kind angemeldet. Frag nicht nach Klasse oder Alter. Erinnere einmal "
                       "freundlich daran, dass sich das Kind mit Ich bin und seinem Namen anmelden kann, dann weißt "
                       "du, welche Aufgaben passen, und der Lernstand wird gespeichert.")
        if k and self.lernzeit and self.einstellungen and not self.ist_erwachsen:
            system += ("\n\nBewertung: Für richtig gelöste Aufgaben sammelt das Kind Sticker. "
                       "Antwortet das Kind auf eine Aufgabe, die du gestellt hast (Rechenaufgabe, Abfrage, Frage zu "
                       "einem Text), beginne deine Antwort mit <ergebnis>richtig</ergebnis> oder "
                       "<ergebnis>falsch</ergebnis>. Die Marke wird nicht vorgelesen. Bei allem anderen schreibst du "
                       "keine. Stell Aufgaben passend zur Klasse, keine geschenkten, und verrate die Lösung nicht "
                       "vorher.")
        andere = [p for pid, p in (self.persoenlichkeiten.daten.items() if self.persoenlichkeiten else [])
                  if pid != self.aktiv and p["per_sprache"]]
        if andere:
            liste = "\n".join(f"- {p['name']}" + (f": {p['beschreibung']}" if p["beschreibung"] else "")
                               for p in andere)
            system += ("\n\nAndere Persönlichkeiten von Pixel, zu denen das Kind selbst wechseln kann:\n" + liste
                       + "\nMöchte das Kind etwas, wofür eine andere besser passt, schlag den Wechsel vor und nenne "
                         "den Satz dafür (zum Beispiel: Sag einfach: Sei Professor Pixel). Schick es nicht weg.")
        return system

    @property
    def sprechpause(self):
        return kinder_mod.sprechpause(self.kind_daten, self.pause_basis)

    def pruefe_anmeldung_abgelaufen(self, jetzt=None):
        """Nach ANMELDUNG_GILT_S ohne Gespräch ist kein Kind mehr angemeldet (sonst übt das nächste Kind
        mit dem Profil des vorigen)."""
        jetzt = jetzt or time.time()
        if self.kind and jetzt - self.letzte_aktivitaet > ANMELDUNG_GILT_S:
            self.abmelden(f"länger als {ANMELDUNG_GILT_S // 60} Minuten kein Gespräch")

    def abmelden(self, grund):
        """Niemand mehr angemeldet: Das nächste Kind meldet sich mit "Ich bin …" an."""
        if not self.kind:
            return
        print(f"  Kind: {self.kind} abgemeldet ({grund})")
        self.kind = ""
        self.neu()
        if self.einstellungen:
            self.einstellungen.setze("kind", "")

    def kartei(self):
        """Lernkartei des aktiven Kindes, wenn die Persönlichkeit einen Lernplan hat, sonst None.
        Wird jedes Mal frisch gelesen, weil die Oberfläche Stufe und Karten ändern kann."""
        k = self.kind_daten
        if self.lernplan != "englisch" or not k or self.ist_erwachsen:  # Lernplan ist Grundschulstoff
            return None
        try:
            if self._plan is None:
                self._plan = lernkartei.Lernplan()
            return lernkartei.Lernkartei(self.kind, k["klasse"], self._plan, self.lernordner)
        except (OSError, ValueError, KeyError) as fehler:
            print(f"  [Lernkartei] nicht lesbar: {fehler}")
            return None

    def themenstand(self):
        """Lernstand des aktiven Kindes in Mathe, Deutsch oder HSU (Lernplan der Persönlichkeit), sonst None.
        Jedes Mal frisch gelesen, weil die Oberfläche Stufe und Thema ändern kann."""
        k = self.kind_daten
        if self.lernplan not in lernthemen.FAECHER or not k or self.ist_erwachsen:
            return None
        try:
            return lernthemen.Lernstand(self.kind, k["klasse"], self.lernplan, self.lernordner)
        except (OSError, ValueError, KeyError) as fehler:
            print(f"  [Lernplan] nicht lesbar: {fehler}")
            return None

    def lerne_thema(self, vorige_antwort, antwort):
        """Lernstand in Mathe, Deutsch, HSU fortschreiben: Bewertung (<ergebnis>) für das Thema der vorigen Aufgabe
        (<thema>), Wahl des Kindes (neues <thema> in der Antwort) und Schwierigkeit (<niveau>). Gibt einen Satz
        zurück, wenn ein Thema geschafft ist."""
        stand = self.themenstand()
        if not stand:
            return None
        geaendert, satz = False, None
        richtig = stimmen.ergebnis(antwort)
        vorher = stimmen.themen(vorige_antwort or "")
        karten = stimmen.aufgaben(vorige_antwort or "")
        if richtig is not None and karten:
            kasten = einmaleins.Kartei(self.kind, self.lernordner)
            if kasten.bewerte(karten[0], richtig):
                kasten.speichere()
                k = kasten.karten[karten[0]]
                print(f"  [Einmaleins] {karten[0]}: {'richtig' if richtig else 'falsch'} -> Fach {k['fach']}")
        if richtig is not None and vorher:
            kennung = vorher[0]
            if kennung in stand.plan.themen:
                alt = stand.plan.stufe(stand.stufe)["name"]
                name = stand.plan.themen[kennung]["name"]
                war_meister = bool(stand.themen.get(kennung, {}).get("meister"))
                ereignis = stand.bewerte(kennung, richtig)
                if ereignis:
                    self.sticker_anlass.append((f"{lernthemen.fach_name(stand.fach)}: {name}", False))
                if not war_meister and stand.themen[kennung].get("meister"):
                    self.sticker_anlass.append((f"{lernthemen.fach_name(stand.fach)}: {name} auf schwer", True))
                geaendert = True
                t = stand.themen[kennung]
                print(f"  [Lernplan] {name} ({stand.niveau}): {'richtig' if richtig else 'falsch'} "
                      f"({sum(t['ergebnisse'])} von {len(t['ergebnisse'])} zuletzt richtig)")
                if ereignis and ereignis[0] == "stufe":
                    satz = (f"Toll! Du hast alle Themen von {alt} geschafft. Ich schlage dir ab jetzt auch Themen aus "
                            f"{stand.plan.stufe(stand.stufe)['name']} vor.")
                elif ereignis:
                    satz = (f"Super! {name} kannst du jetzt richtig gut. Du kannst weiter üben, es schwerer probieren "
                            "oder dir ein anderes Thema aussuchen.")
            else:
                print(f"  [Lernplan] Thema '{kennung}' gibt es nicht, nicht gewertet")
        neu = [k for k in stimmen.themen(antwort) if k in stand.plan.themen]
        if neu and stand.waehle(neu[0]):  # das Kind hat sich ein (anderes) Thema ausgesucht
            print(f"  [Lernplan] gewählt: {stand.plan.themen[neu[0]]['name']}")
            geaendert = True
        niveau = stimmen.niveau(antwort)
        if niveau and stand.setze_niveau(niveau):
            print(f"  [Lernplan] Schwierigkeit: {niveau}")
            geaendert = True
        if geaendert:
            stand.speichere()
        return satz

    def lerne(self, vorige_antwort, antwort):
        """Bewertung aus Claudes Antwort (<ergebnis>) in die Lernkartei eintragen. Welcher Eintrag gemeint
        war, steht in der versteckten Lösung der vorigen Frage. Gibt die neue Stufe zurück, wenn aufgestiegen."""
        richtig = stimmen.ergebnis(antwort)
        loesungen = stimmen.loesungen(vorige_antwort or "")
        kartei = self.kartei()
        if kartei:  # Wahl des Kindes: Thema und Schwierigkeit (versteckte Marken in Claudes Antwort)
            gewaehlt = [t for t in stimmen.themen(antwort) if t in {x.lower() for x in kartei.themen()} | {"gemischt"}]
            if gewaehlt:
                neu_thema = "" if gewaehlt[0] == "gemischt" else next(x for x in kartei.themen() if x.lower() == gewaehlt[0])
                if neu_thema != kartei.thema:
                    kartei.thema = neu_thema
                    print(f"  [Lernkartei] Thema: {neu_thema or 'gemischt'}")
                    kartei.speichere()
            niveau = stimmen.niveau(antwort)
            if niveau in lernkartei.NIVEAUS and niveau != kartei.niveau:
                kartei.niveau = niveau
                print(f"  [Lernkartei] Schwierigkeit: {niveau}")
                kartei.speichere()
        if not kartei or richtig is None or not loesungen:
            return None
        kennung = kartei.plan.finde(loesungen[0])
        if not kennung:
            print(f"  [Lernkartei] '{loesungen[0]}' steht nicht im Lernplan, nicht gewertet")
            return None
        neu = kartei.bewerte(kennung, richtig)
        kartei.speichere()
        album = self.album()
        if album:
            gekonnt = sum(1 for c in kartei.karten.values() if c["fach"] >= lernkartei.GEKONNT_AB)
            while gekonnt >= album.englisch_belohnt + sticker_mod.STICKER_JE_WOERTER:
                album.englisch_belohnt += sticker_mod.STICKER_JE_WOERTER
                self.sticker_anlass.append((f"Englisch: {album.englisch_belohnt} Wörter gekonnt", False))
            album.speichere()
        k = kartei.karten[kennung]
        print(f"  [Lernkartei] {kartei.plan.eintraege[kennung]['en']}: {'richtig' if richtig else 'falsch'} "
              f"-> Fach {k['fach']}, wieder ab {k['faellig']}")
        if neu:
            print(f"  [Lernkartei] Stufe {neu} erreicht")
        return neu

    # ---------------------------------------------------------------- Sticker und Serien
    def nachgeholte_sticker(self, album, offen=()):
        """Sticker für Themen in Mathe, Deutsch, Sachkunde, die schon geschafft waren, bevor es Sticker gab
        (18.10.2026), oder deren Sticker fehlt. Gezählt je Grund (Fach und Themenname, golden für schwer), so gibt
        es für jedes geschaffte Thema genau einen, auch bei gleichnamigen Themen in mehreren Klassen.
        offen: Anlässe dieser Antwort, die gerade verteilt werden."""
        k = self.kind_daten
        if not k:
            return []
        soll = Counter()
        for fach in lernthemen.FAECHER:
            try:
                stand = lernthemen.Lernstand(self.kind, k["klasse"], fach, self.lernordner)
            except (OSError, ValueError, KeyError):
                continue
            for kennung, t in stand.themen.items():
                grund = f"{lernthemen.fach_name(fach)}: {stand.plan.themen[kennung]['name']}"
                if t.get("gekonnt"):
                    soll[(grund, False)] += 1
                if t.get("meister"):
                    soll[(f"{grund} auf schwer", True)] += 1
        hat = Counter((st.get("grund"), bool(st.get("gold"))) for st in album.sticker) + Counter(offen)
        return [anlass for anlass, anzahl in (soll - hat).items() for _ in range(anzahl)]

    def album(self):
        """Sticker-Album des angemeldeten Kindes (nicht für Erwachsene), sonst None."""
        if not self.kind_daten or self.ist_erwachsen:
            return None
        return sticker_mod.Album(self.kind, self.stickerordner)

    def tagebuch(self):
        if not self.kind_daten or self.ist_erwachsen:
            return None
        return tagebuch_mod.Tagebuch(self.kind, self.lernordner)

    @property
    def fach_name(self):
        """Name des Fachs fürs Tagebuch: Lernplan, sonst die Persönlichkeit (z. B. Zuhör-Pixel)."""
        return {"englisch": "Englisch", "mathe": "Mathe", "deutsch": "Deutsch", "hsu": "Sachkunde"}.get(
            self.lernplan, self.persoenlichkeit_name)

    def belohnungen(self, antwort):
        """Nach einer Antwort: Sticker verteilen, Serie und Tagesrekord zählen. Gibt [(Ton, Satz)] zum Sprechen
        zurück. Nur bei Persönlichkeiten, bei denen Lernen zählt."""
        album = self.album() if self.lernzeit else None
        anlaesse, self.sticker_anlass = self.sticker_anlass, []
        richtig = stimmen.ergebnis(antwort)
        if not album or (richtig is None and not anlaesse):
            return []
        nachholen = self.nachgeholte_sticker(album, anlaesse) if richtig is not None else []
        saetze = []
        neue = []
        for grund, gold in anlaesse + nachholen:
            neue.append(album.neuer_sticker(grund, gold))
            print(f"  [Sticker] {album.name(neue[-1])} für {grund}" + (" (nachgeholt)" if (grund, gold) in nachholen else ""))
        if neue:
            vorweg = "Für Themen, die du schon geschafft hast, bekommst du noch Sticker. " if nachholen else ""
            saetze.append((TON_STICKER, vorweg + album.ansage(neue)))
        if richtig is not None:  # Tagebuch (Wochenbericht) und Tagesziel
            buch = self.tagebuch()
            buch.antwort(self.fach_name, richtig)
            ziel = int(self.einstellung("tagesziel"))
            if richtig and ziel and not buch.heute()["ziel"] and buch.richtig_heute() >= ziel:
                buch.heute()["ziel"] = True
                print("  [Tagesziel] erreicht")
                saetze.append((TON_SERIE, f"Tagesziel geschafft: {ziel} Aufgaben richtig!"))
            buch.speichere()
        if richtig is True:
            self.serie += 1
            rekord = album.zaehle_richtig()
            if self.serie % sticker_mod.SERIE_ALLE == 0:
                saetze.append((TON_SERIE, f"{self.serie} richtige in Folge!"))
            if rekord:
                saetze.append((TON_SERIE, f"Neuer Rekord: Heute schon {rekord} Aufgaben richtig!"))
        elif richtig is False:
            self.serie = 0
        album.speichere()
        return saetze

    def wechsle_kind(self, kid, ansage=True):
        """Anderes Kind ist jetzt dran: Verlauf leeren (gehört zum vorigen Kind), merken, begrüßen."""
        k = self.kinder.hole(kid) if self.kinder else None
        if not k:
            return False
        if kid != self.kind:
            self.neu()
            self.sticker_anlass = []
        self.kind = kid
        if self.einstellungen and self.einstellungen["kind"] != kid:
            self.einstellungen.setze("kind", kid)
        print(f"  Kind: {kid} ({kinder_mod.klasse_text(k['klasse'])})")
        if ansage:
            self.sage(f"Hallo {k['name']}, schön, dass du da bist!")
        return True

    def pruefe_anmeldung(self, frage):
        """'Ich bin Anna': True (weiter zuhören), None wenn es keine Anmeldung eines bekannten Kindes ist."""
        if not self.kinder:
            return None
        if normalisiere(frage) in ("wer bin ich", "weißt du wer ich bin", "weisst du wer ich bin"):
            k = self.kind_daten
            self.sage(f"Du bist {k['name']}." if k else
                      "Das weiß ich noch nicht. Sag einfach: Ich bin, und dann deinen Namen.")
            return True
        bezeichnung = kinder_mod.pruefe_anmeldung(frage)
        kid = self.kinder.finde(bezeichnung) if bezeichnung else None
        if not kid:
            return None  # "Ich bin müde" ist eine normale Äußerung
        print(f"  [Befehl] Anmeldung Kind {kid}")
        self.wechsle_kind(kid)
        self.letzte_aktivitaet = time.time()
        return True

    def anmeldung_und_rest(self, frage):
        """("Ich bin Anna", "Wie viele Sticker habe ich?") für "Ich bin Anna. Wie viele …" oder "Ich bin Anna und
        ich will Mathe üben", wenn der erste Teil ein bekanntes Kind anmeldet, sonst None."""
        if not self.kinder:
            return None
        frage = frage.strip()
        teile = re.split(r"(?<=[.!?])\s+", frage, maxsplit=1)
        kandidaten = [tuple(teile)] if len(teile) == 2 else []
        mit_rest = _ANMELDUNG_MIT_REST.match(frage)
        if mit_rest:
            kandidaten.append((mit_rest.group("anmeldung"), mit_rest.group("rest")))
        for anmeldung, rest in kandidaten:
            bezeichnung = kinder_mod.pruefe_anmeldung(anmeldung)
            if bezeichnung and self.kinder.finde(bezeichnung):
                return anmeldung, rest
        return None

    def ist_steuerung(self, text):
        """Würde Pixel diese Äußerung selbst erledigen (Befehl, Anmeldung, Wechsel, Fachwunsch, Abschied …)?"""
        if not text:
            return False
        if self.anmeldung_und_rest(text):
            return True
        bezeichnung = kinder_mod.pruefe_anmeldung(text)
        if bezeichnung and self.kinder and self.kinder.finde(bezeichnung):
            return True
        wechsel = pers.pruefe_wechsel(text) if self.persoenlichkeiten else None
        if wechsel and self.persoenlichkeiten.finde(wechsel[1]):
            return True
        return bool(pruefe_befehl(text) or fachwunsch(text) or ist_stickerfrage(text) or ist_abschied(text))

    def pruefe_persoenlichkeit(self, frage):
        """Wechselwunsch per Sprache. Gibt True/False zurück (weiter zuhören?), None wenn es keiner ist."""
        if not self.persoenlichkeiten:
            return None
        wunsch = pers.pruefe_wechsel(frage)
        if not wunsch:
            return None
        art, bezeichnung = wunsch
        pid = self.persoenlichkeiten.finde(bezeichnung)  # nur per Sprache freigegebene
        if pid is None:
            if art == "fest":  # "Persönlichkeit Elefant": verrät nicht, welche gesperrt sind
                print(f"  [Befehl] Persönlichkeit '{bezeichnung}' unbekannt oder nicht freigegeben")
                self.sage("Diese Persönlichkeit kenne ich nicht.")
                return True
            return None  # "Sei ein Elefant" ist eine normale Frage an Claude
        print(f"  [Befehl] Persönlichkeit {pid}")
        if pid == self.aktiv:
            self.sage(f"Ich bin doch schon {self.persoenlichkeit_name}.")
        else:
            self.wechsle_persoenlichkeit(pid, ansage=True)
        self.letzte_aktivitaet = time.time()
        return True

    def bestaetigung(self):
        """Ton nach dem Wake Word ("Ja?" mit der aktuellen Stimme), zwischengespeichert je Stimme."""
        schluessel = (getattr(self.voice, "kennung", None), self.ack)
        if self._bestaetigung is None or self._bestaetigung[0] != schluessel:
            ack = stimmen.ohne_marken(self.ack)
            ton = synthetisiere(self.voice, ack) if ack.strip() else piepton()
            self._bestaetigung = (schluessel, ton)
        return self._bestaetigung[1]

    def wechsle_stimme(self, kennung):
        """Neue Stimme laden. Bei Fehlern bleibt die bisherige Stimme."""
        try:
            if self._ersatz is None:  # Piper als Ersatz nur einmal laden (dauert ca. 2 s)
                self._ersatz = stimmen.baue_stimme(stimmen.STANDARD_STIMME)
            if kennung == stimmen.STANDARD_STIMME:
                self.voice = self._ersatz
            else:
                self.voice = stimmen.baue_stimme(kennung, ersatz=self._ersatz)
            print(f"  Stimme: {kennung}")
            return True
        except (ValueError, RuntimeError, OSError) as fehler:
            print(f"  [Einstellungen] Stimme {kennung} nicht ladbar ({fehler}), bleibt {self.voice.kennung}")
            return False

    def uebernimm_einstellungen(self, hoerer=None):
        """Geänderte Werte aus der Einstellungsdatei übernehmen. Wird vor jeder Frage aufgerufen."""
        if self.kinder and self.kinder.aenderungen() and self.kind and not self.kinder.hole(self.kind):
            print("  [Kinder] aktives Kind gelöscht")
            self.kind = ""
            if self.einstellungen:
                self.einstellungen.setze("kind", "")
        if self.persoenlichkeiten:
            geaendert = self.persoenlichkeiten.aenderungen()
            if self.aktiv in geaendert:
                if self.persoenlichkeiten.hole(self.aktiv):
                    print("  [Persönlichkeiten] aktive Persönlichkeit geändert")
                    self.wende_persoenlichkeit_an(self.aktiv)
                else:  # gelöscht: zurück zu Pixel
                    print("  [Persönlichkeiten] aktive Persönlichkeit gelöscht, zurück zu Pixel")
                    self.wechsle_persoenlichkeit(pers.STANDARD)
        if not self.einstellungen:
            return
        for name, wert in self.einstellungen.aenderungen().items():
            print(f"  [Einstellungen] {name} = {wert}")
            if name == "kind":
                if not wert:
                    self.abmelden("Oberfläche")
                elif self.wechsle_kind(wert, ansage=False):  # gewählt in der Oberfläche
                    self.letzte_aktivitaet = time.time()  # gilt ab jetzt 30 Minuten
                else:
                    print(f"  [Einstellungen] Kind {wert} unbekannt, bleibt {self.kind or 'keins'}")
                    self.einstellungen.setze("kind", self.kind)
            elif name == "persoenlichkeit":
                if not self.wechsle_persoenlichkeit(wert):  # ohne Ansage, gewählt in der Oberfläche
                    print(f"  [Einstellungen] Persönlichkeit {wert} unbekannt, bleibt {self.aktiv}")
                    self.einstellungen.setze("persoenlichkeit", self.aktiv)
            elif name == "folge":
                self.folge_s = wert
            elif name == "pause":
                self.pause_basis = wert
            elif name == "ww_schwelle" and hoerer:
                hoerer.ww_schwelle = wert
            elif name == "wakeword" and hoerer:
                if hoerer.lade_wakeword(wert):  # gilt ab dem nächsten Warten auf das Wake Word
                    print(f"  Wake Word: {anzeigename(wert)}")
                else:
                    self.merke("wakeword", hoerer.wakeword)
            elif name == "schlafenszeit":
                self.grenzen.schlafenszeit = Grenzen._lies_zeitraum(wert)
            elif name == "tageslimit_cent":
                self.grenzen.limit_cent = wert
            elif name == "tageslimit_cent_erwachsene":
                self.grenzen.limit_cent_erwachsene = wert
            elif name == "max_fragen":
                self.grenzen.max_fragen = wert
            elif name == "geschichte_bis":
                self.geschichte_bis = wert

    def neu(self):
        self.verlauf.clear()
        self.letzte_antwort = ""
        self.serie = 0

    def einstellung(self, name):
        if self.einstellungen:
            return self.einstellungen.werte.get(name, EINSTELLUNGEN_FELDER[name][0])
        return EINSTELLUNGEN_FELDER[name][0]

    def spricht(self):
        """Zustand "spricht" für die Oberfläche, sobald Pixel zu hören ist; vorher "antwortet" (denkt nach)."""
        self.melde("spricht")

    def sage(self, text):
        """Kurzen Text ohne Claude sprechen (für Befehle, Grenzen und Fehlermeldungen)."""
        print(f"  Sage: {text}")
        sprecher = Sprecher(self.voice, self.lautstaerke, englisch=self.englische_stimme(), beim_ton=self.spricht)
        sprecher.sprich(text)
        sprecher.fertig()
        self.buche_tts(sprecher)

    def buche_tts(self, sprecher):
        """Zeichen der Cloud-Stimmen zählen, Kosten oberhalb der monatlichen Freimenge buchen (je Stimme)."""
        for voice, zeichen in sprecher.zeichen.items():
            gruppe = getattr(voice, "preisgruppe", None)
            if not gruppe or not zeichen:
                continue
            if time.strftime("%Y-%m") != self.monat:  # neuer Monat, neue Freimenge
                self.monat, self.monatszeichen = time.strftime("%Y-%m"), {}
            bisher = self.monatszeichen.get(gruppe, 0)
            kosten = stimmen.kosten_usd(gruppe, stimmen.berechnete_zeichen(gruppe, zeichen, bisher))
            self.monatszeichen[gruppe] = bisher + zeichen
            self.buche("tts", kosten, modell=voice.kennung, zeichen=zeichen, status=gruppe)

    def modell_ansage(self):
        info = MODELLE.get(self.modell)
        if info:
            return f"Ich bin im {info['modus']} und benutze {info['name']}."
        return f"Ich benutze das Modell {self.modell}."

    def fuehre_befehl_aus(self, befehl):
        """Führt einen Sprachbefehl aus. Gibt True zurück, wenn danach weiter zugehört werden soll,
        False für zurück zum Wake Word."""
        art, wert = befehl
        print(f"  [Befehl] {art}" + (f" {wert}" if wert else ""))
        if art == "beenden":
            self.neu()
            self.sage("Tschüss, bis bald!")
            self.abmelden("Abschied")  # danach spricht oft ein anderes Kind (sonst ginge dessen Übung aufs falsche Profil)
            return False
        if art == "pause":
            return False
        if art == "neu":
            self.neu()
            self.sage("Okay, wir fangen von vorne an.")
        elif art == "wiederholen":
            self.sage(self.letzte_antwort or "Ich habe noch nichts gesagt.")
        elif art == "welches_modell":
            self.sage(self.modell_ansage())
        elif art == "persoenlichkeiten":
            namen = [n for n in (self.persoenlichkeiten.per_sprache() if self.persoenlichkeiten else [])
                     if n != self.persoenlichkeit_name]
            if namen:
                liste = namen[0] if len(namen) == 1 else ", ".join(namen[:-1]) + " oder " + namen[-1]
                self.sage(f"Gerade bin ich {self.persoenlichkeit_name}. Ich kann auch {liste} sein. "
                          f"Sag zum Beispiel: Persönlichkeit {namen[-1]}.")
            else:
                self.sage(f"Ich bin {self.persoenlichkeit_name}.")
        elif art in ("lauter", "leiser"):
            neu = self.stufe + (1 if art == "lauter" else -1)
            if 1 <= neu <= len(LAUTSTAERKE_STUFEN):
                self.stufe = neu
                self.merke("lautstaerke", neu)
                self.sage(f"So ist es {art}.")
            else:
                self.sage(f"{art.capitalize()} geht es nicht.")
            print(f"  Lautstärke: Stufe {self.stufe} von {len(LAUTSTAERKE_STUFEN)}")
        elif art == "modell":
            if wert is None:
                self.sage("Das Modell kenne ich nicht. Sag Haiku oder Sonnet.")
            elif wert == self.modell:
                self.sage(self.modell_ansage())
            else:
                self.modell = wert
                self.merke("modell", wert)
                self.sage(f"Okay. {self.modell_ansage()}")
                print(f"  Claude-Modell: {self.modell}")
        self.letzte_aktivitaet = time.time()
        return True

    def kosten_zusammenfassung(self):
        k, a = self.kosten, self.anfragen
        text = (f"Claude {k['claude'] * 100:.2f} US-Cent ({a['claude']}x), "
                f"Deepgram {k['deepgram'] * 100:.2f} US-Cent ({a['deepgram']}x), ")
        if a["tts"]:
            text += f"Stimme {k['tts'] * 100:.2f} US-Cent ({a['tts']}x), "
        return text + f"zusammen {sum(k.values()) * 100:.2f} US-Cent"

    def buche(self, dienst, kosten, **werte):
        """Kosten aufsummieren und ins Protokoll schreiben."""
        erwachsen = self.ist_erwachsen
        if kosten is not None:
            self.kosten[dienst] += kosten
            if erwachsen:
                self.heute_kosten_erwachsene += kosten
            else:
                self.heute_kosten += kosten
        self.anfragen[dienst] += 1
        if dienst == "claude" and werte.get("status") != "fehler" and not erwachsen:
            self.heute_fragen += 1
        if self.protokoll:
            self.protokoll.schreibe(dienst=dienst, kosten_usd=kosten, profil="erwachsen" if erwachsen else "",
                                    **werte)

    def zeige_kosten(self, nutzung, dauer, status, modell=None):
        """Claude: verbrauchte Tokens und Kosten anzeigen und protokollieren."""
        if nutzung is None:
            return
        modell = modell or self.modell
        kosten = berechne_kosten(modell, nutzung)
        geschrieben = getattr(nutzung, "cache_creation_input_tokens", 0) or 0
        gelesen = getattr(nutzung, "cache_read_input_tokens", 0) or 0
        self.buche("claude", kosten, modell=modell, tokens_ein=nutzung.input_tokens + geschrieben + gelesen,
                   tokens_aus=nutzung.output_tokens, dauer_s=dauer, status=status)
        tokens = f"{nutzung.input_tokens + geschrieben + gelesen} ein / {nutzung.output_tokens} aus"
        if geschrieben or gelesen:
            tokens += f" (Cache: {gelesen} gelesen, {geschrieben} geschrieben)"
        if kosten is None:
            print(f"  [Kosten] Claude: {tokens} (kein Preis für {modell} hinterlegt)")
            return
        print(f"  [Kosten] Claude: {tokens}, {kosten * 100:.3f} US-Cent")
        print(f"  [Kosten] seit Start: {self.kosten_zusammenfassung()}")

    def verarbeite(self, frage):
        """Befehl ausführen oder Frage beantworten. Gibt False zurück für zurück zum Wake Word."""
        # "Ich bin Anna. Wie viele Sticker habe ich?": erst anmelden, dann den Rest wie eine eigene Äußerung
        teile = self.anmeldung_und_rest(frage)
        if teile and self.pruefe_anmeldung(teile[0]):
            frage = teile[1]
        if self.ist_loesung(frage):
            # "Tschüss" als Antwort auf "Was heißt goodbye?", "Stopp" für "stop": keine Befehle, sondern Antworten
            print("  [Antwort] passt zur Lösung der letzten Aufgabe, kein Befehl")
            self.beantworte(frage)
            return True
        befehl = pruefe_befehl(frage)
        if befehl:
            return self.fuehre_befehl_aus(befehl)
        weiter = self.pruefe_anmeldung(frage)
        if weiter is not None:
            return weiter
        if self.schlafenszeit_kind and not self.ist_erwachsen and not (self.nur_geschichte and self.gute_nacht
                                                                        and ist_geschichtenwunsch(frage)):
            self.sage("Es ist schon Schlafenszeit. Wenn du möchtest, erzähle ich dir noch eine Gute-Nacht-Geschichte."
                      if self.nur_geschichte else SCHLAFENSZEIT)
            return False
        if ist_stickerfrage(frage):
            print("  [Befehl] Sticker")
            album = self.album()
            self.sage(album.zusammenfassung() if album else
                      "Sag mir zuerst, wer du bist. Zum Beispiel: Ich bin, und dann deinen Namen.")
            self.letzte_aktivitaet = time.time()
            return True
        fach = fachwunsch(frage)
        pid = self.persoenlichkeit_fuer(fach) if fach else None
        if pid and pid != self.aktiv:
            print(f"  [Befehl] Fachwunsch {fach}: Persönlichkeit {pid}")
            self.wechsle_persoenlichkeit(pid, ansage=True)
            self.beantworte(frage)  # die neue Persönlichkeit geht gleich auf den Wunsch ein
            return True
        weiter = self.pruefe_persoenlichkeit(frage)
        if weiter is not None:
            return weiter
        if ist_geschichtenwunsch(frage) and self.gute_nacht:
            self.erzaehle(frage)
            return False  # nach einer Geschichte nicht weiter zuhören, Schlafenszeit
        if ist_abschied(frage):  # Claude verabschiedet sich passend, danach zurück zum Wake Word
            print("  [Abschied] Gespräch endet nach der Antwort")
            self.beantworte(frage)
            self.neu()
            self.abmelden("Abschied")
            return False
        self.beantworte(frage)
        return True

    def persoenlichkeit_fuer(self, fach):
        """Per Sprache wählbare Persönlichkeit für ein Fach: Lernplan passt, für Zuhören die Zuhör-Persönlichkeit."""
        return self.persoenlichkeiten.fuer_fach(fach) if self.persoenlichkeiten else None

    def ist_loesung(self, frage):
        """Ist die Äußerung genau die versteckte Lösung von Pixels letzter Aufgabe?"""
        if time.time() - getattr(self, "letzte_aktivitaet", 0) > VERLAUF_VERGESSEN_S:
            return False  # die Aufgabe ist zu lange her (oder es gab noch keine)
        t = normalisiere(frage)
        loesungen = {normalisiere(teil) for loesung in stimmen.loesungen(self.letzte_antwort or "")
                     for teil in re.split(r",|;| oder ", loesung)}
        return bool(t) and t in loesungen

    def geschichten_stimme(self):
        """Stimme für Geschichten: eigene, falls eingestellt und ladbar, sonst die Gesprächsstimme."""
        kennung = self.stimme_geschichte
        if not kennung or kennung == getattr(self.voice, "kennung", None):
            return self.voice
        if self._geschichten_voice and self._geschichten_voice[0] == kennung:
            return self._geschichten_voice[1]
        try:
            if self._ersatz is None:
                self._ersatz = stimmen.baue_stimme(stimmen.STANDARD_STIMME)
            voice = self._ersatz if kennung == stimmen.STANDARD_STIMME else \
                stimmen.baue_stimme(kennung, ersatz=self._ersatz)
            self._geschichten_voice = (kennung, voice)
            return voice
        except (ValueError, RuntimeError, OSError) as fehler:
            print(f"  [Geschichte] Stimme {kennung} nicht ladbar ({fehler}), nehme {self.voice.kennung}")
            return self.voice

    def englische_stimme(self):
        """Stimme für englische Stellen (<en>…</en>) oder None. Fehlt sie, spricht die normale Stimme."""
        kennung = self.stimme_englisch
        if not kennung:
            return None
        if self._englische_voice and self._englische_voice[0] == kennung:
            return self._englische_voice[1]
        try:
            if self._ersatz is None:
                self._ersatz = stimmen.baue_stimme(stimmen.STANDARD_STIMME)
            voice = stimmen.baue_stimme(kennung, ersatz=self._ersatz)
        except (ValueError, RuntimeError, OSError) as fehler:
            print(f"  [Englisch] Stimme {kennung} nicht ladbar ({fehler}), Englisch spricht {self.voice.kennung}")
            voice = None
        self._englische_voice = (kennung, voice)
        return voice

    def erzaehle(self, wunsch):
        """Gute-Nacht-Geschichte mit eigenem Modell, eigener Stimme und eigenen Anweisungen.

        Die Geschichte kommt nicht in den Gesprächsverlauf (sonst kostet jede weitere Frage über
        tausend Tokens mehr)."""
        messung = self.messung or {"t_ende": time.time()}
        self.messung = None
        modell = self.modell_geschichte
        print(f"  [Geschichte] {modell}, Stimme {self.stimme_geschichte or 'wie im Gespräch'}")
        self.melde("antwortet", "Gute-Nacht-Geschichte")
        import anthropic

        sprecher = Sprecher(self.geschichten_stimme(), self.lautstaerke, englisch=self.englische_stimme(),
                            beim_ton=self.spricht)
        try:
            text, bis_erster, gesamt, stopp_grund, nutzung = frage_claude(
                self.client, modell, self.mit_kind(self.geschichten_prompt, geschichte=True),
                [{"role": "user", "content": kinder_mod.ohne_namen(wunsch, self.kinder) if self.kinder else wunsch}],
                sprecher,
                max_tokens=MAX_TOKENS_GESCHICHTE,
            )
        except anthropic.APIError as fehler:
            print(f"  [Claude] FEHLER: {fehler}")
            self.buche("claude", 0.0, modell=modell, status="fehler")
            sprecher.sprich(FEHLER_VERBINDUNG if isinstance(fehler, anthropic.APIConnectionError) else FEHLER_ALLGEMEIN)
            sprecher.fertig()
            self.buche_tts(sprecher)
            return
        print(f"  [Claude] Geschichte: {len(text.split())} Wörter, fertig nach {gesamt:.1f} s, Stopp: {stopp_grund}")
        self.zeige_kosten(nutzung, gesamt, stopp_grund, modell=modell)
        if stopp_grund == "max_tokens":
            print("  WARNUNG: Geschichte wurde wegen max_tokens abgeschnitten.")
        if not text:
            sprecher.sprich("Hmm, mir fällt gerade keine Geschichte ein. Frag mich bitte noch einmal.")
        sprecher.fertig()
        self.buche_tts(sprecher)
        if text:
            self.letzte_geschichte = time.time()
            self.letzte_antwort = text  # "Wiederhole" liest die Geschichte noch einmal vor
            self.zeige_wartezeit(messung, sprecher, bis_erster, gesamt, modell=modell, art="geschichte")
        self.letzte_aktivitaet = time.time()

    def vorwaermen(self):
        """Verbindungen zu Deepgram und zur Cloud-Stimme aufbauen, während das Kind noch spricht
        (spart bei Deepgram ca. 0,4 s)."""
        englisch = self._englische_voice[1] if self._englische_voice else None
        for ziel in (self.erkenne, self.voice, englisch):
            vorwaermen = getattr(ziel, "vorwaermen", None)
            if vorwaermen:
                vorwaermen()

    def erkenne_audio(self, audio, pause_s=None):
        """Audio mit Deepgram in Text umwandeln. Leerer Text bei Fehler oder Stille.

        pause_s: abgewartete Stille nach dem letzten Wort, zählt zur Wartezeit (None im Modus taste).
        """
        self.melde("antwortet")
        self.stt_fehler = False  # Verbindungsfehler: dann hat Pixel schon etwas gesagt
        self.unsicher = None
        audio_s = len(audio) / SAMPLERATE_AUFNAHME
        self.messung = {"t_ende": time.time(), "pause_s": pause_s, "audio_s": audio_s}
        gesendet = float(np.abs(audio).max()) >= STILLE_SCHWELLE  # Stille schickt sprachtest nicht
        preis = DEEPGRAM_PREIS_MIN_MULTI if self.erkennung == "multi" else DEEPGRAM_PREIS_MIN
        hinweise = hinweiswoerter(self.letzte_antwort)
        if hinweise:
            preis += DEEPGRAM_PREIS_KEYTERM_MIN
            print(f"  [STT] Hinweiswörter: {', '.join(hinweise)}")
        kosten = audio_s / 60 * preis if gesendet else 0.0
        modell = "nova-3" if self.erkennung == "de" else f"nova-3-{self.erkennung}"
        protokoll = {"modell": modell + ("+keyterm" if hinweise else ""), "audio_s": audio_s}
        try:
            if self.erkennung == "multi" and gesendet:
                text, sek = self.erkenne_doppelt(audio, hinweise, audio_s, protokoll)
                if text is None:  # beide fehlgeschlagen
                    raise RuntimeError("Deepgram (deutsch und gemischt) nicht erreichbar")
                kosten = 0.0  # schon je Erkennung gebucht
            else:
                text, sek = self.erkenne(audio, sprache=self.erkennung, hinweise=hinweise)
        except Exception as fehler:
            print(f"  [STT] FEHLER: {fehler}")
            self.stt_fehler = True
            self.buche("deepgram", 0.0, status="fehler", **protokoll)  # fehlgeschlagen: vermutlich nicht berechnet
            import requests

            netzfehler = isinstance(fehler, (requests.ConnectionError, requests.Timeout))
            self.sage(FEHLER_VERBINDUNG if netzfehler else FEHLER_ALLGEMEIN)  # Kind nicht ratlos lassen
            return ""
        if not gesendet:
            return text
        self.messung["stt_s"] = sek
        print(f"  [STT] {sek:.2f} s -> \"{text}\"")
        if not text:  # nur Zahlen: zeigt, ob das Kind zu leise war (Spitze nahe 0 %) oder Geräusch/Murmeln
            werte = np.asarray(audio, dtype=np.float32)  # Aufnahme ist auf -1 bis 1 normiert
            spitze = float(np.abs(werte).max()) * 100
            mittel = 20 * np.log10(max(float(np.sqrt(np.mean(werte ** 2))), 1e-5))
            print(f"  [STT] leer, Pegel: Spitze {spitze:.0f} %, Mittel {mittel:.0f} dBFS")
        if self.erkennung != "multi":
            print(f"  [Kosten] Deepgram: {audio_s:.1f} s Audio, {kosten * 100:.3f} US-Cent")
            self.buche("deepgram", kosten, dauer_s=sek, status="ok" if text else "leer", **protokoll)
        return text

    def erkenne_doppelt(self, audio, hinweise, audio_s, protokoll):
        """Englisch-Runden: dieselbe Aufnahme gleichzeitig deutsch und gemischt erkennen lassen (kostet die
        Spracherkennung doppelt, ca. 0,01 Cent, aber keine Wartezeit). Deutsch gilt, wenn es ein Befehl, eine
        Anmeldung oder ein Wechsel ist (die gemischte Erkennung machte aus Namen ganz andere Wörter,
        aus "Sei Professor Pixel" "Professional text", 23.10.2026) oder wenn die gemischte fremde Schrift liefert;
        sonst gilt die gemischte (englische Antworten). Gibt (Text, Sekunden) zurück, (None, 0) wenn beide
        fehlschlagen."""
        ergebnisse, buchungen = {}, []

        def eine(sprache):
            preis = DEEPGRAM_PREIS_MIN_MULTI if sprache == "multi" else DEEPGRAM_PREIS_MIN
            preis += DEEPGRAM_PREIS_KEYTERM_MIN if hinweise else 0
            modell = ("nova-3-multi" if sprache == "multi" else "nova-3") + ("+keyterm" if hinweise else "")
            try:
                text, sek = self.erkenne(audio, sprache=sprache, hinweise=hinweise)
            except Exception as fehler:  # noqa: BLE001 – die andere Erkennung kann noch reichen
                print(f"  [STT] {sprache}: FEHLER {fehler}")
                buchungen.append((0.0, dict(protokoll, modell=modell, status="fehler")))
                return
            buchungen.append((audio_s / 60 * preis, dict(protokoll, modell=modell, dauer_s=sek,
                                                             status="ok" if text else "leer")))
            ergebnisse[sprache] = (text, sek)

        with ThreadPoolExecutor(max_workers=2) as pool:  # gleichzeitig: keine zusätzliche Wartezeit
            list(pool.map(eine, ("de", "multi")))
        for kosten, werte in buchungen:  # erst danach ins Protokoll (nicht aus zwei Threads gleichzeitig)
            self.buche("deepgram", kosten, **werte)
        print(f"  [Kosten] Deepgram: {audio_s:.1f} s Audio, doppelt erkannt, "
              f"{sum(k for k, _ in buchungen) * 100:.3f} US-Cent")
        if not ergebnisse:
            return None, 0.0
        de, multi = ergebnisse.get("de"), ergebnisse.get("multi")
        sek = max(e[1] for e in ergebnisse.values())
        if de and multi:
            print(f"  [STT] deutsch \"{de[0]}\" | gemischt \"{multi[0]}\"")
        # Passt nur eins zur erwarteten Lösung, gilt dieses: Am 24.10.2026 erkannte deutsch "Bird", gemischt "But"
        # und "Beard", und das Kind bekam für ein richtiges "bird" "falsch".
        loesungen = [teil.strip() for lo in stimmen.loesungen(self.letzte_antwort) for teil in re.split(r",|;| oder ", lo)]
        if de and multi and de[0] and passt_zur_loesung(de[0], loesungen) and not passt_zur_loesung(multi[0], loesungen):
            print("  [STT] deutsch passt zur Lösung")
            return de[0], sek
        if de and de[0] and (not multi or not multi[0] or self.ist_steuerung(de[0]) or fremde_zeichen(multi[0])):
            text, andere = de[0], (multi or ("",))[0]
        else:
            text, andere = (multi or de)[0], (de or ("",))[0] if multi else ""
        if (loesungen and de and multi and _woerter(de[0]) != _woerter(multi[0]) and not self.ist_steuerung(text)
                and not passt_zur_loesung(text, loesungen) and not passt_zur_loesung(andere, loesungen)):
            self.unsicher = andere
            print("  [STT] uneinig, keine passt zur Lösung")
        return text, sek

    def beantworte(self, frage):
        """Frage an Claude stellen und die Antwort laut vorlesen."""
        messung = self.messung or {"t_ende": time.time()}  # getippte Frage: Messung beginnt jetzt
        self.messung = None
        if time.time() - self.letzte_aktivitaet > VERLAUF_VERGESSEN_S:
            self.neu()  # lange Pause: neues Gespräch, auch die alte Aufgabe (Lösung, Thema) gilt nicht mehr
        self.letzte_aktivitaet = time.time()

        if self.kinder:
            frage = kinder_mod.ohne_namen(frage, self.kinder)  # Namen gehen nie an Claude
        self.verlauf.append({"role": "user", "content": frage})
        if len(self.verlauf) > MAX_NACHRICHTEN:
            # in einem Schritt kürzen: Der Anfang des Verlaufs bleibt dann für mehrere Fragen gleich (Cache)
            self.verlauf[:] = self.verlauf[-VERLAUF_KUERZEN_AUF:]
        while self.verlauf and self.verlauf[0]["role"] != "user":  # Verlauf muss mit user beginnen
            self.verlauf.pop(0)

        import anthropic

        vorige_antwort = self.letzte_antwort  # enthält die versteckte Lösung der Abfrage, auf die das Kind antwortet
        system = self.mit_kind(self.system)
        kartei = self.kartei()
        if kartei:
            system = f"{system}\n\n{kartei.prompt_abschnitt()}"
        stand = self.themenstand()
        notizen = []
        if stand:  # ändert sich selten (Wahl, Schwierigkeit, geschafft): Cache bleibt an
            neu = len(self.verlauf) <= 1  # nur die gerade gestellte Frage: neues Gespräch
            system = f"{system}\n\n{stand.prompt_abschnitt()}"
            vorschlag = None if neu else stand.vorschlag()  # schwerer, leichter oder nächstes Thema vorschlagen
            if neu and stand.aktuell:
                notizen.append(stand.begruessung())
            if vorschlag:
                stand.speichere()
                print(f"  [Lernplan] {vorschlag.split(': ', 1)[1][:90]} …")
                notizen.append(vorschlag)
            art = stand.einmaleins_art()
            if art and not neu:  # Einmaleins-Karteikasten: welche Aufgaben dran sind
                notizen.append(einmaleins.Kartei(self.kind, self.lernordner).notiz(art))
        if self.unsicher is not None and self.unsicher_folge < MAX_UNSICHER:
            self.unsicher_folge += 1
            andere = kinder_mod.ohne_namen(self.unsicher, self.kinder) if self.kinder else self.unsicher
            notizen.append(NOTIZ_UNSICHER.format(andere=andere.replace('"', "") or "nichts"))
        else:
            self.unsicher_folge = 0
        self.unsicher = None
        if notizen:
            # An die Äußerung des Kindes in diesem Zug, nicht in den System-Prompt: Haiku übersah Vorschläge dort,
            # und der System-Prompt bliebe nicht gleich (Cache)
            notiz = " ".join(f"({n})" for n in [*notizen, NOTIZ_GEHEIM])
            self.verlauf[-1] = {"role": "user", "content": f"{self.verlauf[-1]['content']}\n\n{notiz}"}
        jubel = bool(self.lernzeit and self.kind_daten and not self.ist_erwachsen)
        sprecher = Sprecher(self.voice, self.lautstaerke, englisch=self.englische_stimme(), jubel=jubel,
                            beim_ton=self.spricht)
        try:
            antwort, bis_erster, gesamt, stopp_grund, nutzung = frage_claude(
                self.client, self.modell, system, self.verlauf, sprecher,
                cache=not kartei,  # mit Lernplan ändert sich der System-Prompt bei jeder Frage
            )
        except anthropic.APIError as fehler:
            self.verlauf.pop()  # fehlgeschlagene Frage nicht im Verlauf lassen
            print(f"  [Claude] FEHLER: {fehler}")
            self.buche("claude", 0.0, modell=self.modell, status="fehler")
            # APITimeoutError ist eine Unterklasse von APIConnectionError
            if isinstance(fehler, anthropic.APIConnectionError):
                sprecher.sprich(FEHLER_VERBINDUNG)
            else:
                sprecher.sprich(FEHLER_ALLGEMEIN)
            sprecher.fertig()
            self.buche_tts(sprecher)
            return
        bis_text = f"{bis_erster:.2f} s" if bis_erster is not None else "-"
        print(f"  [Claude] erster Satz nach {bis_text}, komplett nach {gesamt:.2f} s, Stopp: {stopp_grund}")
        self.zeige_kosten(nutzung, gesamt, stopp_grund)
        if stopp_grund == "max_tokens":
            print("  WARNUNG: Antwort wurde wegen max_tokens abgeschnitten.")
        if not antwort:
            # Leere Antworten dürfen nicht in den Verlauf, sonst lehnt die API die nächste Anfrage ab
            self.verlauf.pop()
            print("  [Claude] Leere Antwort.")
            sprecher.sprich("Hmm, dazu fällt mir gerade nichts ein. Frag mich bitte noch einmal.")
            sprecher.fertig()
            self.buche_tts(sprecher)
            return
        self.verlauf.append({"role": "assistant", "content": antwort})
        self.letzte_antwort = antwort
        print(f"  Antwort: {antwort}")
        neue_stufe = self.lerne(vorige_antwort, antwort)
        geschafft = self.lerne_thema(vorige_antwort, antwort)
        belohnungen = self.belohnungen(antwort)
        sprecher.fertig()
        self.buche_tts(sprecher)
        self.zeige_wartezeit(messung, sprecher, bis_erster, gesamt)
        if neue_stufe:
            self.sage(f"Toll! Du hast so viel gelernt, dass du jetzt in Stufe {neue_stufe} bist.")
        if geschafft:
            self.sage(geschafft)
        for ton, satz in belohnungen:
            signalton(ton, self)
            self.sage(satz)
        self.letzte_aktivitaet = time.time()

    def zeige_wartezeit(self, messung, sprecher, bis_erster, claude_gesamt, modell=None, art="gespraech"):
        """Wartezeit vom Ende des Sprechens bis zum ersten Ton anzeigen und protokollieren."""
        if sprecher.erster_ton is None:
            return
        pause = messung.get("pause_s")
        warten = (pause or 0.0) + sprecher.erster_ton - messung["t_ende"]
        if art == "gespraech":  # Geschichten verfälschen die Wartezeit von Gesprächen nicht
            self.wartezeiten.append(warten)
        teile = []
        if pause is not None:
            teile.append(f"Pause {pause:.2f}")
        if messung.get("stt_s") is not None:
            teile.append(f"Deepgram {messung['stt_s']:.2f}")
        if bis_erster is not None:
            teile.append(f"Claude 1. Satz {bis_erster:.2f}")
        if sprecher.tts_erster_s is not None:
            teile.append(f"Stimme {sprecher.tts_erster_s:.2f}")
        print(f"  [Zeit] {' + '.join(teile)} -> erster Ton nach {warten:.2f} s"
              + ("" if pause is not None else " (ohne Sprechpause, getippt oder feste Dauer)"))
        if self.zeiten:
            self.zeiten.schreibe(
                modell=modell or self.modell, art=art, audio_s=messung.get("audio_s"), pause_s=pause,
                stt_s=messung.get("stt_s"), claude_erster_satz_s=bis_erster,
                tts_erster_satz_s=sprecher.tts_erster_s, warten_s=warten,
                stimme=getattr(sprecher.voice, "kennung", None),
                claude_gesamt_s=claude_gesamt, zeichen_erster_satz=sprecher.zeichen_erster_satz,
            )

    def wartezeit_zusammenfassung(self):
        w = sorted(self.wartezeiten)
        if not w:
            return None
        return (f"Wartezeit bis zum ersten Ton: Median {w[len(w) // 2]:.2f} s, "
                f"schnellste {w[0]:.2f} s, langsamste {w[-1]:.2f} s ({len(w)} Antworten)")


# ----------------------------------------------------------------------- Modi
def sicher_verarbeite(gespraech, frage):
    """verarbeite, aber ein unerwarteter Fehler beendet nicht das ganze Programm (sonst startet der Dienst neu,
    und das Kind hört nichts). Gibt False zurück (zurück zum Wake Word), wenn etwas schiefging."""
    try:
        return gespraech.verarbeite(frage)
    except Exception:  # noqa: BLE001 – alles abfangen, Strg+C (KeyboardInterrupt) aber nicht
        print("  FEHLER beim Verarbeiten:")
        traceback.print_exc()
        try:
            gespraech.sage(FEHLER_ALLGEMEIN)
        except Exception:  # noqa: BLE001
            pass
        return False


def modus_taste(gespraech, dauer):
    """Enter = aufnehmen (feste Dauer), oder Text eintippen. Zum Testen."""
    print("\nEnter = sprechen, oder Text eintippen. 'neu' = von vorn, 'q' = beenden.\n")
    while True:
        gespraech.melde("wartet", "Modus taste")
        eingabe = input("> ").strip()
        if eingabe.lower() == "q":
            return
        if eingabe.lower() == "neu":
            gespraech.neu()
            print("  Verlauf gelöscht.\n")
            continue
        gespraech.uebernimm_einstellungen()
        grenze = gespraech.grenze_erreicht()
        if grenze:
            gespraech.sage(grenze)
            continue
        if eingabe:
            frage = eingabe
            gespraech.melde("antwortet")
            gespraech.messung = None  # keine alte Messung einer früheren Aufnahme verwenden
        else:
            gespraech.vorwaermen()
            frage = gespraech.erkenne_audio(nimm_auf(dauer))
            if not frage:
                print("  Nichts gehört.")
                continue
        sicher_verarbeite(gespraech, frage)  # "Tschüss" beendet hier nur das Gespräch, nicht das Programm
        print()


def modus_dauerhaft(gespraech, hoerer):
    """Ohne Wake Word: jede erkannte Sprache wird verarbeitet (nur zum Testen der Sprechpausen)."""
    print("\nDauerhaftes Zuhören, ohne Wake Word. Ctrl+C beendet.")
    print("Achtung: Jede Sprache im Raum wird an Deepgram und Claude gesendet.\n")
    while True:
        print("Ich höre zu ...")
        gespraech.melde("hoert_zu", "ohne Wake Word")
        audio = hoerer.nimm_bis_pause(start_timeout_s=None)
        if audio is None:
            continue
        gespraech.uebernimm_einstellungen(hoerer)
        grenze = gespraech.grenze_erreicht()
        if grenze:  # Aufnahme verwerfen, nichts senden
            gespraech.sage(grenze)
            continue
        frage = gespraech.erkenne_audio(audio, hoerer.letzte_pause_s)
        if frage:
            sicher_verarbeite(gespraech, frage)
        print()


def modus_wakeword(gespraech, hoerer):
    """Wake Word -> sprechen -> Antwort -> kurzes Folgefrage-Fenster -> zurück zum Wake Word."""
    while True:
        print(f"Warte auf das Wake Word „{anzeigename(hoerer.wakeword)}“ ...")
        gespraech.melde("wartet")
        score = hoerer.warte_auf_wakeword()
        print(f"  Wake Word erkannt (Score {score:.2f})")
        # erst die Einstellungen: eine frische Anmeldung in der Oberfläche soll nicht als abgelaufen gelten
        gespraech.uebernimm_einstellungen(hoerer)  # Änderungen aus der Oberfläche gelten ab jetzt
        gespraech.pruefe_anmeldung_abgelaufen()
        grenze = gespraech.grenze_erreicht()
        if grenze:  # gar nicht erst aufnehmen
            gespraech.sage(grenze)
            print()
            continue
        daten, rate = gespraech.bestaetigung()
        spiele(mit_lautstaerke(daten, gespraech.lautstaerke), rate)  # Mikrofon ist währenddessen zu

        timeout = WARTEN_NACH_WAKEWORD_S
        folgefrage = False
        bereit_ton = False  # nach einer Antwort: Ton, damit das Kind weiß, dass es jetzt sprechen kann
        leer = 0  # Aufnahmen hintereinander, in denen Deepgram nichts erkannt hat (Husten, Geräusch)
        denkpausen = 0  # kurze leere Aufnahmen hintereinander ("Ähm"), zählen nicht als "nicht verstanden"
        while True:
            if folgefrage:  # Limit kann mit der letzten Antwort erreicht worden sein
                gespraech.uebernimm_einstellungen(hoerer)
                grenze = gespraech.grenze_erreicht()
                if grenze:
                    gespraech.sage(grenze)
                    print()
                    break
            if bereit_ton:
                signalton(TON_BEREIT, gespraech)
            gespraech.vorwaermen()  # Deepgram schließt ungenutzte Verbindungen nach < 20 s
            print("  Ich höre zu ...")
            gespraech.melde("hoert_zu")
            hoerer.pause_s = gespraech.sprechpause  # jüngere Kinder brauchen längere Denkpausen
            audio = hoerer.nimm_bis_pause(start_timeout_s=timeout)
            if audio is None:
                print("  Nichts gehört, zurück zum Wake Word.\n")
                break
            frage = gespraech.erkenne_audio(audio, hoerer.letzte_pause_s)
            if not frage:
                fehler = getattr(gespraech, "stt_fehler", False)  # dann hat Pixel den Fehler schon angesagt
                kurz = len(audio) / SAMPLERATE_AUFNAHME <= DENKPAUSE_AUDIO_S
                if kurz and not fehler and denkpausen < MAX_DENKPAUSEN:
                    denkpausen += 1
                    gespraech.sage(DENKPAUSE)
                    print("  Kurz und nichts erkannt (Denkgeräusch?), höre weiter zu.")
                    bereit_ton = True
                    continue
                leer += 1
                if leer >= 2:
                    if not fehler:
                        gespraech.sage(NICHT_VERSTANDEN_ENDE)
                    print("  Nichts verstanden, zurück zum Wake Word.\n")
                    break
                if not fehler:
                    gespraech.sage(NICHT_VERSTANDEN)
                print("  Nichts verstanden, höre weiter zu.")
                bereit_ton = True
                continue
            leer = denkpausen = 0
            if not sicher_verarbeite(gespraech, frage):
                print("  Zurück zum Wake Word.\n")
                break
            if gespraech.folge_s <= 0:
                print()
                break
            timeout = gespraech.folge_s  # Folgefrage ohne Wake Word
            folgefrage = True
            bereit_ton = True
        signalton(TON_ENDE, gespraech)  # zurück zum Wake Word


# -------------------------------------------------------------------------- Main
def main():
    ap = argparse.ArgumentParser(description="Gespräch mit Pixel")
    ap.add_argument("--modus", choices=["wakeword", "dauerhaft", "taste"], default="wakeword",
                    help="wakeword (Standard), dauerhaft (ohne Wake Word) oder taste (Enter)")
    ap.add_argument("--modell",
                    help="Claude-Modell, z. B. claude-haiku-5-5 oder claude-sonnet-5-5")
    ap.add_argument("--wakeword",
                    help="Eigenes Modell aus wakewords/ (hey_pixel), mitgeliefertes (hey_mycroft, hey_jarvis, "
                         "alexa, hey_marvin) oder Pfad zu einer .onnx-Datei")
    ap.add_argument("--ww-schwelle", type=float,
                    help="Empfindlichkeit des Wake Words, 0 bis 1. Niedriger = reagiert leichter")
    ap.add_argument("--vad-schwelle", type=float, default=0.5,
                    help="Ab diesem Wert gilt ein Block als Sprache (Standard: 0.5)")
    ap.add_argument("--pause", type=float,
                    help="Sekunden Stille, nach denen die Aufnahme endet")
    ap.add_argument("--folge", type=float,
                    help="Sekunden für eine Folgefrage ohne Wake Word, 0 = aus")
    ap.add_argument("--stimme",
                    help="Stimme als Anbieter:Name, z. B. piper:de_DE-thorsten-medium, "
                         "google:de-DE-Chirp3-HD-Aoede, aura:aura-2-elara-de")
    ap.add_argument("--ack",
                    help="Kurzer Text nach dem Wake Word, leer = nur ein Piepton (Standard: aus der Persönlichkeit)")
    ap.add_argument("--persoenlichkeit", metavar="KENNUNG",
                    help="Persönlichkeit für diesen Lauf, z. B. pirat (sonst die aktive aus einstellungen.json)")
    ap.add_argument("--dauer", type=float, default=6.0,
                    help="Aufnahmedauer in Sekunden, nur im Modus taste (Standard: 6)")
    ap.add_argument("--system", metavar="DATEI",
                    help="Eigenen System-Prompt aus einer Textdatei laden")
    ap.add_argument("--debug", action="store_true",
                    help="Wake-Word-Scores anzeigen, hilft beim Einstellen der Schwelle")
    ap.add_argument("--schlafenszeit",
                    help="In diesem Zeitraum antwortet der Roboter nicht, z. B. 20:00-07:00, 'aus' = nie")
    ap.add_argument("--tageslimit-cent", type=float,
                    help="Höchstkosten pro Tag in US-Cent (Claude, Deepgram, Stimme), 0 = aus")
    ap.add_argument("--max-fragen", type=int,
                    help="Höchstzahl Fragen an Claude pro Tag, 0 = aus")
    ap.add_argument("--lautstaerke", type=int, choices=range(1, len(LAUTSTAERKE_STUFEN) + 1),
                    metavar=f"1-{len(LAUTSTAERKE_STUFEN)}",
                    help="Lautstärke beim Start, per Sprache 'lauter'/'leiser'")
    ap.add_argument("--einstellungen", metavar="DATEI", default=str(EINSTELLUNGEN_DATEI),
                    help="Einstellungsdatei (Standard: einstellungen.json im Programmordner)")
    ap.add_argument("--mikrofon", metavar="GERÄT",
                    help="Aufnahmegerät: Nummer oder Teil des Namens aus 'python sprachtest.py --geraete' "
                         "(Standard: Systemstandard)")
    ap.add_argument("--lautsprecher", metavar="GERÄT",
                    help="Wiedergabegerät, wie --mikrofon (Standard: Systemstandard)")
    args = ap.parse_args()

    # Mikrofon und Lautsprecher können verschiedene Geräte sein (z. B. Headset und eingebaute Lautsprecher).
    # sounddevice nimmt eine Nummer oder einen Teil des Gerätenamens; gilt für Aufnahme und Wiedergabe.
    for art, geraet in (("input", args.mikrofon), ("output", args.lautsprecher)):
        if geraet:
            try:
                info = sd.query_devices(int(geraet) if geraet.isdigit() else geraet, art)
            except ValueError as fehler:
                sys.exit(f"{'Mikrofon' if art == 'input' else 'Lautsprecher'} '{geraet}': {fehler}\n"
                         "Geräte anzeigen: python sprachtest.py --geraete")
            sd.default.device[0 if art == "input" else 1] = info["index"]
            print(f"{'Mikrofon' if art == 'input' else 'Lautsprecher'}: {info['name']}")

    andere = laufende_instanz()
    if andere:
        print(f"Das Gesprächsprogramm läuft schon (Prozess {andere}). Zwei gleichzeitig würden sich um "
              "Mikrofon und Lautsprecher streiten. Bitte das andere zuerst beenden.", file=sys.stderr)
        sys.exit(LAEUFT_SCHON)

    # Ohne Startoption gilt der Wert aus der Einstellungsdatei, Startoptionen gelten nur für diesen Lauf
    es = Einstellungen(args.einstellungen)

    schluessel = lies_anthropic_schluessel()
    import anthropic

    # Persönlichkeiten; beim ersten Start ziehen die bisherigen Einzelwerte aus einstellungen.json nach Pixel
    persoenlichkeiten = pers.Persoenlichkeiten(PERSOENLICHKEITEN_DATEI, umzug=es.umgezogen)
    es.entferne_umgezogene()
    aktiv = args.persoenlichkeit or es["persoenlichkeit"]
    if not persoenlichkeiten.hole(aktiv):
        print(f"Persönlichkeit '{aktiv}' unbekannt, nehme Pixel.")
        aktiv = pers.STANDARD
    p = persoenlichkeiten.hole(aktiv)

    def wert(name, option):  # Startoption, sonst Persönlichkeit, sonst Einstellungsdatei
        if option is not None:
            return option
        return p[name] if name in pers.FELDER else es[name]

    system = p["system_prompt"] or SYSTEM_PROMPT
    if args.system:  # nur für diesen Lauf
        system = Path(args.system).read_text(encoding="utf-8").strip()

    import httpx2  # HTTP-Bibliothek des Anthropic-SDK

    # Verbindung länger offen halten, spart eine neue TLS-Verbindung (gemessen ca. 0,06 s pro Frage)
    http_client = anthropic.DefaultHttpxClient(limits=httpx2.Limits(
        max_connections=10, max_keepalive_connections=5, keepalive_expiry=CLAUDE_VERBINDUNG_OFFEN_S))
    client = anthropic.Anthropic(api_key=schluessel, timeout=CLAUDE_TIMEOUT_S,
                                 max_retries=CLAUDE_WIEDERHOLUNGEN, http_client=http_client)
    erkenne = baue_cloud_erkenner("deepgram", None)
    try:
        voice = stimmen.baue_stimme(wert("stimme", args.stimme))
    except (ValueError, RuntimeError) as fehler:
        if args.stimme:
            sys.exit(f"Stimme: {fehler}")
        # z. B. Google-Stimme ohne GOOGLE_TTS_API_KEY: mit der lokalen Stimme weitermachen
        print(f"Stimme {wert('stimme', None)} nicht ladbar ({fehler}), nehme {stimmen.STANDARD_STIMME}.")
        voice = stimmen.baue_stimme(stimmen.STANDARD_STIMME)
    protokoll = Protokoll()
    zeiten = Protokoll(ZEITEN, ZEITEN_SPALTEN, sitzung=protokoll.sitzung)
    grenzen = Grenzen(wert("schlafenszeit", args.schlafenszeit), wert("tageslimit_cent", args.tageslimit_cent),
                      wert("max_fragen", args.max_fragen), es["tageslimit_cent_erwachsene"])
    gespraech = Gespraech(client, wert("modell", args.modell), system, voice, erkenne, protokoll, grenzen,
                          wert("lautstaerke", args.lautstaerke), zeiten, einstellungen=es,
                          folge_s=wert("folge", args.folge), ack=wert("bestaetigung", args.ack), status=Status(),
                          persoenlichkeiten=persoenlichkeiten, aktiv=aktiv,
                          kinder=kinder_mod.Kinder(Path(args.einstellungen).parent / "kinder.json"))
    gespraech.status.quelle = gespraech.status_werte
    print(f"Einstellungen: {es.pfad} (Änderungen gelten ab der nächsten Frage)")
    print(f"Protokolle: {protokoll.pfad.name} (Kosten), {zeiten.pfad.name} (Wartezeiten) in {protokoll.pfad.parent}")
    print(f"Grenzen: {grenzen.beschreibung()} | heute bisher {gespraech.heute_kosten * 100:.2f} US-Cent, "
          f"{gespraech.heute_fragen} Fragen, Erwachsene {gespraech.heute_kosten_erwachsene * 100:.2f} US-Cent")

    print("Hinweis: Text der Gespräche geht an Anthropic (Claude), Aufnahmen an Deepgram.")
    print(f"Persönlichkeit: {gespraech.persoenlichkeit_name}")
    k = gespraech.kind_daten
    print(f"Kind: {gespraech.kind} ({kinder_mod.klasse_text(k['klasse'])})" if k else
          "Kind: noch keins angemeldet (\"Ich bin …\", Profile in der Oberfläche anlegen)")
    print(f"Claude-Modell: {gespraech.modell}")
    print(f"Stimme: {voice.kennung}")
    if not voice.kennung.startswith("piper:"):
        print("Hinweis: Die Antworttexte gehen zur Sprachausgabe an den Anbieter der Stimme.")

    try:
        if args.modus == "taste":
            modus_taste(gespraech, args.dauer)
            return

        print("Lade Wake-Word- und Sprechpausen-Erkennung ...")
        hoerer = gespraech.hoerer = Hoerer(
            wakeword=wert("wakeword", args.wakeword), ww_schwelle=wert("ww_schwelle", args.ww_schwelle),
            vad_schwelle=args.vad_schwelle, pause_s=wert("pause", args.pause), debug=args.debug,
        )
        gespraech.pause_basis = hoerer.pause_s  # mit Startoption --pause; Kinder können davon abweichen
        if args.modus == "dauerhaft":
            modus_dauerhaft(gespraech, hoerer)
        else:
            modus_wakeword(gespraech, hoerer)
    except KeyboardInterrupt:
        print("\nTschüss!")
    finally:
        gespraech.melde("aus")
        if any(gespraech.anfragen.values()):
            print(f"Kosten dieser Sitzung: {gespraech.kosten_zusammenfassung()}")
        if gespraech.wartezeit_zusammenfassung():
            print(gespraech.wartezeit_zusammenfassung())


if __name__ == "__main__":
    main()
