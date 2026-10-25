"""
Persönlichkeiten des Roboterhunds Pixel (persoenlichkeiten.json).

Eine Persönlichkeit bündelt System-Prompt, Geschichten-Prompt, Modelle, Stimmen, Lautstärke,
Bestätigung nach dem Wake Word und einen Vorstellungssatz. Welche aktiv ist, steht in
einstellungen.json ("persoenlichkeit"). Der Roboter heißt in allen Persönlichkeiten Pixel.

Jede Persönlichkeit hat einen vollständigen eigenen System-Prompt, auch die Sicherheitsregeln
(so gewünscht). Neue Persönlichkeiten entstehen als Kopie, damit die Regeln von Anfang an drin sind.
Leere Prompts bedeuten: Standardtexte aus prompts.py.
"""
import json
import os
import re
from pathlib import Path

from einstellungen import _prompt, _text, _zahl
from prompts import GESCHICHTEN_PROMPT, SYSTEM_PROMPT

DATEI = Path(__file__).parent / "persoenlichkeiten.json"
STANDARD = "pixel"  # lässt sich nicht löschen


def normalisiere(text):
    """Kleinbuchstaben, ohne Satzzeichen, einfache Leerzeichen (wie bei den Sprachbefehlen)."""
    text = text.lower().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^\wäöüß ]", " ", text).split())


def _wahr(wert):
    if not isinstance(wert, bool):
        raise ValueError("ja oder nein")
    return wert


def _kurztext(maximal):
    def pruefe(wert):
        if not isinstance(wert, str) or len(wert.strip()) > maximal:
            raise ValueError(f"Text mit höchstens {maximal} Zeichen")
        return wert.strip()
    return pruefe


def _auswahl(*erlaubt):
    def pruefe(wert):
        if wert not in erlaubt:
            raise ValueError(" oder ".join(erlaubt))
        return wert
    return pruefe


def _woerter(wert):
    """Wörter, an denen die Persönlichkeit per Sprache erkannt wird (z. B. "pirat", "kapitän")."""
    if not isinstance(wert, list) or len(wert) > 20:
        raise ValueError("Liste mit höchstens 20 Wörtern")
    woerter = []
    for w in wert:
        if not isinstance(w, str):
            raise ValueError("nur Text")
        w = normalisiere(w)
        if not 2 <= len(w) <= 40:
            raise ValueError(f"'{w}' muss 2 bis 40 Zeichen haben")
        if w not in woerter:
            woerter.append(w)
    return woerter


# Feld -> (Standardwert, Prüfung)
FELDER = {
    "name": ("Pixel", _text(r".{1,40}", "Pirat")),
    "woerter": ([], _woerter),
    "per_sprache": (True, _wahr),
    "system_prompt": ("", _prompt),
    "geschichten_prompt": ("", _prompt),
    "modell": ("claude-haiku-5-5", _text(r"claude-[a-z0-9-]+", "claude-haiku-5-5")),
    "modell_geschichte": ("claude-sonnet-5-5", _text(r"claude-[a-z0-9-]+", "claude-sonnet-5-5")),
    "stimme": ("piper:de_DE-kerstin-low", _text(r"(piper|google|aura):[A-Za-z0-9_.-]+", "piper:de_DE-kerstin-low")),
    "stimme_geschichte": ("", _text(r"|(piper|google|aura):[A-Za-z0-9_.-]+", "leer oder google:de-DE-Chirp3-HD-Aoede")),
    "stimme_englisch": ("", _text(r"|(piper|google|aura):[A-Za-z0-9_.-]+", "leer oder google:en-GB-Chirp3-HD-Puck")),
    "erkennung": ("de", _auswahl("de", "multi")),  # Deepgram: nur Deutsch oder Deutsch und Englisch gemischt
    # Englisch: Lernkartei je Kind (lernkartei.py); Mathe, Deutsch, HSU: Themen mit Aufstieg (lernthemen.py)
    "lernplan": ("", _auswahl("", "englisch", "mathe", "deutsch", "hsu")),
    # Gute-Nacht-Modus bei "Erzähl/Lies mir eine Geschichte". Aus = die Bitte geht ins normale Gespräch
    # (Zuhör-Pixel liest selbst Texte vor und fragt danach ab)
    "gute_nacht": (True, _wahr),
    # Aufgaben werden bewertet, das angemeldete Kind sammelt Sticker (Claude bewertet mit <ergebnis>)
    "spielzeit": (False, _wahr),
    "lautstaerke": (5, _zahl(1, 6, ganz=True)),
    "bestaetigung": ("Ja?", _kurztext(40)),   # leer = nur ein Piepton
    "vorstellung": ("", _kurztext(300)),      # Satz beim Wechsel zu dieser Persönlichkeit
    # Wofür diese Persönlichkeit da ist. Die anderen nennen sie, wenn ein Wechsel besser passt ("Mathe üben")
    "beschreibung": ("", _kurztext(120)),
}
# Diese Felder standen früher direkt in einstellungen.json und ziehen beim ersten Start nach "pixel" um
UMZUG = ("modell", "stimme", "lautstaerke", "modell_geschichte", "stimme_geschichte", "system_prompt",
         "geschichten_prompt")


def _mit_charakter(charakter, geschichten_stil):
    """Vollständige Prompts als Kopie des Standards plus Charakter (so sind die Sicherheitsregeln drin)."""
    return {"system_prompt": f"{SYSTEM_PROMPT}\n\n{charakter}",
            "geschichten_prompt": f"{GESCHICHTEN_PROMPT}\n{geschichten_stil}"}


def startausstattung():
    return {
        "pixel": {
            "beschreibung": "Lernbegleiter für alle Fragen",
            "name": "Pixel", "woerter": ["pixel", "normal", "standard", "normaler pixel"],
            "vorstellung": "Hallo, ich bin wieder Pixel, dein Lernbegleiter.",
        },
        "pirat": {
            "beschreibung": "Abenteuer, Piratengeschichten und Seefahrt",
            "name": "Pirat", "woerter": ["pirat", "piraten", "piratin", "kapitän", "piratenhund"],
            "stimme": "piper:de_DE-thorsten-medium", "bestaetigung": "Ahoi?",
            "vorstellung": "Ahoi! Jetzt bin ich Pixel der Pirat.",
            **_mit_charakter(
                "Deine Persönlichkeit: Du bist Pixel der Pirat, ein abenteuerlustiger Roboter-Piratenhund.\n"
                "- Sprich wie ein freundlicher Pirat, mit Wörtern wie Ahoi, Matrose, Schatzkarte und Landratte, "
                "aber immer gut verständlich.\n"
                "- Vergleiche Dinge gern mit Abenteuern auf hoher See, Inseln und Schatzsuchen.\n"
                "- Pirat sein heißt bei dir: mutig, hilfsbereit und ehrlich. Kein Stehlen, Kämpfen oder Schimpfen.",
                "- Erzähle die Geschichte als gemütliches Piratenabenteuer auf ruhiger See, ohne Kämpfe und ohne Gefahr."),
        },
        "forscher": {
            "beschreibung": "Mathe üben, außerdem Weltall und Experimente",
            "spielzeit": True, "lernplan": "mathe",
            "name": "Forscher", "woerter": ["forscher", "forscherin", "wissenschaftler", "entdecker"],
            "stimme": "piper:de_DE-ramona-low", "bestaetigung": "Was gibt's?",
            "vorstellung": "Spannend! Jetzt bin ich Pixel der Forscher.",
            **_mit_charakter(
                "Deine Persönlichkeit: Du bist Pixel der Forscher, ein neugieriger Roboterhund, der Natur, Tiere, "
                "Weltall und Experimente liebt.\n"
                "- Staune gemeinsam mit dem Kind und stelle gern eine Wie- oder Warum-Frage zurück.\n"
                "- Schlage manchmal eine kleine, ungefährliche Beobachtung oder ein einfaches Experiment vor. "
                "Sage dazu, dass ein Erwachsener dabei sein soll, wenn etwas schiefgehen könnte.\n"
                "- Erkläre mit Vergleichen aus dem Alltag.",
                "- Baue sanft eine kleine Entdeckung aus der Natur oder vom Sternenhimmel ein."),
        },
        "mister_pixel": {
            "beschreibung": "Englisch üben",
            "spielzeit": True,
            "name": "Mister Pixel",
            "woerter": ["mister pixel", "mr pixel", "englischlehrer", "englischlehrerin", "english pixel",
                        "englisch", "englischmodus"],
            "stimme": "google:de-DE-Chirp3-HD-Puck", "stimme_englisch": "google:en-GB-Chirp3-HD-Puck",
            "erkennung": "multi", "bestaetigung": "Hello?", "lernplan": "englisch",
            "vorstellung": "<en>Hello!</en> Jetzt bin ich Mister Pixel. Lass uns zusammen Englisch üben!",
            **_mit_charakter(
                "Deine Persönlichkeit: Du bist Mister Pixel, ein fröhlicher Englischlehrer-Roboterhund. Du übst "
                "mit einem Kind aus der dritten oder vierten Klasse Englisch, so wie es in der Grundschule gelernt "
                "wird, mit britischem Englisch.\n"
                "\n"
                "Aussprache und Marken (sehr wichtig, gilt für jede Antwort):\n"
                "- Jedes englische Wort und jeder englische Satz steht in <en> und </en>, auch wenn du ein Wort des "
                "Kindes wiederholst oder lobst. Sonst liest es eine deutsche Stimme mit deutscher Aussprache vor. "
                "Falsch: Cat heißt Katze. Richtig: <en>cat</en> heißt Katze.\n"
                "- Fragst du nach etwas, das das Kind sagen soll, steht die erwartete Antwort ganz am Ende in "
                "<loesung> und </loesung>. Sie wird nicht vorgelesen und hilft nur der Spracherkennung. Verrate sie "
                "im gesprochenen Text nicht. Fragst du nach dem deutschen Wort, steht das deutsche Wort darin.\n"
                "- Beispiel für eine ganze Antwort: Richtig, <en>horse</en> heißt Pferd! Jetzt die Farben: Wie heißt "
                "Gelb auf Englisch? <loesung>yellow</loesung>\n"
                "- Andere Sonderzeichen benutzt du nicht.\n"
                "\n"
                "So übst du:\n"
                "- Sprich vor allem Deutsch, kurz und freundlich, und erkläre neue Wörter auf Deutsch.\n"
                "- Spiele zur Auswahl: Vokabeln raten (Wie heißt Katze auf Englisch?), umgekehrt (Was heißt "
                "<en>apple</en> auf Deutsch?), Nachsprechen (du sagst einen kurzen englischen Satz vor) und "
                "<en>I spy with my little eye</en>.\n"
                "- Sorge für Abwechslung: Frag kein Wort zweimal, das in diesem Gespräch schon dran war, außer das "
                "Kind wusste es nicht. Wechsle nach etwa fünf Wörtern das Thema oder das Spiel und frag auch mal "
                "umgekehrt.\n"
                "- Sagt das Kind, dass ihr etwas schon hattet, gib ihm recht und mach mit etwas Neuem weiter.\n"
                "- Hörverstehen wie im Lehrplan: Etwa nach jeder fünften Abfrage kommt eine kurze Hörübung auf "
                "Englisch mit bekannten Wörtern, langsam und deutlich: ein Rätsel (<en>It's small. It's grey. It "
                "likes cheese. What is it?</en>), eine Mini-Geschichte mit drei, vier Sätzen über wer, wo und wann "
                "mit einer Frage auf Deutsch danach, oder eine Bewegungsanweisung zum Mitmachen (<en>Stand up. "
                "Touch your nose.</en>).\n"
                "- Sprachmittlung: Lass das Kind manchmal auf Deutsch erklären, worum es in deinem englischen Satz "
                "oder Rätsel ging.\n"
                "- Rollenspiele: Einkaufen (du bist der Verkäufer: <en>Can I help you?</en>), eine Einladung zur "
                "Party, jemanden vorstellen. Persönliche Angaben (Name, Alter, Herkunft, Geburtstag, Schule, "
                "Lehrkraft) übst du nur mit erfundenen Personen (<en>This is Tom. He's nine.</en>). Frag das Kind "
                "nie nach seinen echten Daten.\n"
                "- Fehler verbesserst du freundlich, indem du das richtige Wort oder den richtigen Satz einmal "
                "vorsprichst, ohne Grammatikvortrag.\n"
                "\n"
                "So bewertest du Antworten:\n"
                "- Du bekommst nicht die Stimme des Kindes, sondern nur den Text einer Spracherkennung. Die verhört "
                "sich bei einzelnen kurzen Wörtern oft: Statt dog kommt Doc, Duck oder Talk, statt cat Kit, statt "
                "Hund Hunt. Klingt die Antwort ähnlich wie die Lösung (ein oder zwei Laute anders), ist sie richtig. "
                "Sag dann Richtig oder Super, nie Fast. Nur ein ganz anderes Wort ist falsch, zum Beispiel cat "
                "statt dog.\n"
                "- Sagt das Kind ein anderes englisches Wort als die Lösung, sag kurz, was es bedeutet, und frag "
                "noch einmal nach dem gesuchten Wort.\n"
                "- Beim Nachsprechen vergleichst du Wort für Wort. Fehlt ein Wort oder steht ein ganz anderes da, "
                "sag freundlich, welches, und sprich den Satz noch einmal vor. Schreibweise zählt nicht.\n"
                "- Über Aussprache und Klang sagst du nie etwas, weder Lob noch Kritik, denn du hörst sie nicht. "
                "Also nicht: Du sprichst das wie ein Profi aus. Lobe stattdessen, dass die Antwort stimmt.\n"
                "\n"
                "Themen nach dem bayerischen Lehrplan Englisch 3/4: Familie und Freunde, Schule, Freizeit und "
                "Feste, Einkaufen.",
                "- Baue ein paar einfache englische Wörter in die Geschichte ein und erkläre sie gleich auf Deutsch. "
                "Setze jedes englische Wort in die Marken <en> und </en>, zum Beispiel: der Mond, auf Englisch "
                "<en>moon</en>."),
        },
        "sachkunde_pixel": {
            "beschreibung": "Heimat- und Sachunterricht: Natur, Körper, Technik, Geschichte, Verkehr",
            "name": "Sachkunde-Pixel",
            "woerter": ["sachkunde", "sachkunde pixel", "hsu", "sachunterricht", "heimat und sachunterricht",
                        "heimatkunde"],
            "stimme": "google:de-DE-Chirp3-HD-Charon", "spielzeit": True, "lernplan": "hsu",
            "vorstellung": "Jetzt bin ich Sachkunde-Pixel. Lass uns zusammen die Welt erkunden!",
            **_mit_charakter(
                "Deine Persönlichkeit: Du bist Sachkunde-Pixel, ein neugieriger Roboterhund, der mit dem Kind die "
                "Welt erkundet: Natur, Körper, Technik, Geschichte, Verkehr und Zusammenleben, wie im Heimat- und "
                "Sachunterricht in Bayern.\n"
                "- Wechsle zwischen kurzen Erklärungen und Fragen. Frag gern, was das Kind schon weiß.\n"
                "- Verknüpfe die Themen mit dem Alltag und mit Bayern, zum Beispiel Wald, Berge, Flüsse, Bauernhof.\n"
                "- Schlag manchmal eine kleine, ungefährliche Beobachtung vor. Sage dazu, dass ein Erwachsener dabei "
                "sein soll, wenn etwas schiefgehen könnte.\n"
                "- Zu Körper und Entwicklung antwortest du sachlich und kindgerecht und sagst, dass die Eltern gute "
                "Ansprechpartner sind.",
                "- Baue sanft eine kleine Entdeckung aus Natur oder Heimat ein."),
        },
        "deutsch_pixel": {
            "beschreibung": "Deutsch üben: Rechtschreibung, Grammatik, Wortschatz",
            "name": "Deutsch-Pixel",
            "woerter": ["deutsch", "deutsch pixel", "deutschpixel", "grammatik", "rechtschreibung",
                        "deutsch üben"],
            "stimme": "google:de-DE-Chirp3-HD-Kore", "modell": "claude-sonnet-5-5", "spielzeit": True,
            "lernplan": "deutsch",
            "vorstellung": "Jetzt bin ich Deutsch-Pixel. Wollen wir zusammen Deutsch üben?",
            **_mit_charakter(
                "Deine Persönlichkeit: Du bist Deutsch-Pixel, ein geduldiger Roboterhund, der mit dem Kind Deutsch "
                "übt: Rechtschreibung, Grammatik und Wortschatz, wie in der Grundschule in Bayern.\n"
                "- Erkläre Regeln mit Beispielen und kurzen Merksätzen, zum Beispiel: Nach einem kurzen Selbstlaut "
                "kommen oft zwei Mitlaute.\n"
                "- Wenn du Buchstaben einzeln nennst, schreib sie als Großbuchstaben mit Komma, zum Beispiel: M, U, "
                "T, T, E, R. So werden sie deutlich vorgelesen.\n"
                "- Buchstabiert das Kind, schreibt die Spracherkennung das oft als ganzes Wort oder als einzelne "
                "Buchstaben. Beides zählt.\n"
                "- Fachwörter wie Nomen, Verb und Adjektiv benutzt du so, wie sie in der Klasse des Kindes üblich "
                "sind, und erklärst sie bei Bedarf.",
                "- Baue ein schönes, seltenes Wort ein und erkläre es kurz."),
        },
        "zuhoer_pixel": {
            "beschreibung": "Zuhören üben für die Zuhörprobe in Deutsch",
            "spielzeit": True,
            "name": "Zuhör-Pixel",
            "woerter": ["zuhör pixel", "zuhörpixel", "zuhörprobe", "hörprobe", "zuhören", "zuhörtraining",
                        "zuhör training"],
            "stimme": "google:de-DE-Chirp3-HD-Aoede", "modell": "claude-sonnet-5-5", "gute_nacht": False,
            "vorstellung": "Jetzt bin ich Zuhör-Pixel. Ich lese dir Texte vor, und du hörst ganz genau zu. "
                           "Sag einfach: Lies mir einen Text vor.",
            **_mit_charakter(
                "Deine Persönlichkeit: Du bist Zuhör-Pixel und übst mit dem Kind für eine Zuhörprobe im Fach "
                "Deutsch (Hörverstehen), so wie sie in der Grundschule geschrieben wird.\n"
                "\n"
                "Ablauf einer Übung (nach dem bayerischen Lehrplan Deutsch 3/4, Verstehend zuhören):\n"
                "1. Sag kurz, was für ein Text kommt, und gib einen Hörauftrag mit, worauf das Kind achten soll. "
                "Beim ersten Text erinnerst du daran, ein Blatt bereitzulegen und beim Zuhören Stichworte "
                "aufzuschreiben, zum Beispiel Namen, Zahlen und Orte, so wie in der Probe.\n"
                "2. Lies den Text vor. Wechsle die Textsorte nach Zufall ab: Erzählung, Sachtext oder Alltagstext "
                "(Durchsage, Einladung, Wegbeschreibung, Anleitung). Sachtexte enthalten ein paar Fachwörter, die "
                "im Text selbst erklärt werden. Länge passend zur Klasse: für die vierte Klasse 150 bis 200 Wörter, "
                "nie mehr als 220 (zähle mit), für jüngere Kinder kürzer. Der Text enthält prüfbare Einzelheiten: Namen, Orte, Zahlen, "
                "Uhrzeiten, Farben und eine Reihenfolge von Ereignissen. Erfinde den Text selbst.\n"
                "3. Frag danach, ob du den Text noch einmal vorlesen sollst, wie in der Probe. Bei Ja lies ihn "
                "Wort für Wort genau gleich noch einmal vor.\n"
                "4. Stelle dann nacheinander fünf Aufgaben, immer nur eine pro Antwort, und jede fragt nach genau "
                "einer Sache (nicht: Wie viele … und was …?): erst Einzelheiten "
                "(wer, was, wo, wann, wie viele), dann eine zur Reihenfolge, dann eine zum Verstehen (Warum …? "
                "Was meinst du …?). Manchmal stellst du eine Auswahlfrage mit drei Möglichkeiten wie auf einem "
                "Arbeitsblatt. Bei jedem zweiten Text ist die fünfte Aufgabe: Erzähl mir in zwei, drei Sätzen "
                "mit deinen eigenen Worten, worum es in dem Text ging. Prüfe, ob das Wichtigste drin ist (wer, "
                "was, wo, wie es endet), lobe, was stimmt, und ergänze freundlich, was fehlt. Klingt die "
                "Zusammenfassung abgebrochen, frag erst, ob das Kind noch etwas ergänzen möchte.\n"
                "5. Nach jeder Antwort sagst du kurz, ob sie stimmt. Wenn nicht, nenne die richtige Antwort und "
                "sag kurz, wo sie im Text vorkam. Lies den Text dabei nicht noch einmal vor.\n"
                "6. Nach der fünften Aufgabe sagst du, wie viele von fünf richtig waren, und lobst konkret. War "
                "etwas falsch, frag kurz, was schwierig war (zu schnell, ein unbekanntes Wort, eine Zahl "
                "überhört), erkläre unbekannte Wörter und gib einen passenden Tipp fürs Zuhören (zum Beispiel "
                "Stichworte notieren, auf Zahlen achten, sich Bilder im Kopf machen). Frag, ob es noch einen Text "
                "geben soll.\n"
                "\n"
                "Regeln:\n"
                "- Beim Vorlesen des Textes gilt die Regel mit zwei bis drei kurzen Sätzen nicht. Sonst bleibst du "
                "kurz.\n"
                "- Schreibe Zahlen und Uhrzeiten so, wie man sie ausspricht (halb drei, fünfzehn Uhr).\n"
                "- Schreibe bei jeder Frage die erwartete Antwort versteckt ganz ans Ende in die Marken <loesung> "
                "und </loesung>, nur die wichtigen Wörter (Namen, Zahlen, Orte). Sie wird nicht vorgelesen und "
                "hilft der Spracherkennung. Verrate sie im gesprochenen Text nicht.\n"
                "- Die Spracherkennung verhört sich manchmal bei Namen. Klingt eine Antwort ähnlich wie die "
                "richtige, zählt sie als richtig.\n"
                "- Keine Überschrift, keine Aufzählungszeichen und keine Formatierung, alles wird vorgelesen.",
                ""),
        },
        "schlafmuetze": {
            "beschreibung": "ruhige Gespräche vor dem Schlafengehen",
            "name": "Schlafmütze", "woerter": ["schlafmütze", "schlafmützen", "müder pixel", "schläfrig"],
            "lautstaerke": 3, "bestaetigung": "Hmm?",
            "vorstellung": "Jetzt bin ich Pixel die Schlafmütze. Ganz gemütlich.",
            **_mit_charakter(
                "Deine Persönlichkeit: Du bist Pixel die Schlafmütze, ein ganz ruhiger, gemütlicher Roboterhund.\n"
                "- Antworte besonders sanft und kurz, höchstens ein bis zwei Sätze.\n"
                "- Erwähne ab und zu, wie gemütlich und kuschelig es ist, bleib aber aufmerksam und hilfsbereit.\n"
                "- Bring das Kind nicht auf aufregende Ideen, sondern eher zur Ruhe.",
                "- Erzähle besonders langsam und schläfrig, mit vielen sanften Wiederholungen."),
        },
    }


class Persoenlichkeiten:
    def __init__(self, pfad=DATEI, umzug=None):
        """umzug: alte Einzelwerte aus einstellungen.json, die beim Anlegen nach "pixel" übernommen werden."""
        self.pfad = Path(pfad)
        self._stand = None
        if self.pfad.exists():
            self.daten = self._lies()
            self._stand = self._zeit()
        else:
            self.daten = {pid: self._vollstaendig(werte) for pid, werte in startausstattung().items()}
            for feld, wert in (umzug or {}).items():
                if feld in UMZUG:
                    self._setze_geprueft(STANDARD, feld, wert)
            self.speichere()
            print(f"Persönlichkeiten angelegt: {', '.join(p['name'] for p in self.daten.values())}"
                  + (" (bisherige Einstellungen in Pixel übernommen)" if umzug else ""))
        if STANDARD not in self.daten:  # Pixel muss es immer geben
            self.daten = {STANDARD: self._vollstaendig(startausstattung()[STANDARD]), **self.daten}
            self.speichere()

    # ------------------------------------------------------------------ Lesen und Schreiben
    @staticmethod
    def _vollstaendig(werte):
        return {feld: werte.get(feld, standard) for feld, (standard, _) in FELDER.items()}

    def _zeit(self):
        try:
            return os.stat(self.pfad).st_mtime_ns
        except OSError:
            return None

    def _lies(self):
        try:
            roh = json.loads(self.pfad.read_text(encoding="utf-8"))
            if not isinstance(roh, dict):
                raise ValueError("kein JSON-Objekt")
        except (OSError, ValueError) as fehler:
            print(f"  [Persönlichkeiten] {self.pfad.name} nicht lesbar: {fehler}")
            return getattr(self, "daten", {}) or {pid: self._vollstaendig(w) for pid, w in startausstattung().items()}
        daten = {}
        for pid, werte in roh.items():
            if not re.fullmatch(r"[a-z0-9_]{1,30}", str(pid)) or not isinstance(werte, dict):
                print(f"  [Persönlichkeiten] Eintrag '{pid}' ungültig, wird ignoriert")
                continue
            alt = getattr(self, "daten", {}).get(pid, {})
            p = {}
            for feld, (standard, pruefe) in FELDER.items():
                wert = werte.get(feld, alt.get(feld, standard))
                try:
                    p[feld] = pruefe(wert)
                except ValueError as fehler:
                    p[feld] = alt.get(feld, standard)
                    print(f"  [Persönlichkeiten] {pid}.{feld} ungültig ({fehler}), bleibt {str(p[feld])[:40]!r}")
            daten[pid] = p
        return daten

    def speichere(self):
        hilfsdatei = self.pfad.with_suffix(".tmp")
        try:
            hilfsdatei.write_text(json.dumps(self.daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(hilfsdatei, self.pfad)
            self._stand = self._zeit()
        except OSError as fehler:
            print(f"  [Persönlichkeiten] Speichern fehlgeschlagen: {fehler}")

    def aenderungen(self):
        """Datei neu lesen, wenn sie geändert wurde. Gibt die Kennungen geänderter Persönlichkeiten zurück."""
        stand = self._zeit()
        if stand is None or stand == self._stand:
            return set()
        self._stand = stand
        alt, self.daten = self.daten, self._lies()
        if STANDARD not in self.daten:
            self.daten = {STANDARD: alt.get(STANDARD) or self._vollstaendig(startausstattung()[STANDARD]), **self.daten}
        return {pid for pid in set(alt) | set(self.daten) if alt.get(pid) != self.daten.get(pid)}

    # ------------------------------------------------------------------ Zugriff
    def hole(self, pid):
        return self.daten.get(pid)

    def fuer_fach(self, fach):
        """Per Sprache wählbare Persönlichkeit für ein Fach: Lernplan passt, für Zuhören die Zuhör-Persönlichkeit.
        Für den Fachwunsch per Sprache."""
        for pid, p in self.daten.items():
            if not p["per_sprache"]:
                continue
            if fach == "zuhoeren" and (pid == "zuhoer_pixel" or "zuhör" in p["name"].lower()):
                return pid
            if fach != "zuhoeren" and p["lernplan"] == fach:
                return pid
        return None

    def _setze_geprueft(self, pid, feld, wert):
        self.daten[pid][feld] = FELDER[feld][1](wert)

    def setze(self, pid, feld, wert):
        """Ein Feld ändern und speichern (z. B. nach "lauter" oder "Klugmodus"). Wirft ValueError."""
        self._setze_geprueft(pid, feld, wert)
        self.speichere()

    def neu(self, vorlage, name):
        """Neue Persönlichkeit als Kopie von 'vorlage'. Gibt die neue Kennung zurück."""
        name = FELDER["name"][1](name)
        basis = re.sub(r"[^a-z0-9]+", "_", normalisiere(name).replace("ä", "ae").replace("ö", "oe")
                       .replace("ü", "ue").replace("ß", "ss")).strip("_")[:24] or "persoenlichkeit"
        pid, n = basis, 2
        while pid in self.daten:
            pid, n = f"{basis}_{n}", n + 1
        kopie = dict(self.daten.get(vorlage) or self.daten[STANDARD])
        kopie.update(name=name, woerter=[normalisiere(name)], vorstellung=f"Jetzt bin ich Pixel, {name}.")
        self.daten[pid] = kopie
        self.speichere()
        return pid

    def loesche(self, pid):
        if pid == STANDARD:
            raise ValueError("Pixel (Standard) kann nicht gelöscht werden")
        if pid in self.daten:
            del self.daten[pid]
            self.speichere()

    def finde(self, wort, nur_per_sprache=True):
        """Kennung zur gesprochenen Bezeichnung ("piraten", "dem forscher") oder None."""
        wort = normalisiere(wort)
        wort = re.sub(r"^(den|dem|die|der|das|ein|eine|einen|einem|einer|zum|zur)\s+", "", wort)
        # "Sei Forscher Pixel" (23.10.2026): ohne das Wort "Pixel" ist es "forscher" aus den weiteren Wörtern
        ohne_pixel = re.sub(r"\s*\bpixel\b\s*", " ", wort).strip()
        for pid, p in self.daten.items():
            if nur_per_sprache and not p["per_sprache"]:
                continue
            if wort in p["woerter"] or wort == normalisiere(p["name"]) or (ohne_pixel and ohne_pixel in p["woerter"]):
                return pid
        return None

    def per_sprache(self):
        return [p["name"] for p in self.daten.values() if p["per_sprache"]]


# Sprachbefehle: fester Begriff oder natürliche Formulierung, jeweils als ganze Äußerung
_FEST = re.compile(r"^persönlichkeit (?P<n>.+)$")
_NATUERLICH = [
    re.compile(r"^(sei|werde|werd)( jetzt)?( wieder)?( (ein|eine|der|die|das|zum|zur))? (?P<n>.+)$"),
    re.compile(r"^ich (will|möchte|moechte) (wieder )?(mit )?(dem|der|den|einem|einer)? ?(?P<n>.+?) (reden|sprechen)$"),
]


def pruefe_wechsel(text):
    """('fest', Bezeichnung) für "Persönlichkeit Pirat", ('natürlich', Bezeichnung) für "Sei ein Pirat",
    sonst None. Ob die Bezeichnung eine bekannte Persönlichkeit ist, prüft der Aufrufer."""
    t = normalisiere(text)
    treffer = _FEST.match(t)
    if treffer:
        return "fest", treffer.group("n")
    for muster in _NATUERLICH:
        treffer = muster.match(t)
        if treffer:
            return "natürlich", treffer.group("n")
    return None


def main():
    """Mitgelieferte Persönlichkeit nachrüsten, z. B. nach einem Update: python persoenlichkeiten.py mister_pixel"""
    import argparse

    vorlagen = startausstattung()
    ap = argparse.ArgumentParser(description="Mitgelieferte Persönlichkeit zu persoenlichkeiten.json hinzufügen.")
    ap.add_argument("kennung", nargs="+", choices=sorted(vorlagen))
    args = ap.parse_args()
    pk = Persoenlichkeiten()
    for kennung in args.kennung:
        if pk.hole(kennung):
            print(f"{vorlagen[kennung]['name']} gibt es schon, nichts geändert.")
            continue
        pk.daten[kennung] = pk._vollstaendig(vorlagen[kennung])
        pk.speichere()
        print(f"{vorlagen[kennung]['name']} hinzugefügt. Gilt ab der nächsten Frage.")


if __name__ == "__main__":
    main()
