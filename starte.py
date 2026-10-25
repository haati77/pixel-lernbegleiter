"""
Startet Pixel: Gesprächsprogramm und Handy-Oberfläche mit einem Befehl.

    python starte.py                       # beides, Oberfläche im Heimnetz
    python starte.py --nur-lokal           # Oberfläche nur auf diesem Rechner
    python starte.py --ohne-oberflaeche    # nur das Gespräch
    python starte.py -- --modus taste      # alles nach "--" geht an gespraech.py

Beide Ausgaben erscheinen in diesem Fenster, mit [Gespräch] bzw. [Oberfläche] davor.
Strg+C beendet beides. Stürzt ein Programm ab, wird es nach 5 s neu gestartet, bei mehr als
5 Abstürzen in 10 Minuten wird aufgegeben (dann stimmt grundsätzlich etwas nicht).
Endet das Gesprächsprogramm normal (z. B. 'q' im Modus taste), wird alles beendet.
"""
import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

BASIS = Path(__file__).parent
NEUSTART_NACH_S = 5
MAX_ABSTUERZE = 5
ABSTURZ_FENSTER_S = 600
BEENDEN_WARTEN_S = 8
LAEUFT_SCHON = 3  # Rückgabewert der Programme, wenn schon eine Instanz läuft  # so lange dürfen die Programme nach Strg+C aufräumen


class Programm:
    """Ein überwachtes Python-Programm, dessen Ausgabe mit einem Namen davor weitergegeben wird."""

    def __init__(self, name, argumente, eingabe=False):
        self.name = name
        self.argumente = argumente
        self.eingabe = eingabe  # bekommt die Tastatur (Modus taste)
        self.prozess = None
        self.abstuerze = []

    def starte(self):
        umgebung = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        self.prozess = subprocess.Popen(
            [sys.executable, "-u", *self.argumente], cwd=BASIS, env=umgebung,
            stdin=None if self.eingabe else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
        )
        threading.Thread(target=self._weitergeben, args=(self.prozess,), daemon=True).start()

    def _weitergeben(self, prozess):
        for zeile in prozess.stdout:
            if "Missing phoneme from id map" in zeile:  # harmlose Piper-Meldung
                continue
            print(f"[{self.name}] {zeile}", end="", flush=True)

    def laeuft(self):
        return self.prozess is not None and self.prozess.poll() is None

    def darf_neu_starten(self):
        jetzt = time.time()
        self.abstuerze = [t for t in self.abstuerze if jetzt - t < ABSTURZ_FENSTER_S] + [jetzt]
        return len(self.abstuerze) <= MAX_ABSTUERZE

    def beende(self):
        if not self.laeuft():
            return
        if os.name != "nt":
            # Unter Linux (Pi) bekommen die Programme Strg+C nicht automatisch mit, z. B. wenn systemd
            # beendet. SIGINT löst dort dasselbe saubere Beenden aus (Status "aus").
            self.prozess.send_signal(signal.SIGINT)
        try:
            self.prozess.wait(BEENDEN_WARTEN_S)  # nach Strg+C räumen die Programme selbst auf
        except subprocess.TimeoutExpired:
            self.prozess.terminate()
            try:
                self.prozess.wait(3)
            except subprocess.TimeoutExpired:
                self.prozess.kill()


def main():
    ap = argparse.ArgumentParser(description="Startet Gesprächsprogramm und Handy-Oberfläche")
    ap.add_argument("--nur-lokal", action="store_true", help="Oberfläche nur auf diesem Rechner erreichbar")
    ap.add_argument("--ohne-oberflaeche", action="store_true", help="nur das Gesprächsprogramm starten")
    ap.add_argument("--port", type=int, default=8080, help="Port der Oberfläche (Standard: 8080)")
    ap.add_argument("gespraech_optionen", nargs=argparse.REMAINDER,
                    help='Optionen für gespraech.py nach "--", z. B. -- --modus taste')
    args = ap.parse_args()
    optionen = [o for o in args.gespraech_optionen if o != "--"]

    programme = [Programm("Gespräch", ["gespraech.py", *optionen], eingabe="taste" in optionen)]
    if not args.ohne_oberflaeche:  # ohne Eltern-PIN läuft die Oberfläche offen im Heimnetz, mit Hinweis
        programme.append(Programm("Oberfläche", ["oberflaeche.py", "--port", str(args.port),
                                                 *(["--nur-lokal"] if args.nur_lokal else [])]))

    def bei_sigterm(*_):  # systemd auf dem Pi beendet mit SIGTERM: wie Strg+C behandeln
        raise KeyboardInterrupt

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, bei_sigterm)

    print(f"[Start] {' und '.join(p.name for p in programme)} werden gestartet. Strg+C beendet alles.")
    for p in programme:
        p.starte()

    gespraech = programme[0]
    try:
        while True:
            time.sleep(1)
            if gespraech.prozess.poll() == 0:
                print("[Start] Gesprächsprogramm beendet, alles wird beendet.")
                break
            for p in programme:
                code = p.prozess.poll()
                if code is None or (p is gespraech and code == 0):
                    continue
                if code == LAEUFT_SCHON:
                    print(f"[Start] {p.name} läuft schon in einem anderen Fenster, Start wird abgebrochen.")
                    raise SystemExit(1)
                if not p.darf_neu_starten():
                    print(f"[Start] {p.name}: mehr als {MAX_ABSTUERZE} Abstürze in {ABSTURZ_FENSTER_S // 60} Minuten, "
                          "gebe auf. Bitte die Meldungen oben prüfen.")
                    raise SystemExit(1)
                print(f"[Start] {p.name} unerwartet beendet (Code {code}), Neustart in {NEUSTART_NACH_S} s ...")
                time.sleep(NEUSTART_NACH_S)
                p.starte()
    except KeyboardInterrupt:
        print("\n[Start] Wird beendet ...")
    finally:
        for p in programme:
            p.beende()
        print("[Start] Alles beendet.")


if __name__ == "__main__":
    main()
