"""
Sprachausgabe für Pixel: austauschbare Stimmen hinter derselben Schnittstelle.

Kennungen (Anbieter:Stimme):
    piper:de_DE-kerstin-low            lokal, kostenlos, funktioniert ohne Internet
    google:de-DE-Chirp3-HD-Aoede       Google Cloud TTS, Schlüssel in GOOGLE_TTS_API_KEY
    aura:aura-2-elara-de               Deepgram Aura-2, Schlüssel in DEEPGRAM_API_KEY

Jede Stimme hat synthetisiere(text) -> (int16-Daten, Samplerate) und vorwaermen().
Cloud-Stimmen werden mit MitErsatz umhüllt: Bei einem Fehler spricht Piper weiter.
"""
import base64
import io
import os
import re
import threading
import wave
from pathlib import Path

import numpy as np

STIMMEN_ORDNER = Path(__file__).parent / "voices"
STANDARD_STIMME = "piper:de_DE-kerstin-low"
CLOUD_TIMEOUT_S = 4  # danach spricht Piper (MitErsatz): lieber kurz andere Stimme als lange Stille

# Preise in US-Dollar pro 1 Mio. Zeichen und monatliche Freimenge in Zeichen, je Abrechnungsgruppe.
# Quellen (Stand Oktober 2026): cloud.google.com/text-to-speech/pricing, deepgram.com/pricing.
# Google: Standard und WaveNet teilen sich eine Freimenge (gleiche SKU), Neural2 und Polyglot ebenso.
PREISGRUPPEN = {
    "google-chirp3": (30.0, 1_000_000),
    "google-neural2": (16.0, 1_000_000),
    "google-standard": (4.0, 4_000_000),
    "google-studio": (160.0, 1_000_000),
    "aura": (30.0, 0),  # keine Freimenge, wird vom Deepgram-Startguthaben abgezogen
}


def _wav_zu_daten(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16), wf.getframerate()


def _fehlertext(antwort):
    """Kurze Fehlermeldung aus der Antwort (Google: error.message, Deepgram: err_msg)."""
    try:
        daten = antwort.json()
        return (daten.get("error") or {}).get("message") or daten.get("err_msg") or antwort.text[:200]
    except ValueError:
        return antwort.text[:200]


def _lies_schluessel(variable):
    """Schlüssel aus der Umgebung lesen. Unter Windows auch aus den Benutzervariablen, falls das
    Programm gestartet wurde, bevor die Variable gesetzt war. Der Schlüssel wird nie ausgegeben."""
    schluessel = os.environ.get(variable, "").strip()
    if not schluessel and os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                schluessel = str(winreg.QueryValueEx(k, variable)[0]).strip()
        except OSError:
            pass
    if not schluessel:
        raise RuntimeError(f"Umgebungsvariable {variable} fehlt")
    return schluessel


class PiperStimme:
    preisgruppe = None

    def __init__(self, name):
        from piper import PiperVoice
        from piper.download_voices import download_voice

        self.kennung = f"piper:{name}"
        STIMMEN_ORDNER.mkdir(exist_ok=True)
        onnx = STIMMEN_ORDNER / f"{name}.onnx"
        if not onnx.exists():
            print(f"Lade Stimme {name} herunter ...")
            download_voice(name, STIMMEN_ORDNER)
        self.voice = PiperVoice.load(onnx)

    def synthetisiere(self, text):
        puffer = io.BytesIO()
        with wave.open(puffer, "wb") as wf:
            self.voice.synthesize_wav(text, wf)
        return _wav_zu_daten(puffer.getvalue())

    def vorwaermen(self):
        pass  # lokal, nichts zu tun


class _CloudStimme:
    """Gemeinsame Teile: offene Verbindung (Session) und Vorwärmen im Hintergrund."""

    basis = ""

    def __init__(self):
        import requests

        self.sitzung = requests.Session()

    def _waerme(self):
        try:
            self.sitzung.head(self.basis, timeout=5)  # nur Verbindungsaufbau, ohne Text
        except Exception:
            pass

    def vorwaermen(self):
        threading.Thread(target=self._waerme, daemon=True).start()


class GoogleStimme(_CloudStimme):
    # EU-Endpunkt: Texte werden in der EU verarbeitet (Chirp 3: HD gibt es global, eu und us)
    basis = "https://eu-texttospeech.googleapis.com/"

    def __init__(self, name):
        super().__init__()
        self.kennung = f"google:{name}"
        self.name = name
        self.sprache = "-".join(name.split("-")[:2])  # de-DE-Chirp3-HD-Aoede -> de-DE
        typ = name.split("-")[2].lower()
        self.preisgruppe = {"chirp3": "google-chirp3", "neural2": "google-neural2", "polyglot": "google-neural2",
                            "studio": "google-studio"}.get(typ, "google-standard")
        self.sitzung.headers["X-goog-api-key"] = _lies_schluessel("GOOGLE_TTS_API_KEY")

    def synthetisiere(self, text):
        antwort = self.sitzung.post(f"{self.basis}v1/text:synthesize", timeout=CLOUD_TIMEOUT_S, json={
            "input": {"text": text},
            "voice": {"languageCode": self.sprache, "name": self.name},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000},
        })
        if not antwort.ok:
            raise RuntimeError(f"Google TTS: HTTP {antwort.status_code}: {_fehlertext(antwort)}")
        return _wav_zu_daten(base64.b64decode(antwort.json()["audioContent"]))  # LINEAR16 kommt als WAV


class AuraStimme(_CloudStimme):
    basis = "https://api.deepgram.com/"
    preisgruppe = "aura"
    RATE = 24000

    def __init__(self, modell):
        super().__init__()
        self.kennung = f"aura:{modell}"
        self.modell = modell
        self.sitzung.headers["Authorization"] = f"Token {_lies_schluessel('DEEPGRAM_API_KEY')}"

    def synthetisiere(self, text):
        antwort = self.sitzung.post(
            f"{self.basis}v1/speak", timeout=CLOUD_TIMEOUT_S, json={"text": text},
            params={"model": self.modell, "encoding": "linear16", "sample_rate": self.RATE, "container": "none"},
        )
        if not antwort.ok:
            raise RuntimeError(f"Deepgram Aura: HTTP {antwort.status_code}: {_fehlertext(antwort)}")
        return np.frombuffer(antwort.content, dtype=np.int16), self.RATE


class MitErsatz:
    """Cloud-Stimme mit Piper als Ersatz: Der Roboter bleibt bei Netzproblemen nie stumm.

    letzte_zeichen: berechnete Zeichen des letzten Aufrufs (0, wenn Piper einspringen musste).
    """

    def __init__(self, stimme, ersatz):
        self.stimme = stimme
        self.ersatz = ersatz
        self.kennung = stimme.kennung
        self.preisgruppe = stimme.preisgruppe
        self.letzte_zeichen = 0

    def erzeuge(self, text):
        """(Daten, Rate, berechnete Zeichen) ohne gemeinsamen Zustand, damit mehrere Teile gleichzeitig
        erzeugt werden können. Musste Piper einspringen, sind es 0 berechnete Zeichen."""
        try:
            daten, rate = self.stimme.synthetisiere(text)
            return daten, rate, len(text)
        except Exception as fehler:
            print(f"  [TTS] FEHLER {self.kennung}: {fehler} -> Piper spricht")
            daten, rate = self.ersatz.synthetisiere(text)
            return daten, rate, 0

    def synthetisiere(self, text):
        daten, rate, self.letzte_zeichen = self.erzeuge(text)
        return daten, rate

    def vorwaermen(self):
        self.stimme.vorwaermen()


def baue_einzelstimme(kennung):
    """Stimme zur Kennung ohne Ersatz: Fehler kommen als Ausnahme an (z. B. für Hörproben)."""
    anbieter, _, name = kennung.partition(":")
    if anbieter == "piper":
        return PiperStimme(name)
    if anbieter == "google":
        return GoogleStimme(name)
    if anbieter == "aura":
        return AuraStimme(name)
    raise ValueError(f"Unbekannte Stimme '{kennung}'. Beispiele: piper:de_DE-kerstin-low, "
                     "google:de-DE-Chirp3-HD-Aoede, aura:aura-2-elara-de")


def baue_stimme(kennung, ersatz=None):
    """Stimme zur Kennung bauen. Cloud-Stimmen bekommen die Piper-Stimme 'ersatz' als Rückfall."""
    stimme = baue_einzelstimme(kennung)
    if isinstance(stimme, PiperStimme):
        return stimme
    return MitErsatz(stimme, ersatz or PiperStimme(STANDARD_STIMME.partition(":")[2]))


# Englische Stellen markiert Claude in Antworten mit <en>…</en> (Persönlichkeit mit stimme_englisch).
# Eine Markierung kann über mehrere Sätze gehen, deshalb wird der Zustand von Satz zu Satz weitergereicht.
_MARKE = re.compile(r"<\s*(/?)\s*en\s*>", re.IGNORECASE)
# Versteckte Marken, die nie vorgelesen werden (auch nicht unvollständig am Ende eines Satzes):
#   <loesung>fish</loesung>       erwartete Antwort einer Abfrage, Hinweiswort für die Spracherkennung
#   <ergebnis>richtig</ergebnis>  Bewertung der letzten Antwort des Kindes, für die Lernkartei
#   <thema>m2_einmaleins</thema>  Thema einer Aufgabe aus den Lernplänen Mathe, Deutsch, HSU (lernthemen.py)
#   <niveau>schwer</niveau>       vom Kind gewünschte Schwierigkeit (leicht, mittel, schwer)
#   <aufgabe>7x8</aufgabe>        Karte aus dem Einmaleins-Karteikasten (einmaleins.py)
_VERSTECKT = re.compile(r"<\s*(loesung|ergebnis|thema|niveau|aufgabe)\s*>(.*?)(?:<\s*/\s*\1\s*>|$)", re.IGNORECASE | re.DOTALL)


def _versteckte(text, art):
    return [" ".join(inhalt.split()) for name, inhalt in _VERSTECKT.findall(text)
            if name.lower() == art and inhalt.strip()]


def loesungen(text):
    """Inhalte der versteckten Marken <loesung>…</loesung>."""
    return _versteckte(text, "loesung")


def themen(text):
    """Inhalte der versteckten Marken <thema>…</thema> (IDs aus lernthemen.py)."""
    return [t.lower() for t in _versteckte(text, "thema")]


def aufgaben(text):
    """Inhalte der versteckten Marken <aufgabe>…</aufgabe> (Einmaleins-Karten wie 7x8 oder 56:7)."""
    return [a.lower().replace(" ", "").replace("·", "x").replace("*", "x") for a in _versteckte(text, "aufgabe")]


def niveau(text):
    """Inhalt der letzten versteckten Marke <niveau>…</niveau> (kleingeschrieben) oder None."""
    werte = [w.lower() for w in _versteckte(text, "niveau")]
    return werte[-1] if werte else None


def ergebnis(text):
    """True für <ergebnis>richtig</ergebnis>, False für falsch, None ohne Bewertung."""
    werte = [w.lower() for w in _versteckte(text, "ergebnis")]
    return ("richtig" in werte[0]) if werte and ("richtig" in werte[0] or "falsch" in werte[0]) else None


def ohne_loesung(text):
    """Text ohne alle versteckten Marken (Lösung, Ergebnis, Thema)."""
    return _VERSTECKT.sub("", text)


def zerlege_sprachen(text, englisch=False):
    """'Hund heißt <en>dog</en>.' -> ([("de", "Hund heißt"), ("en", "dog.")], False).

    englisch: ob der Text innerhalb einer offenen Markierung beginnt. Gibt die Teile und den Zustand am
    Ende zurück. Teile ohne Buchstaben oder Ziffern (z. B. ein Punkt) hängen am vorherigen Teil.
    """
    text = ohne_loesung(text)
    teile, pos = [], 0
    for treffer in [*_MARKE.finditer(text), None]:
        stueck = text[pos:treffer.start() if treffer else len(text)]
        sprache = "en" if englisch else "de"
        if stueck.strip():
            if teile and (teile[-1][0] == sprache or not re.search(r"\w", stueck)):
                teile[-1] = (teile[-1][0], f"{teile[-1][1]}{stueck}")
            else:
                teile.append((sprache, stueck))
        if treffer:
            englisch = treffer.group(1) != "/"
            pos = treffer.end()
    return [(s, " ".join(t.split())) for s, t in teile], englisch


def englische_stellen(text):
    """Jede Stelle in <en>…</en> einzeln, z. B. ["dog", "cat", "I see a big elephant."]."""
    return [" ".join(s.split()) for s in re.findall(r"<\s*en\s*>(.*?)<\s*/\s*en\s*>", text, re.IGNORECASE | re.DOTALL)]


def ohne_marken(text):
    return " ".join(_MARKE.sub("", ohne_loesung(text)).split())


def sprache_der_stimme(kennung):
    """'en' für englische Stimmen (piper:en_GB-…, google:en-GB-…, aura:…-en), sonst 'de'."""
    name = kennung.partition(":")[2].lower()
    return "en" if name.startswith("en") or name.endswith("-en") else "de"


def berechnete_zeichen(preisgruppe, zeichen, bisher_im_monat):
    """Wie viele der Zeichen über der monatlichen Freimenge liegen und bezahlt werden müssen."""
    if not preisgruppe:
        return 0
    frei = PREISGRUPPEN[preisgruppe][1]
    return max(0, bisher_im_monat + zeichen - frei) - max(0, bisher_im_monat - frei)


def kosten_usd(preisgruppe, zeichen_berechnet):
    if not preisgruppe:
        return 0.0
    return zeichen_berechnet * PREISGRUPPEN[preisgruppe][0] / 1_000_000
