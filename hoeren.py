"""
Zuhören für Pixel: Wake Word und Sprechpausen-Erkennung.

- Wake Word: openWakeWord (läuft lokal, nichts geht ins Netz)
- Sprechpausen-Erkennung: Silero-VAD, wird von openWakeWord mitgeliefert (ebenfalls lokal)

Es werden nur kurze Audioblöcke (80 ms) im Speicher verarbeitet. Erst wenn das Wake Word
erkannt wurde und jemand spricht, wird die Aufnahme bis zur Sprechpause gesammelt.
"""
import collections
import glob
import inspect
import os
import warnings

import numpy as np
import sounddevice as sd

# Harmlose Meldung von onnxruntime auf Rechnern ohne NVIDIA-GPU
warnings.filterwarnings("ignore", message=".*CUDAExecutionProvider.*")

RATE = 16000
BLOCK = 1280                 # 80 ms bei 16 kHz, so viel erwartet openWakeWord pro Aufruf
BLOCK_S = BLOCK / RATE
VAD_FRAME = 640              # Blockgröße für die Sprechpausen-Erkennung
VORLAUF_BLOECKE = 6          # ca. 0,5 s vor dem Sprechbeginn mitnehmen (Satzanfang nicht abschneiden)
SPRECHBEGINN_BLOECKE = 2     # so viele Sprachblöcke hintereinander gelten als Sprechbeginn (160 ms)
WAKEWORD_ORDNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wakewords")  # eigene Modelle
STANDARD_WAKEWORD = "hey_pixel"
ERSATZ_WAKEWORD = "hey_mycroft"  # mitgeliefert, falls das eigene Modell fehlt
NACHLAUF_BLOECKE = 5         # ca. 0,4 s Stille am Ende der Aufnahme behalten
LEEREN_S = 2.5               # so viel Stille vor dem Warten aufs Wake Word durch das Modell schieben


def anzeigename(wakeword):
    """'hey_pixel' oder 'wakewords/hey_pixel.onnx' -> 'Hey Pixel'."""
    name = os.path.splitext(os.path.basename(wakeword))[0]
    return " ".join(teil.capitalize() for teil in name.split("_"))


def finde_wakeword_modell(name):
    """Pfad zur .onnx-Datei des Wake-Word-Modells. 'name' ist ein Modellname oder ein Dateipfad."""
    import openwakeword

    if os.path.isfile(name):
        return name
    eigenes = os.path.join(WAKEWORD_ORDNER, f"{name}.onnx")  # z. B. wakewords/hey_pixel.onnx
    if os.path.isfile(eigenes):
        return eigenes
    mitgeliefert = getattr(openwakeword, "models", {})
    if name in mitgeliefert and os.path.isfile(mitgeliefert[name].get("model_path", "")):
        return mitgeliefert[name]["model_path"]
    ordner = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
    treffer = sorted(glob.glob(os.path.join(ordner, f"{name}_v*.onnx")))
    if not treffer and hasattr(openwakeword, "utils"):
        try:
            openwakeword.utils.download_models()
            treffer = sorted(glob.glob(os.path.join(ordner, f"{name}_v*.onnx")))
        except Exception:
            pass
    if not treffer:
        keine_wakewords = {"silero", "timer", "weather", "melspectrogram", "embedding"}  # andere Modelle im Paket
        namen = sorted({os.path.basename(p).split("_v")[0] for p in glob.glob(os.path.join(ordner, "*_v*.onnx"))}
                       - keine_wakewords)
        eigene = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(WAKEWORD_ORDNER, "*.onnx")))
        raise FileNotFoundError(
            f"Wake-Word-Modell '{name}' nicht gefunden. Eigene in wakewords/: {', '.join(eigene) or 'keine'}; "
            f"mitgeliefert: {', '.join(namen)}; oder der Pfad zu einer .onnx-Datei."
        )
    return treffer[-1]


class Hoerer:
    def __init__(self, wakeword=STANDARD_WAKEWORD, ww_schwelle=0.5, vad_schwelle=0.5,
                 pause_s=1.2, max_dauer_s=15.0, min_sprache_s=0.15, debug=False):
        from openwakeword.vad import VAD

        self.ww_schwelle = ww_schwelle
        self.vad_schwelle = vad_schwelle
        self.pause_s = pause_s
        self.max_dauer_s = max_dauer_s
        self.min_sprache_s = min_sprache_s
        self.debug = debug
        self.letzte_pause_s = 0.0

        if not self.lade_wakeword(wakeword) and wakeword != ERSATZ_WAKEWORD:
            print(f"WARNUNG: Wake Word '{wakeword}' nicht gefunden, nehme '{ERSATZ_WAKEWORD}'.")
            if not self.lade_wakeword(ERSATZ_WAKEWORD):
                raise FileNotFoundError(f"Auch das Ersatz-Wake-Word '{ERSATZ_WAKEWORD}' fehlt.")
        self.vad = VAD()

    def lade_wakeword(self, wakeword):
        """Wake-Word-Modell laden (Name oder Pfad). Gibt False zurück, wenn es nicht gefunden wird;
        dann bleibt das bisherige Modell aktiv."""
        from openwakeword.model import Model

        try:
            pfad = finde_wakeword_modell(wakeword)
        except FileNotFoundError as fehler:
            print(f"  [Wake Word] {fehler}")
            return False
        # Je nach openWakeWord-Version heißt der Parameter anders
        parameter = inspect.signature(Model.__init__).parameters
        schluessel = "wakeword_models" if "wakeword_models" in parameter else "wakeword_model_paths"
        try:
            self.ww = Model(**{schluessel: [pfad]}, inference_framework="onnx")
        except TypeError:
            self.ww = Model(**{schluessel: [pfad]})
        self.wakeword = wakeword
        return True

    # ------------------------------------------------------------------ Hilfen
    @staticmethod
    def _stream():
        return sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK)

    @staticmethod
    def _lies(stream):
        daten, _ueberlauf = stream.read(BLOCK)
        return np.asarray(daten[:, 0]).copy()

    def _ist_sprache(self, block):
        return float(self.vad.predict(block, frame_size=VAD_FRAME)) >= self.vad_schwelle

    # --------------------------------------------------------------- Wake Word
    def _leere_wakeword_puffer(self):
        """Audio-Merkmale des letzten Wake Words aus openWakeWord entfernen.

        reset() leert in openWakeWord 0.4.0 nur die Score-Liste. Die Merkmale der letzten
        Sekunden bleiben und enthalten noch das alte Wake Word, das dann sofort wieder auslöst.
        Deshalb einige Sekunden Stille hinterherschieben, danach die Scores zurücksetzen.
        """
        stille = np.zeros(BLOCK, dtype=np.int16)
        for _ in range(int(LEEREN_S / BLOCK_S)):
            self.ww.predict(stille)
        self.ww.reset()

    def warte_auf_wakeword(self):
        """Blockiert, bis das Wake Word erkannt wurde. Gibt den Score (0 bis 1) zurück."""
        self._leere_wakeword_puffer()
        with self._stream() as stream:
            while True:
                punkte = self.ww.predict(self._lies(stream))
                wert = float(max(punkte.values())) if punkte else 0.0
                if self.debug and wert >= 0.2:
                    print(f"  [Wake Word] Score {wert:.2f} (Schwelle {self.ww_schwelle:.2f})")
                if wert >= self.ww_schwelle:
                    return wert

    # --------------------------------------------------------- Sprechpausen-VAD
    def nimm_bis_pause(self, start_timeout_s=5.0, verwerfe_s=0.25):
        """Wartet auf Sprache und nimmt auf, bis eine Sprechpause erkannt wird.

        start_timeout_s: so lange auf den Sprechbeginn warten (None = unbegrenzt).
        verwerfe_s: erste Zeit nach dem Öffnen des Mikrofons ignorieren (Nachhall, Klingeln).
        Gibt float32-Audio (16 kHz, mono) zurück oder None, wenn niemand gesprochen hat.
        """
        self.vad.reset_states()
        self.letzte_pause_s = 0.0  # Stille nach dem letzten Wort, bis die Aufnahme endete (Wartezeit)
        vorlauf = collections.deque(maxlen=VORLAUF_BLOECKE)
        aufnahme = []
        wartebloecke = 0
        in_folge = 0
        sprachbloecke = 0
        stille_s = 0.0
        letzter_sprachblock = -1
        laeuft = False

        with self._stream() as stream:
            for _ in range(int(verwerfe_s / BLOCK_S)):
                self._lies(stream)
            while True:
                block = self._lies(stream)
                sprache = self._ist_sprache(block)

                if not laeuft:
                    vorlauf.append(block)
                    in_folge = in_folge + 1 if sprache else 0
                    if in_folge >= SPRECHBEGINN_BLOECKE:
                        laeuft = True
                        aufnahme = list(vorlauf)
                        sprachbloecke = in_folge
                        letzter_sprachblock = len(aufnahme) - 1
                        continue
                    wartebloecke += 1
                    if start_timeout_s is not None and wartebloecke * BLOCK_S >= start_timeout_s:
                        return None
                    continue

                aufnahme.append(block)
                if sprache:
                    sprachbloecke += 1
                    stille_s = 0.0
                    letzter_sprachblock = len(aufnahme) - 1
                else:
                    stille_s += BLOCK_S
                if stille_s >= self.pause_s:
                    break
                if len(aufnahme) * BLOCK_S >= self.max_dauer_s:
                    break

        self.letzte_pause_s = stille_s
        if sprachbloecke * BLOCK_S < self.min_sprache_s:
            return None  # nur ein Knacken. Nicht höher setzen: Ein einzelnes Wort ("cat", "ja") hat nur 0,2 bis 0,3 s
        ende = min(len(aufnahme), letzter_sprachblock + 1 + NACHLAUF_BLOECKE)
        audio = np.concatenate(aufnahme[:ende]).astype(np.float32) / 32768.0
        return audio
