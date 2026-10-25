"""
Sprachtest für Pixel (Windows, nur CPU)

Kette: Mikrofon -> Spracherkennung (STT) -> Text -> Piper (TTS) -> Lautsprecher

Spracherkennung wahlweise lokal (faster-whisper) oder in der Cloud (Deepgram, OpenAI).
API-Schlüssel werden NUR aus Umgebungsvariablen gelesen, nie aus Dateien:
    DEEPGRAM_API_KEY   für --stt deepgram
    OPENAI_API_KEY     für --stt openai

Start:
    python sprachtest.py                      # lokal, Modell small
    python sprachtest.py --stt deepgram       # Cloud: Deepgram Nova-3
    python sprachtest.py --stt openai         # Cloud: OpenAI gpt-transcribe
    python sprachtest.py --vergleich small deepgram openai --dauer 6
    python sprachtest.py --tts "Hallo, ich bin dein Roboterhund"
"""
import argparse
import io
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

BASIS = Path(__file__).parent
STIMME = "de_DE-kerstin-low"
MODELL_ORDNER = BASIS / "voices"
SAMPLERATE_AUFNAHME = 16000  # Whisper und Cloud-Dienste kommen mit 16 kHz gut zurecht
STILLE_SCHWELLE = 0.005      # Spitzenpegel darunter: nichts an die Cloud senden (spart Kosten)
DEEPGRAM_TIMEOUT_S = 10      # länger soll ein Kind nicht warten, danach kommt eine Fehlermeldung

# Cloud-Anbieter: Name -> (Umgebungsvariable, Anzeigename)
CLOUD_ANBIETER = {
    "deepgram": ("DEEPGRAM_API_KEY", "Deepgram Nova-3"),
    "openai": ("OPENAI_API_KEY", "OpenAI gpt-transcribe"),
}


# --------------------------------------------------------------------------- TTS
def lade_stimme():
    """Piper-Stimme laden, bei Bedarf automatisch herunterladen."""
    from piper import PiperVoice
    from piper.download_voices import download_voice

    MODELL_ORDNER.mkdir(exist_ok=True)
    onnx = MODELL_ORDNER / f"{STIMME}.onnx"
    if not onnx.exists():
        print(f"Lade Stimme {STIMME} herunter ...")
        download_voice(STIMME, MODELL_ORDNER)
    return PiperVoice.load(onnx)


_ABSPIELRATE = {}  # (Wiedergabegerät, gewünschte Rate) -> Rate, die das Gerät kann


def abspielrate(rate):
    """Die gewünschte Rate, falls das Wiedergabegerät sie kann, sonst seine Standardrate.
    USB-Headsets können oft nur 16, 44,1 oder 48 kHz, Piper liefert aber auch 22,05 und Google 24 kHz."""
    schluessel = (sd.default.device[1], rate)
    if schluessel not in _ABSPIELRATE:
        try:
            sd.check_output_settings(samplerate=rate, channels=1, dtype="int16")
            _ABSPIELRATE[schluessel] = rate
        except Exception:
            _ABSPIELRATE[schluessel] = int(sd.query_devices(kind="output")["default_samplerate"])
            print(f"  [Audio] Gerät kann {rate} Hz nicht, rechne auf {_ABSPIELRATE[schluessel]} Hz um")
    return _ABSPIELRATE[schluessel]


def spiele(daten, rate):
    """int16-Audio abspielen und warten, bis es fertig ist. Rechnet die Abtastrate bei Bedarf um."""
    ziel = abspielrate(rate)
    if ziel != rate:
        n = int(len(daten) * ziel / rate)
        daten = np.interp(np.linspace(0, len(daten) - 1, n), np.arange(len(daten)), daten).astype(np.int16)
    sd.play(daten, ziel)
    sd.wait()


def sprich(voice, text):
    """Text mit Piper in eine WAV-Datei synthetisieren und abspielen."""
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        wav_pfad = Path(tmp) / "ausgabe.wav"
        with wave.open(str(wav_pfad), "wb") as wf:
            voice.synthesize_wav(text, wf)
        synth_zeit = time.time() - t0
        with wave.open(str(wav_pfad), "rb") as wf:
            rate = wf.getframerate()
            daten = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    print(f"  [TTS] {synth_zeit:.2f} s für {len(daten) / rate:.1f} s Audio")
    spiele(daten, rate)


# ----------------------------------------------------------------------- Aufnahme
def nimm_auf(sekunden):
    """Mikrofon für feste Dauer aufnehmen, als float32 (16 kHz, mono)."""
    print(f"Sprich jetzt ({sekunden} s) ...")
    aufnahme = sd.rec(
        int(sekunden * SAMPLERATE_AUFNAHME),
        samplerate=SAMPLERATE_AUFNAHME,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    return aufnahme[:, 0]


def audio_als_wav(audio):
    """float32-Audio (-1..1) als 16-Bit-Mono-WAV im Speicher."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLERATE_AUFNAHME)
        wf.writeframes(pcm.tobytes())
    return puffer.getvalue()


# --------------------------------------------------------------------- STT lokal
def baue_lokalen_erkenner(modellname, prompt):
    """faster-whisper laden (CPU, int8). Gibt eine Funktion audio -> (Text, Sekunden) zurück."""
    from faster_whisper import WhisperModel

    print(f"Lade Whisper-Modell '{modellname}' (beim ersten Mal Download, kann dauern) ...")
    stt = WhisperModel(modellname, device="cpu", compute_type="int8")

    def erkenne(audio):
        t0 = time.time()
        segmente, _info = stt.transcribe(
            audio, language="de", vad_filter=True, beam_size=5, initial_prompt=prompt
        )
        text = " ".join(s.text.strip() for s in segmente).strip()
        return text, time.time() - t0

    return erkenne


# --------------------------------------------------------------------- STT Cloud
def lies_schluessel(anbieter):
    """API-Schlüssel aus der Umgebungsvariable lesen oder mit Hinweis beenden."""
    variable, anzeige = CLOUD_ANBIETER[anbieter]
    schluessel = os.environ.get(variable, "").strip()
    if not schluessel:
        sys.exit(
            f"Umgebungsvariable {variable} fehlt (für {anzeige}).\n"
            f"PowerShell, nur für dieses Fenster:   $env:{variable} = \"DEIN_SCHLUESSEL\"\n"
            f"Dauerhaft für dein Benutzerkonto:     setx {variable} \"DEIN_SCHLUESSEL\"  "
            f"(danach neues Fenster öffnen)"
        )
    return schluessel


def _pruefe_antwort(antwort, anzeige):
    if not antwort.ok:
        raise RuntimeError(f"{anzeige}: HTTP {antwort.status_code}: {antwort.text[:200]}")


def baue_cloud_erkenner(anbieter, prompt):
    """Gibt eine Funktion audio -> (Text, Sekunden) für den Cloud-Anbieter zurück.

    Die Funktion hat zusätzlich erkenne.vorwaermen(): baut die Verbindung im Hintergrund auf,
    solange noch gesprochen wird. Eine neue TLS-Verbindung kostet ca. 0,5 s, und Deepgram
    schließt ungenutzte Verbindungen nach weniger als 20 s (gemessen Oktober 2026).
    """
    import threading

    import requests

    schluessel = lies_schluessel(anbieter)
    anzeige = CLOUD_ANBIETER[anbieter][1]
    print(f"Hinweis: Aufnahmen werden zur Erkennung an {anzeige} gesendet.")
    sitzung = requests.Session()  # hält die Verbindung offen, statt sie jedes Mal neu aufzubauen
    basis = "https://api.deepgram.com/" if anbieter == "deepgram" else "https://api.openai.com/"

    def _waerme():
        try:
            sitzung.head(basis, timeout=5)  # ohne Schlüssel und ohne Audio, nur Verbindungsaufbau
        except requests.RequestException:
            pass  # dann eben beim eigentlichen Senden

    def vorwaermen():
        threading.Thread(target=_waerme, daemon=True).start()

    def erkenne(audio, sprache="de", hinweise=()):
        """sprache: "de" oder "multi" (Deepgram: Deutsch und Englisch gemischt in einer Äußerung).
        hinweise: Wörter, die gerade erwartet werden (Deepgram Keyterm Prompting, z. B. die abgefragte Vokabel)."""
        if float(np.abs(audio).max()) < STILLE_SCHWELLE:
            return "", 0.0  # praktisch Stille: nichts senden, nichts bezahlen
        wav = audio_als_wav(audio)
        t0 = time.time()
        if anbieter == "deepgram":
            def sende():
                return sitzung.post(
                    "https://api.deepgram.com/v1/listen",
                    params=[("model", "nova-3"), ("language", sprache), ("smart_format", "true"),
                            *(("keyterm", h) for h in hinweise)],  # je Wort ein eigener keyterm-Parameter
                    headers={"Authorization": f"Token {schluessel}", "Content-Type": "audio/wav"},
                    data=wav,
                    timeout=DEEPGRAM_TIMEOUT_S,
                )
            try:
                antwort = sende()
            except requests.ConnectionError:
                # Deepgram hat die offene Verbindung inzwischen geschlossen ("Remote end closed connection"):
                # einmal mit neuer Verbindung wiederholen, statt das Kind um Wiederholung zu bitten
                print("  [STT] Verbindung war geschlossen, neuer Versuch ...")
                antwort = sende()
            _pruefe_antwort(antwort, anzeige)
            text = antwort.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
        else:  # openai
            daten = {"model": "gpt-transcribe"}
            if sprache != "multi":
                daten["languages[]"] = sprache
            if prompt:
                daten["prompt"] = prompt
            antwort = sitzung.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {schluessel}"},
                files={"file": ("aufnahme.wav", wav, "audio/wav")},
                data=daten,
                timeout=60,
            )
            _pruefe_antwort(antwort, anzeige)
            text = antwort.json()["text"]
        return text.strip(), time.time() - t0

    erkenne.vorwaermen = vorwaermen
    return erkenne


def baue_erkenner(name, prompt):
    """Name ist 'deepgram', 'openai' oder ein faster-whisper-Modellname."""
    if name in CLOUD_ANBIETER:
        return baue_cloud_erkenner(name, prompt)
    return baue_lokalen_erkenner(name, prompt)


# ----------------------------------------------------------------------- Modi
def vergleiche(namen, dauer, prompt):
    """Dieselbe Aufnahme mit mehreren Erkennern auswerten, zum direkten Vergleich."""
    erkenner = {name: baue_erkenner(name, prompt) for name in namen}

    print("\nVergleichsmodus. Enter = aufnehmen, 'q' + Enter = beenden.")
    print("Tipp: Lass dein Kind denselben Satz sprechen und vergleiche die Ergebnisse.\n")
    while True:
        if input("> ").strip().lower() == "q":
            break
        audio = nimm_auf(dauer)
        for name, erkenne in erkenner.items():
            try:
                text, sek = erkenne(audio)
                print(f"  {name:<16} {sek:5.2f} s  ->  \"{text}\"")
            except Exception as fehler:  # Netzwerk, Schlüssel, Limits ...
                print(f"  {name:<16} FEHLER: {fehler}")
        print()


def echo(voice, erkenne):
    """Aufnehmen, erkennen, Ergebnis laut vorlesen."""
    print("\nEcho-Modus. Enter = aufnehmen, 'q' + Enter = beenden.\n")
    while True:
        if input("> ").strip().lower() == "q":
            break
        audio = nimm_auf(ARGS.dauer)
        try:
            text, sek = erkenne(audio)
        except Exception as fehler:
            print(f"  [STT] FEHLER: {fehler}")
            continue
        print(f"  [STT] {sek:.2f} s -> \"{text}\"")
        if not text:
            print("  Nichts erkannt.")
            continue
        sprich(voice, f"Ich habe verstanden: {text}")


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--stt", choices=["lokal", "deepgram", "openai"], default="lokal",
                    help="Spracherkennung: lokal (faster-whisper), deepgram oder openai")
    ap.add_argument("--modell", default="small",
                    help="Whisper-Modell für --stt lokal: tiny, base, small, medium, "
                         "large-v3-turbo (Standard: small)")
    ap.add_argument("--dauer", type=float, default=5.0,
                    help="Aufnahmedauer in Sekunden (Standard: 5)")
    ap.add_argument("--tts", metavar="TEXT",
                    help="Nur TTS testen: diesen Text sprechen und beenden")
    ap.add_argument("--geraete", action="store_true",
                    help="Audiogeräte auflisten und beenden")
    ap.add_argument("--vergleich", nargs="+", metavar="ERKENNER",
                    help="Mehrere Erkenner mit derselben Aufnahme vergleichen, "
                         "z. B. --vergleich small medium deepgram openai")
    ap.add_argument("--prompt", default=None,
                    help="Optionaler Kontext, z. B. \"Ein Kind spricht mit seinem Roboterhund.\" "
                         "(wirkt bei lokal und openai, Deepgram ignoriert ihn)")
    ARGS = ap.parse_args()

    if ARGS.geraete:
        print(sd.query_devices())
        return

    if ARGS.vergleich:
        vergleiche(ARGS.vergleich, ARGS.dauer, ARGS.prompt)
        return

    voice = lade_stimme()

    if ARGS.tts:
        sprich(voice, ARGS.tts)
        return

    name = ARGS.modell if ARGS.stt == "lokal" else ARGS.stt
    echo(voice, baue_erkenner(name, ARGS.prompt))


if __name__ == "__main__":
    main()
