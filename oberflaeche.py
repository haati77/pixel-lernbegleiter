"""
Handy-Oberfläche für Pixel: Status ansehen und Einstellungen ändern, im Heimnetz.

Start:
    python oberflaeche.py                 # erreichbar im Heimnetz unter http://<Rechnername>:8080
    python oberflaeche.py --nur-lokal     # nur auf diesem Rechner (http://localhost:8080)

Läuft getrennt von gespraech.py und braucht nur die Python-Standardbibliothek. Liest status.json,
einstellungen.json und die Protokolle, schreibt nur einstellungen.json. Ist die Umgebungsvariable
PIDOG_ELTERN_PIN gesetzt, ist der Zugang nur mit dieser PIN möglich, sonst für jeden im Heimnetz.
"""
import argparse
import csv
import hmac
import http.cookies
import json
import os
import re
import secrets
import socket
import statistics
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import kinder as kinder_mod
import lernkartei
import lernthemen
import einmaleins
import persoenlichkeiten as pers
import sticker as sticker_mod
import tagebuch as tagebuch_mod
import prompts
from einstellungen import FELDER, Einstellungen

BASIS = Path(__file__).parent
HTML = BASIS / "oberflaeche.html"
STATUS = BASIS / "status.json"
KOSTEN = BASIS / "protokoll" / "kosten.csv"
ZEITEN = BASIS / "protokoll" / "zeiten.csv"

SITZUNG_GUELTIG_S = 12 * 3600   # so lange bleibt man nach der PIN-Eingabe angemeldet
MAX_FEHLVERSUCHE = 5            # danach wird gesperrt
SPERRE_S = 5 * 60
LEBENSZEICHEN_S = 30            # status.json älter als das: gespraech.py läuft nicht

# Nur diese Modelle bietet die Oberfläche an (wie die Sprachbefehle, kein Opus)
MODELLE = [
    {"kennung": "claude-haiku-5-5", "name": "Haiku (schnell)", "kosten": "ca. 0,01 Cent pro Frage"},
    {"kennung": "claude-sonnet-5-5", "name": "Sonnet (klug)", "kosten": "ca. 0,23 Cent pro Frage"},
]
# Preisgruppen wie in stimmen.py: US-Dollar pro 1 Mio. Zeichen, Freimenge pro Monat
PREISGRUPPEN = {"google-chirp3": (30.0, 1_000_000), "google-neural2": (16.0, 1_000_000),
                "google-standard": (4.0, 4_000_000), "aura": (30.0, 0)}


# ------------------------------------------------------------------ Hilfen
def lies_umgebung(variable):
    """Wert aus der Umgebung, unter Windows auch aus den Benutzervariablen. Wird nie ausgegeben."""
    wert = os.environ.get(variable, "").strip()
    if not wert and os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                wert = str(winreg.QueryValueEx(k, variable)[0]).strip()
        except OSError:
            pass
    return wert


def lies_csv(pfad):
    try:
        with open(pfad, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f, delimiter=";"))
    except OSError:
        return []


def zahl(text):
    try:
        return float((text or "").replace(",", "."))
    except ValueError:
        return None


# ------------------------------------------------------------------ Stimmen
class Stimmenliste:
    """Verfügbare Stimmen. Piper aus dem Ordner voices, Google und Aura werden im Hintergrund abgefragt."""

    def __init__(self):
        self.cloud = []
        threading.Thread(target=self._lade_cloud, daemon=True).start()

    def _lade_cloud(self):
        stimmen = []
        schluessel = lies_umgebung("GOOGLE_TTS_API_KEY")
        for sprache, typen in (("de-DE", ("Chirp3", "Neural2")), ("en-GB", ("Chirp3",))):
            if not schluessel:
                break
            try:
                anfrage = urllib.request.Request(
                    f"https://texttospeech.googleapis.com/v1/voices?languageCode={sprache}",
                    headers={"X-goog-api-key": schluessel})
                with urllib.request.urlopen(anfrage, timeout=15) as antwort:
                    for v in json.load(antwort).get("voices", []):
                        name = v["name"]  # z. B. de-DE-Chirp3-HD-Aoede
                        typ = name.split("-")[2]
                        if typ not in typen or not name.startswith(sprache):
                            continue
                        stimmen.append({
                            "kennung": f"google:{name}", "anbieter": "Google",
                            "name": f"{'Chirp 3' if typ == 'Chirp3' else 'Neural2'} {name.split('-')[-1]}",
                            "geschlecht": {"FEMALE": "w", "MALE": "m"}.get(v.get("ssmlGender"), ""),
                            "gruppe": "google-chirp3" if typ == "Chirp3" else "google-neural2",
                            "sprache": sprache[:2]})
            except Exception as fehler:
                print(f"[Stimmen] Google ({sprache}) nicht abrufbar: {fehler}")
        try:  # Deepgram-Modellliste ist ohne Schlüssel abrufbar
            with urllib.request.urlopen("https://api.deepgram.com/v1/models", timeout=15) as antwort:
                for m in json.load(antwort).get("tts", []):
                    kennung = m.get("canonical_name", "")
                    if kennung.endswith("-de"):
                        tags = (m.get("metadata") or {}).get("tags") or []
                        stimmen.append({
                            "kennung": f"aura:{kennung}", "anbieter": "Deepgram Aura",
                            "name": kennung.split("-")[2].capitalize(),
                            "geschlecht": "w" if "feminine" in tags else "m" if "masculine" in tags else "",
                            "gruppe": "aura", "sprache": "de"})
        except Exception as fehler:
            print(f"[Stimmen] Deepgram nicht abrufbar: {fehler}")
        self.cloud = stimmen

    def alle(self, aktuelle=()):
        import stimmen

        piper = [{"kennung": f"piper:{p.stem}", "anbieter": "Piper (lokal)",
                  "name": p.stem.split("-")[1].replace("_", " ").capitalize() + f" ({p.stem.split('-')[2]})",
                  "geschlecht": "", "gruppe": None, "sprache": stimmen.sprache_der_stimme(f"piper:{p.stem}")}
                 for p in sorted((BASIS / "voices").glob("*.onnx"))]
        liste = piper + self.cloud
        bekannt = {s["kennung"] for s in liste}
        for kennung in aktuelle:  # eingestellte Stimme immer anzeigen, auch wenn die Liste fehlt
            if kennung and kennung not in bekannt:
                liste.append({"kennung": kennung, "anbieter": "Weitere", "name": kennung, "geschlecht": "",
                              "gruppe": None, "sprache": stimmen.sprache_der_stimme(kennung)})
        return liste


def verzoegerung_je_stimme():
    """Gemessene Zeit der Sprachausgabe für den ersten Satz (Median) je Stimme aus zeiten.csv."""
    werte = {}
    for z in lies_csv(ZEITEN):
        s, wert = z.get("stimme"), zahl(z.get("tts_erster_satz_s"))
        if s and wert is not None:
            werte.setdefault(s, []).append(wert)
    return {s: {"median_s": round(statistics.median(w), 2), "messungen": len(w)} for s, w in werte.items()}


def kosten_text(gruppe):
    if not gruppe:
        return "kostenlos"
    preis, frei = PREISGRUPPEN.get(gruppe, (0, 0))
    pro_antwort = 200 * preis / 1_000_000 * 100  # Cent für eine Antwort mit 200 Zeichen
    if frei:
        text = f"frei bis {frei / 1e6:g} Mio. Zeichen im Monat, danach {pro_antwort:.2f} Cent pro Antwort"
    else:
        text = f"ca. {pro_antwort:.1f} Cent pro Antwort"
    return text.replace(".", ",").replace("Mio,", "Mio.")  # deutsches Zahlenformat


# ------------------------------------------------------------------ Auswertung
def tageswerte():
    """Kosten und Fragen von heute sowie Zeichen der Cloud-Stimmen im Monat, aus kosten.csv."""
    heute, monat = time.strftime("%Y-%m-%d"), time.strftime("%Y-%m")
    kosten = {"claude": 0.0, "deepgram": 0.0, "tts": 0.0}
    fragen = 0
    zeichen = {}
    for z in lies_csv(KOSTEN):
        zeit = z.get("zeitpunkt") or ""
        dienst = z.get("dienst")
        if zeit.startswith(heute):
            kosten[dienst] = kosten.get(dienst, 0.0) + (zahl(z.get("kosten_usd")) or 0.0)
            if dienst == "claude" and z.get("status") != "fehler":
                fragen += 1
        if dienst == "tts" and zeit.startswith(monat):
            gruppe = z.get("status") or ""
            zeichen[gruppe] = zeichen.get(gruppe, 0) + int(zahl(z.get("zeichen")) or 0)
    freimenge = {g: {"genutzt": zeichen.get(g, 0), "frei": PREISGRUPPEN[g][1]}
                 for g in PREISGRUPPEN if PREISGRUPPEN[g][1] and zeichen.get(g)}
    return {"kosten_cent": {k: round(v * 100, 3) for k, v in kosten.items()},
            "summe_cent": round(sum(kosten.values()) * 100, 3), "fragen": fragen, "freimenge": freimenge}


def _median(werte):
    return round(statistics.median(werte), 2) if werte else None


def auswertung(tage):
    """Kosten pro Tag, Monatswerte, Wartezeit und Fehler der letzten 'tage' Tage aus den Protokollen."""
    heute = time.localtime()
    tagesliste = [time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400)) for i in range(tage - 1, -1, -1)]
    erster_tag = tagesliste[0]
    monat = time.strftime("%Y-%m", heute)

    # --- Kosten
    pro_tag = {t: {"claude": 0.0, "deepgram": 0.0, "tts": 0.0, "fragen": 0} for t in tagesliste}
    monat_kosten, monat_fragen = 0.0, 0
    fehler = {"claude": 0, "deepgram": 0, "max_tokens": 0}
    modelle = {}
    for z in lies_csv(KOSTEN):
        tag = (z.get("zeitpunkt") or "")[:10]
        dienst, kosten = z.get("dienst"), zahl(z.get("kosten_usd")) or 0.0
        ist_frage = dienst == "claude" and z.get("status") != "fehler"
        if tag.startswith(monat):
            monat_kosten += kosten
            monat_fragen += ist_frage
        if tag < erster_tag or tag not in pro_tag:
            continue
        if dienst in ("claude", "deepgram", "tts"):
            pro_tag[tag][dienst] += kosten
        pro_tag[tag]["fragen"] += ist_frage
        if z.get("status") == "fehler" and dienst in fehler:
            fehler[dienst] += 1
        if dienst == "claude" and z.get("status") == "max_tokens":
            fehler["max_tokens"] += 1
        if ist_frage:
            m = modelle.setdefault(z.get("modell") or "?", {"fragen": 0, "kosten": 0.0})
            m["fragen"] += 1
            m["kosten"] += kosten
    zeitraum_kosten = sum(d["claude"] + d["deepgram"] + d["tts"] for d in pro_tag.values())
    zeitraum_fragen = sum(d["fragen"] for d in pro_tag.values())
    tage_im_monat = (time.mktime((heute.tm_year + heute.tm_mon // 12, heute.tm_mon % 12 + 1, 1, 0, 0, 0, 0, 0, -1))
                     - time.mktime((heute.tm_year, heute.tm_mon, 1, 0, 0, 0, 0, 0, -1))) / 86400
    hochrechnung = monat_kosten / heute.tm_mday * round(tage_im_monat)

    # --- Wartezeit (nur Antworten mit Sprechpause, also mit Mikrofon)
    teile = {"pause_s": [], "stt_s": [], "claude_erster_satz_s": [], "tts_erster_satz_s": [], "warten_s": []}
    stimmen, claude_je_modell = {}, {}
    for z in lies_csv(ZEITEN):
        if (z.get("zeitpunkt") or "")[:10] < erster_tag:
            continue
        werte = {k: zahl(z.get(k)) for k in teile}
        gespraech = z.get("art") != "geschichte"  # Geschichten haben andere Wartezeiten
        if gespraech and werte["pause_s"] is not None and werte["warten_s"] is not None:
            for k, w in werte.items():
                if w is not None:
                    teile[k].append(w)
        s = stimmen.setdefault(z.get("stimme") or "piper:de_DE-kerstin-low", {"tts": [], "warten": []})
        if werte["tts_erster_satz_s"] is not None:
            s["tts"].append(werte["tts_erster_satz_s"])
        if gespraech and werte["pause_s"] is not None and werte["warten_s"] is not None:
            s["warten"].append(werte["warten_s"])
        if gespraech and werte["claude_erster_satz_s"] is not None:
            claude_je_modell.setdefault(z.get("modell") or "?", []).append(werte["claude_erster_satz_s"])

    for kennung, m in modelle.items():
        m["kosten_pro_frage_cent"] = round(m.pop("kosten") / m["fragen"] * 100, 4)
        m["claude_erster_satz_s"] = _median(claude_je_modell.get(kennung, []))

    return {
        "tage": [{"tag": t, **{k: round(v * 100, 4) if k != "fragen" else v for k, v in d.items()}}
                 for t, d in pro_tag.items()],
        "zeitraum": {"kosten_cent": round(zeitraum_kosten * 100, 3), "fragen": zeitraum_fragen,
                     "pro_frage_cent": round(zeitraum_kosten / zeitraum_fragen * 100, 4) if zeitraum_fragen else None},
        "monat": {"kosten_cent": round(monat_kosten * 100, 3), "fragen": monat_fragen,
                  "hochrechnung_cent": round(hochrechnung * 100, 2)},
        "wartezeit": {"antworten": len(teile["warten_s"]), **{k: _median(v) for k, v in teile.items()}},
        "stimmen": [{"kennung": k, "messungen": len(v["tts"]), "tts_s": _median(v["tts"]),
                     "warten_s": _median(v["warten"])} for k, v in stimmen.items()],
        "modelle": [{"kennung": k, **v} for k, v in modelle.items()],
        "fehler": fehler,
    }


# ------------------------------------------------------------------ Hörproben
PROBE_TEXT = ("Hallo, ich bin dein Roboterhund. Wusstest du, dass Eulen ihren Kopf fast ganz herumdrehen können? "
              "Schlaf gut und träum was Schönes.")
PROBE_TEXT_EN = "Hello, I am Mister Pixel. Can you say: I have got a little dog? Well done!"


def probe_text(kennung):
    import stimmen

    return PROBE_TEXT_EN if stimmen.sprache_der_stimme(kennung) == "en" else PROBE_TEXT
PROBEN = BASIS / "cache" / "proben"


class Hoerproben:
    """Erzeugt Hörproben mit der gewählten Stimme und speichert sie zwischen. Jede Stimme kostet
    höchstens einmal Zeichen (Google: Freimenge, Aura: ca. 0,4 Cent), danach kommt die Probe aus
    dem Zwischenspeicher. Erzeugt wird ohne Piper-Ersatz, damit ein Fehler nicht als falsche Probe
    gespeichert wird."""

    def __init__(self):
        self.sperre = threading.Lock()

    @staticmethod
    def datei(kennung):
        import hashlib

        kennzeichen = hashlib.sha256(f"{kennung}|{probe_text(kennung)}".encode()).hexdigest()[:16]
        return PROBEN / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', kennung)}_{kennzeichen}.wav"

    def hole(self, kennung):
        """WAV-Bytes der Probe. Wirft RuntimeError mit lesbarer Meldung bei Fehlern."""
        pfad = self.datei(kennung)
        if pfad.exists():
            return pfad.read_bytes()
        with self.sperre:  # nicht dieselbe Probe zweimal gleichzeitig bezahlen
            if pfad.exists():
                return pfad.read_bytes()
            import io
            import wave

            import stimmen

            try:
                stimme = stimmen.baue_einzelstimme(kennung)
                daten, rate = stimme.synthetisiere(probe_text(kennung))
            except Exception as fehler:
                kurz = str(fehler).splitlines()[0].rstrip(" {")[:120]  # fürs Handy lesbar halten
                raise RuntimeError(f"Hörprobe nicht möglich: {kurz}") from None
            puffer = io.BytesIO()
            with wave.open(puffer, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(rate)
                wf.writeframes(daten.tobytes())
            PROBEN.mkdir(parents=True, exist_ok=True)
            pfad.write_bytes(puffer.getvalue())
            self._protokolliere(stimme)
            return puffer.getvalue()

    @staticmethod
    def _protokolliere(stimme):
        """Zeichen der Cloud-Stimme wie im Gespräch als dienst=tts ins Kostenprotokoll schreiben."""
        gruppe = getattr(stimme, "preisgruppe", None)
        if not gruppe:
            return
        import stimmen

        bisher = 0
        monat = time.strftime("%Y-%m")
        for z in lies_csv(KOSTEN):
            if z.get("dienst") == "tts" and z.get("status") == gruppe and (z.get("zeitpunkt") or "").startswith(monat):
                bisher += int(zahl(z.get("zeichen")) or 0)
        zeichen = len(probe_text(stimme.kennung))
        kosten = stimmen.kosten_usd(gruppe, stimmen.berechnete_zeichen(gruppe, zeichen, bisher))
        try:
            with open(KOSTEN, newline="", encoding="utf-8-sig") as f:
                spalten = next(csv.reader(f, delimiter=";"))
        except (OSError, StopIteration):
            return  # ohne Protokoll (gespraech.py noch nie gestartet) nichts zu schreiben
        werte = {"zeitpunkt": time.strftime("%Y-%m-%d %H:%M:%S"), "sitzung": "oberflaeche", "dienst": "tts",
                 "modell": stimme.kennung, "kosten_usd": f"{kosten:.8f}".rstrip("0").rstrip(".").replace(".", ","),
                 "status": gruppe, "zeichen": zeichen}
        try:
            with open(KOSTEN, "a", newline="", encoding="utf-8") as f:
                csv.writer(f, delimiter=";").writerow(werte.get(s, "") for s in spalten)
        except OSError as fehler:
            print(f"[Hörprobe] Protokoll nicht geschrieben: {fehler}")


def lies_status():
    try:
        status = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"laeuft": False, "zustand": "aus"}
    status["laeuft"] = status.get("zustand") != "aus" and time.time() - status.get("aktualisiert", 0) < LEBENSZEICHEN_S
    return status


# ------------------------------------------------------------------ Zugang
class Zugang:
    def __init__(self, pin):
        self.pin = pin           # leer = ohne PIN, jeder im Heimnetz hat Zugang
        self.sitzungen = {}      # Token -> gültig bis
        self.fehlversuche = {}   # Adresse -> (Anzahl, gesperrt bis)
        self.sperre = threading.Lock()

    def anmelden(self, adresse, pin):
        """Gibt (Token, None) oder (None, Fehlermeldung) zurück."""
        with self.sperre:
            anzahl, gesperrt_bis = self.fehlversuche.get(adresse, (0, 0))
            if time.time() < gesperrt_bis:
                return None, f"Zu viele Versuche. Bitte in {int(gesperrt_bis - time.time()) // 60 + 1} Minuten erneut."
            if hmac.compare_digest(str(pin).encode(), self.pin.encode()):
                self.fehlversuche.pop(adresse, None)
                token = secrets.token_urlsafe(32)
                self.sitzungen[token] = time.time() + SITZUNG_GUELTIG_S
                return token, None
            anzahl += 1
            self.fehlversuche[adresse] = (0, time.time() + SPERRE_S) if anzahl >= MAX_FEHLVERSUCHE else (anzahl, 0)
            return None, "PIN falsch."

    def gueltig(self, token):
        if not self.pin:
            return True
        with self.sperre:
            bis = self.sitzungen.get(token or "")
            if bis and bis > time.time():
                return True
            self.sitzungen.pop(token or "", None)
            return False

    def abmelden(self, token):
        with self.sperre:
            self.sitzungen.pop(token or "", None)


# ------------------------------------------------------------------ Webserver
class Anfrage(BaseHTTPRequestHandler):
    zugang = None
    stimmen = None
    proben = None
    einstellungen_pfad = None
    server_version = "Pixel"
    sys_version = ""

    def log_message(self, format, *args):  # keine Zugriffsprotokolle im Terminal
        pass

    def _token(self):
        keks = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return keks["pidog"].value if "pidog" in keks else None

    def _antworte(self, code, daten=None, art="application/json; charset=utf-8", kopf=None):
        inhalt = daten if isinstance(daten, bytes) else json.dumps(daten, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", art)
        self.send_header("Content-Length", str(len(inhalt)))
        if "Cache-Control" not in (kopf or {}):
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
        for name, wert in (kopf or {}).items():
            self.send_header(name, wert)
        self.end_headers()
        self.wfile.write(inhalt)

    def _json_lesen(self):
        laenge = int(self.headers.get("Content-Length") or 0)
        if laenge > 100_000:
            raise ValueError("zu groß")
        return json.loads(self.rfile.read(laenge) or b"{}")

    def do_GET(self):
        if self.path == "/":
            return self._antworte(200, HTML.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/zustand":
            if not self.zugang.gueltig(self._token()):
                return self._antworte(401, {"fehler": "Bitte anmelden"})
            return self._antworte(200, self._zustand())
        if self.path.startswith("/api/lernstand"):
            if not self.zugang.gueltig(self._token()):
                return self._antworte(401, {"fehler": "Bitte anmelden"})
            from urllib.parse import parse_qs, urlparse

            kid = (parse_qs(urlparse(self.path).query).get("kind") or [""])[0]
            kartei = self._kartei(kid)
            if not kartei:
                return self._antworte(404, {"fehler": "Dieses Kind gibt es nicht (mehr)."})
            return self._antworte(200, kartei.uebersicht())
        if self.path.startswith("/api/themen"):
            if not self.zugang.gueltig(self._token()):
                return self._antworte(401, {"fehler": "Bitte anmelden"})
            from urllib.parse import parse_qs, urlparse

            q = parse_qs(urlparse(self.path).query)
            stand = self._themenstand((q.get("kind") or [""])[0], (q.get("fach") or [""])[0])
            if not stand:
                return self._antworte(404, {"fehler": "Kind oder Fach gibt es nicht."})
            return self._antworte(200, self._mit_einmaleins(stand, (q.get("kind") or [""])[0]))
        if self.path.startswith("/api/sticker"):
            if not self.zugang.gueltig(self._token()):
                return self._antworte(401, {"fehler": "Bitte anmelden"})
            from urllib.parse import parse_qs, urlparse

            kid = (parse_qs(urlparse(self.path).query).get("kind") or [""])[0]
            if not self._kinder().hole(kid):
                return self._antworte(404, {"fehler": "Dieses Kind gibt es nicht (mehr)."})
            album = sticker_mod.Album(kid, Path(self.einstellungen_pfad).parent / "sticker")
            return self._antworte(200, album.uebersicht())
        if self.path == "/api/wochenbericht":
            if not self.zugang.gueltig(self._token()):
                return self._antworte(401, {"fehler": "Bitte anmelden"})
            return self._antworte(200, self._wochenbericht())
        if self.path.startswith("/api/auswertung"):
            if not self.zugang.gueltig(self._token()):
                return self._antworte(401, {"fehler": "Bitte anmelden"})
            tage = self.path.partition("tage=")[2]
            tage = int(tage) if tage.isdigit() and 1 <= int(tage) <= 90 else 14
            return self._antworte(200, auswertung(tage))
        if self.path.startswith("/api/probe"):
            # GET, damit das Handy die Probe direkt als <audio src> abspielen kann (auch auf dem iPhone)
            if not self.zugang.gueltig(self._token()):
                return self._antworte(401, {"fehler": "Bitte anmelden"})
            from urllib.parse import parse_qs, urlparse

            kennung = (parse_qs(urlparse(self.path).query).get("stimme") or [""])[0]
            try:
                pers.FELDER["stimme"][1](kennung)
            except ValueError:
                return self._antworte(400, {"fehler": "Ungültige Stimme"})
            try:
                wav = self.proben.hole(kennung)
            except RuntimeError as fehler:
                print(f"[Hörprobe] {kennung}: {fehler}")
                return self._antworte(502, {"fehler": str(fehler)})
            return self._antworte(200, wav, "audio/wav", kopf={"Cache-Control": "private, max-age=86400"})
        self._antworte(404, {"fehler": "Nicht gefunden"})

    def do_POST(self):
        try:
            daten = self._json_lesen()
        except ValueError:
            return self._antworte(400, {"fehler": "Ungültige Anfrage"})
        if self.path == "/api/anmelden":
            token, fehler = self.zugang.anmelden(self.client_address[0], daten.get("pin", ""))
            if not token:
                return self._antworte(403, {"fehler": fehler})
            keks = f"pidog={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SITZUNG_GUELTIG_S}"
            return self._antworte(200, {"ok": True}, kopf={"Set-Cookie": keks})
        if not self.zugang.gueltig(self._token()):
            return self._antworte(401, {"fehler": "Bitte anmelden"})
        if self.path == "/api/abmelden":
            self.zugang.abmelden(self._token())
            return self._antworte(200, {"ok": True}, kopf={"Set-Cookie": "pidog=; Path=/; Max-Age=0"})
        if self.path == "/api/einstellungen":
            return self._speichere(daten)
        if self.path == "/api/kind":
            return self._kind(daten)
        if self.path == "/api/lernstand":
            return self._lernstand(daten)
        if self.path == "/api/themen":
            return self._themen(daten)
        if self.path == "/api/persoenlichkeit":
            return self._persoenlichkeit(daten)
        self._antworte(404, {"fehler": "Nicht gefunden"})

    def _kartei(self, kid):
        k = self._kinder().hole(kid) if kid else None
        if not k:
            return None
        return lernkartei.Lernkartei(kid, k["klasse"], lernkartei.Lernplan(),
                                     Path(self.einstellungen_pfad).parent / "lernstand")

    def _lernstand(self, daten):
        """Eingriff der Eltern: aktion "stufe" (stufe) oder "zuruecksetzen" (kennung, Karte wird wieder neu)."""
        if not isinstance(daten, dict):
            return self._antworte(400, {"fehler": "Ungültige Anfrage"})
        kartei = self._kartei(daten.get("kind"))
        if not kartei:
            return self._antworte(404, {"fehler": "Dieses Kind gibt es nicht (mehr)."})
        if daten.get("aktion") == "stufe":
            stufe = daten.get("stufe")
            if not isinstance(stufe, int) or isinstance(stufe, bool) or not 1 <= stufe <= kartei.plan.hoechste:
                return self._antworte(422, {"fehler": f"Stufe 1 bis {kartei.plan.hoechste}"})
            kartei.stufe = stufe
        elif daten.get("aktion") == "thema":
            if daten.get("thema") not in ("", *kartei.themen()):
                return self._antworte(422, {"fehler": "Dieses Thema gibt es nicht."})
            kartei.thema = daten["thema"]
        elif daten.get("aktion") == "niveau":
            if daten.get("niveau") not in lernkartei.NIVEAUS:
                return self._antworte(422, {"fehler": "Schwierigkeit leicht, mittel oder schwer"})
            kartei.niveau = daten["niveau"]
        elif daten.get("aktion") == "zuruecksetzen":
            if daten.get("kennung") not in kartei.karten:
                return self._antworte(404, {"fehler": "Diese Karte gibt es nicht."})
            del kartei.karten[daten["kennung"]]
        else:
            return self._antworte(400, {"fehler": "Ungültige Anfrage"})
        kartei.speichere()
        print(f"[Lernstand] {daten.get('kind')}: {daten['aktion']}")
        return self._antworte(200, kartei.uebersicht())

    def _wochenbericht(self):
        """Letzte 7 Tage je Kind (ohne Erwachsene), mit der Vorwoche zum Vergleich."""
        basis = Path(self.einstellungen_pfad).parent
        grenze = time.strftime("%Y-%m-%d", time.localtime(time.time() - 6 * 86400))
        kinder = []
        for kid, k in self._kinder().daten.items():
            if kinder_mod.ist_erwachsen(k):
                continue
            buch = tagebuch_mod.Tagebuch(kid, basis / "lernstand")
            album = sticker_mod.Album(kid, basis / "sticker")
            kinder.append({"id": kid, "name": k["name"], "woche": buch.woche(), "vorwoche": buch.woche(versatz=7),
                           "sticker": sum(1 for s in album.sticker if s.get("datum", "") >= grenze)})
        return {"kinder": kinder}

    def _themenstand(self, kid, fach):
        k = self._kinder().hole(kid) if kid else None
        if not k or fach not in lernthemen.FAECHER:
            return None
        return lernthemen.Lernstand(kid, k["klasse"], fach, Path(self.einstellungen_pfad).parent / "lernstand")

    def _themen(self, daten):
        """Eltern: aktion "stufe" (stufe), "aktuell" (thema, "" = automatisch) oder "zuruecksetzen" (thema)."""
        if not isinstance(daten, dict):
            return self._antworte(400, {"fehler": "Ungültige Anfrage"})
        stand = self._themenstand(daten.get("kind"), daten.get("fach"))
        if not stand:
            return self._antworte(404, {"fehler": "Kind oder Fach gibt es nicht."})
        aktion, thema = daten.get("aktion"), daten.get("thema", "")
        if aktion == "niveau":
            if daten.get("niveau") not in lernthemen.NIVEAUS:
                return self._antworte(422, {"fehler": "Schwierigkeit leicht, mittel oder schwer"})
            stand.niveau = daten["niveau"]
        elif aktion == "stufe":
            if not any(s["stufe"] == daten.get("stufe") for s in stand.plan.stufen):
                return self._antworte(422, {"fehler": "Diese Stufe gibt es nicht."})
            stand.stufe, stand.aktuell_gewaehlt = daten["stufe"], ""
        elif aktion == "aktuell":
            if thema and thema not in stand.plan.themen:
                return self._antworte(404, {"fehler": "Dieses Thema gibt es nicht."})
            stand.aktuell_gewaehlt = thema  # leer = das Kind sucht sich selbst eins aus
        elif aktion == "zuruecksetzen":
            if thema not in stand.plan.themen:
                return self._antworte(404, {"fehler": "Dieses Thema gibt es nicht."})
            stand.themen.pop(thema, None)
        else:
            return self._antworte(400, {"fehler": "Ungültige Anfrage"})
        stand.speichere()
        print(f"[Lernplan] {daten.get('kind')} {daten.get('fach')}: {aktion} {thema or daten.get('stufe', '')}")
        return self._antworte(200, self._mit_einmaleins(stand, daten.get("kind")))

    def _mit_einmaleins(self, stand, kid):
        """Übersicht eines Fachs, bei Mathe mit dem Einmaleins-Karteikasten."""
        u = stand.uebersicht()
        if stand.fach == "mathe":
            u["einmaleins"] = einmaleins.Kartei(kid, Path(self.einstellungen_pfad).parent / "lernstand").uebersicht()
        return u

    def _kinder(self):
        return kinder_mod.Kinder(Path(self.einstellungen_pfad).parent / "kinder.json")

    def _kind(self, daten):
        """aktion "neu" (name, klasse), "speichern" (id, werte) oder "loeschen" (id). Namen bleiben auf dem Rechner."""
        if not isinstance(daten, dict):
            return self._antworte(400, {"fehler": "Ungültige Anfrage"})
        ki, aktion, kid = self._kinder(), daten.get("aktion"), daten.get("id")
        if aktion == "neu":
            try:
                neu = ki.neu(daten.get("name", ""), daten.get("klasse", 4))
            except ValueError as f:
                return self._antworte(422, {"fehler": str(f)})
            print(f"[Kinder] neu: {neu}")
            return self._antworte(200, {"id": neu})
        if not ki.hole(kid):
            return self._antworte(404, {"fehler": "Dieses Kind gibt es nicht (mehr)."})
        if aktion == "loeschen":
            ki.loesche(kid)
            es = Einstellungen(self.einstellungen_pfad)
            if es["kind"] == kid:  # gespraech.py merkt es ebenfalls
                es.werte["kind"] = ""
                es.speichere()
            print(f"[Kinder] gelöscht: {kid}")
            return self._antworte(200, {"ok": True})
        if aktion != "speichern" or not isinstance(daten.get("werte"), dict):
            return self._antworte(400, {"fehler": "Ungültige Anfrage"})
        k, fehler, gespeichert = ki.hole(kid), {}, []
        for name, wert in daten["werte"].items():
            if name not in kinder_mod.FELDER:
                fehler[name] = "unbekanntes Feld"
                continue
            try:
                neu = kinder_mod.FELDER[name][1](wert)
            except ValueError as f:
                fehler[name] = str(f)
                continue
            if name == "name" and ki.finde(neu) not in (None, kid):
                fehler[name] = "Diesen Namen gibt es schon."
                continue
            if neu != k[name]:
                k[name] = neu
                gespeichert.append(name)
        if gespeichert:
            ki.speichere()
            print(f"[Kinder] {kid} geändert: {', '.join(gespeichert)}")
        self._antworte(200 if not fehler else 422, {"gespeichert": gespeichert, "fehler": fehler})

    def _laden(self):
        """Einstellungen und Persönlichkeiten. Beim allerersten Start (vor gespraech.py) wird hier wie
        dort umgezogen: alte Einzelwerte aus einstellungen.json in die Persönlichkeit Pixel."""
        es = Einstellungen(self.einstellungen_pfad)
        pk = pers.Persoenlichkeiten(Path(self.einstellungen_pfad).parent / "persoenlichkeiten.json",
                                    umzug=es.umgezogen)
        es.entferne_umgezogene()
        aktiv = es["persoenlichkeit"] if pk.hole(es["persoenlichkeit"]) else pers.STANDARD
        return es, pk, aktiv

    def _zustand(self):
        es, pk, aktiv = self._laden()
        status = lies_status()
        verzoegerung = verzoegerung_je_stimme()
        stimmen = []
        genutzt = [x[f] for x in pk.daten.values() for f in ("stimme", "stimme_geschichte", "stimme_englisch")]
        for s in self.stimmen.alle([*genutzt, status.get("stimme")]):
            s = dict(s, kosten=kosten_text(s["gruppe"]), **verzoegerung.get(s["kennung"], {}))
            stimmen.append(s)
        eigene = sorted(p.stem for p in (BASIS / "wakewords").glob("*.onnx"))
        wakewords = [{"kennung": k, "name": " ".join(t.capitalize() for t in k.split("_"))}
                     for k in dict.fromkeys(eigene + ["hey_mycroft", es["wakeword"]])]
        return {"status": status, "einstellungen": dict(es.werte, persoenlichkeit=aktiv), "tag": tageswerte(), "modelle": MODELLE,
                "persoenlichkeiten": pk.daten, "aktiv": aktiv,
                "kinder": self._kinder().daten,
                "wakewords": wakewords,
                "standard_prompts": {"system_prompt": prompts.SYSTEM_PROMPT,
                                     "geschichten_prompt": prompts.GESCHICHTEN_PROMPT},
                "pin_aktiv": bool(self.zugang.pin),
                "stimmen": stimmen}

    def _speichere(self, daten):
        if not isinstance(daten, dict):
            return self._antworte(400, {"fehler": "Ungültige Anfrage"})
        es, pk, _ = self._laden()
        fehler, gespeichert = {}, []
        for name, wert in daten.items():
            if name not in FELDER or name in pers.UMZUG:
                fehler[name] = "unbekannte Einstellung"
                continue
            if name == "kind" and wert and not self._kinder().hole(wert):
                fehler[name] = "unbekanntes Kind"
                continue
            if name == "persoenlichkeit" and not pk.hole(wert):
                fehler[name] = "unbekannte Persönlichkeit"
                continue
            try:
                neu = FELDER[name][1](wert)
            except ValueError as f:
                fehler[name] = str(f)
                continue
            if neu != es.werte[name]:
                es.werte[name] = neu
                gespeichert.append(name)
        if gespeichert:
            es.speichere()
            print(f"[Einstellungen] geändert: {', '.join(gespeichert)}")
        self._antworte(200 if not fehler else 422, {"gespeichert": gespeichert, "fehler": fehler})

    def _persoenlichkeit(self, daten):
        """aktion "speichern" (id, werte), "neu" (vorlage, name) oder "loeschen" (id)."""
        if not isinstance(daten, dict):
            return self._antworte(400, {"fehler": "Ungültige Anfrage"})
        es, pk, aktiv = self._laden()
        aktion, pid = daten.get("aktion"), daten.get("id")
        def vergeben(name, ausser=None):  # sonst wäre der Sprachbefehl mehrdeutig
            return any(pers.normalisiere(x["name"]) == pers.normalisiere(str(name))
                       for k, x in pk.daten.items() if k != ausser)

        if aktion == "neu":
            if vergeben(daten.get("name", "")):
                return self._antworte(422, {"fehler": "Diesen Namen gibt es schon."})
            try:
                neu = pk.neu(daten.get("vorlage") or aktiv, daten.get("name", ""))
            except ValueError as f:
                return self._antworte(422, {"fehler": f"Name: {f}"})
            print(f"[Persönlichkeiten] neu: {neu}")
            return self._antworte(200, {"id": neu})
        if not pk.hole(pid):
            return self._antworte(404, {"fehler": "Diese Persönlichkeit gibt es nicht (mehr)."})
        if aktion == "loeschen":
            try:
                pk.loesche(pid)
            except ValueError as f:
                return self._antworte(422, {"fehler": str(f)})
            if pid == aktiv:  # gespraech.py wechselt dann ebenfalls zu Pixel
                es.werte["persoenlichkeit"] = pers.STANDARD
                es.speichere()
            print(f"[Persönlichkeiten] gelöscht: {pid}")
            return self._antworte(200, {"ok": True})
        if aktion != "speichern" or not isinstance(daten.get("werte"), dict):
            return self._antworte(400, {"fehler": "Ungültige Anfrage"})
        p, fehler, gespeichert = pk.hole(pid), {}, []
        standard = {"system_prompt": prompts.SYSTEM_PROMPT, "geschichten_prompt": prompts.GESCHICHTEN_PROMPT}
        for name, wert in daten["werte"].items():
            if name not in pers.FELDER:
                fehler[name] = "unbekanntes Feld"
                continue
            if name in ("modell", "modell_geschichte") and wert not in {m["kennung"] for m in MODELLE}:
                fehler[name] = "nur Haiku oder Sonnet"
                continue
            if name == "name" and vergeben(wert, ausser=pid):
                fehler[name] = "Diesen Namen gibt es schon."
                continue
            try:
                neu = pers.FELDER[name][1](wert)
            except ValueError as f:
                fehler[name] = str(f)
                continue
            if name in standard and neu == standard[name].strip():
                neu = ""  # unverändert = Standard, damit spätere Verbesserungen am Standard ankommen
            if neu != p[name]:
                p[name] = neu
                gespeichert.append(name)
        if gespeichert:
            pk.speichere()
            print(f"[Persönlichkeiten] {pid} geändert: {', '.join(gespeichert)}")
        self._antworte(200 if not fehler else 422, {"gespeichert": gespeichert, "fehler": fehler})


class Server(ThreadingHTTPServer):
    # Unter Windows erlaubt SO_REUSEADDR einen zweiten Server auf demselben Port, ohne Fehlermeldung.
    # Dort deshalb ausschalten, damit ein doppelter Start auffällt. Unter Linux ist es harmlos und
    # erlaubt einen schnellen Neustart.
    allow_reuse_address = os.name != "nt"


def eigene_adresse():
    """IP-Adresse im Heimnetz (ohne etwas zu senden)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description="Handy-Oberfläche für Pixel")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--nur-lokal", action="store_true", help="nur auf diesem Rechner erreichbar")
    ap.add_argument("--einstellungen", default=str(BASIS / "einstellungen.json"), metavar="DATEI")
    args = ap.parse_args()

    pin = lies_umgebung("PIDOG_ELTERN_PIN")
    if pin and len(pin) < 4:
        sys.exit("Die Eltern-PIN in PIDOG_ELTERN_PIN ist kürzer als 4 Zeichen. Bitte länger wählen oder löschen.")
    if not pin:
        if os.name == "nt":
            setzen = ("einmalig in PowerShell mit:\n"
                      '  [Environment]::SetEnvironmentVariable("PIDOG_ELTERN_PIN", (Read-Host "Eltern-PIN"), "User")')
        else:
            setzen = "als Umgebungsvariable PIDOG_ELTERN_PIN."
        print("Hinweis: Ohne Eltern-PIN kann jeder im Heimnetz Einstellungen ändern, auch Schlafenszeit und "
              f"Limits. Eine PIN setzt man {setzen}")

    Anfrage.zugang = Zugang(pin)
    Anfrage.stimmen = Stimmenliste()
    Anfrage.einstellungen_pfad = args.einstellungen
    Anfrage.proben = Hoerproben()
    host = "127.0.0.1" if args.nur_lokal else "0.0.0.0"
    try:
        server = Server((host, args.port), Anfrage)
    except OSError:
        print(f"Port {args.port} ist schon belegt. Läuft die Oberfläche bereits? Sonst mit --port einen "
              "anderen wählen.", file=sys.stderr)
        sys.exit(3)  # wie gespraech.LAEUFT_SCHON: starte.py startet dann nicht neu
    adresse = "localhost" if args.nur_lokal else eigene_adresse()
    print(f"Oberfläche läuft: http://{adresse}:{args.port}  (Strg+C beendet)")
    if not args.nur_lokal:
        print(f"Auf dem Handy im selben WLAN öffnen. Auf diesem Rechner auch: http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nOberfläche beendet.")


if __name__ == "__main__":
    main()
