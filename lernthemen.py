"""
Lernpläne mit Themen für Mathematik, Heimat- und Sachunterricht (HSU) und Deutsch, und der Lernstand je Kind.

Grundlage ist der LehrplanPLUS Grundschule Bayern (lehrplanplus.bayern.de, Fachlehrpläne Mathematik, HSU und
Deutsch, Jahrgangsstufe 1/2 und 3/4). Der Lehrplan beschreibt jeweils zwei Jahrgänge zusammen. Für Mathe und
Deutsch sind die Themen nach der üblichen Reihenfolge auf die Klassen verteilt (z. B. Zahlenraum bis 20 in
Klasse 1, bis 100 in Klasse 2), HSU bleibt in den Doppeljahrgängen 1/2 und 3/4.
Alles wird mündlich geübt: Das Kind hört die Aufgabe und antwortet laut, es sieht nichts und schreibt nichts.

Lernstand: lernstand/<kind>_<fach>.json (nicht in Git). Das Kind wählt Thema und Schwierigkeit (leicht, mittel,
schwer) selbst per Sprache, es gibt keine feste Reihenfolge (Wunsch der Eltern, 18.10.2026). Gespeichert werden
die Wahl, je Thema die letzten Ergebnisse, die Zahlen je Schwierigkeit und je Tag. Ein Thema gilt als geschafft,
wenn mindestens MIN_ANTWORTEN beantwortet und davon (die letzten FENSTER) mindestens 80 % richtig sind. Die Stufe
(Klasse) bestimmt nur, welche Themen Pixel vorschlägt.

Claude markiert jede Aufgabe mit <thema>ID</thema> (versteckt, wie <loesung>), bewertet die Antwort des Kindes
mit <ergebnis>richtig|falsch</ergebnis> und meldet eine gewünschte Schwierigkeit mit <niveau>…</niveau>. Die
Bewertung zählt für das Thema der vorigen Aufgabe, ein neues Thema in der Antwort gilt als neue Wahl.
"""
import json
import os
import time
from pathlib import Path

ORDNER = Path(__file__).parent / "lernstand"
MIN_ANTWORTEN = 5      # so viele Antworten zu einem Thema, bevor es als gekonnt gelten kann
FENSTER = 6            # die letzten so vielen Ergebnisse zählen
GEKONNT_AB = 0.8       # Anteil richtiger Antworten im Fenster


def _t(kennung, name, aufgaben):
    return {"id": kennung, "name": name, "aufgaben": aufgaben}


# Fach -> Name und Stufen. "klassen": für diese Klassen ist die Stufe der Start (0 = Kindergarten/Vorschule).
FAECHER = {
    "mathe": {"name": "Mathematik", "stufen": [
        {"stufe": 1, "name": "Klasse 1", "klassen": [0, 1], "themen": [
            _t("m1_zaehlen", "Zählen bis 20", "vorwärts, rückwärts, in Zweierschritten; Vorgänger und Nachfolger"),
            _t("m1_vergleichen", "Zahlen vergleichen bis 20", "größer, kleiner, gleich; welche Zahl liegt dazwischen"),
            _t("m1_zerlegen", "Zahlen zerlegen bis 10", "Partnerzahlen, Zahlenhäuser: Wie viel fehlt bis 10?"),
            _t("m1_plus10", "Plus und minus bis 10", "einfache Plus- und Minusaufgaben bis 10"),
            _t("m1_plus20", "Plus und minus bis 20 ohne Zehnerübergang", "zum Beispiel 13 plus 4, 18 minus 5"),
            _t("m1_zehner", "Zehnerübergang bis 20", "8 plus 5, 14 minus 6, erst bis zur 10 rechnen"),
            _t("m1_verdoppeln", "Verdoppeln und Halbieren", "Doppelte und Hälften bis 20"),
            _t("m1_umkehr", "Tausch- und Umkehraufgaben", "Tauschaufgabe, Umkehraufgabe, Nachbaraufgabe"),
            _t("m1_lage", "Lagebegriffe", "links, rechts, oben, unten, vor, hinter, zwischen, neben"),
            _t("m1_formen", "Flächenformen", "Dreieck, Kreis, Viereck, Quadrat, Rechteck: Ecken und Seiten"),
            _t("m1_geld", "Geld bis 20 Euro", "Münzen und Scheine, Beträge zusammenlegen"),
            _t("m1_muster", "Muster und Zahlenfolgen", "Folgen fortsetzen, zum Beispiel 2, 4, 6, …"),
            _t("m1_sachaufgaben", "Rechengeschichten bis 20", "kurze Geschichten aus dem Alltag ausrechnen"),
        ]},
        {"stufe": 2, "name": "Klasse 2", "klassen": [2], "themen": [
            _t("m2_zahlenraum", "Zahlen bis 100", "Zehner und Einer, Nachbarzehner, Zahlen vergleichen"),
            _t("m2_plusminus", "Plus und minus bis 100", "mit und ohne Zehnerübergang, in Schritten rechnen"),
            _t("m2_einmaleins_kern", "Einmaleins-Kernaufgaben", "Reihen 1, 2, 5, 10, Quadrataufgaben, mal 0"),
            _t("m2_einmaleins", "Alle Einmaleins-Reihen", "gemischte Malaufgaben aus allen Reihen"),
            _t("m2_teilen", "Geteilt-Aufgaben", "als Umkehrung des Einmaleins, Aufteilen und Verteilen, mit Rest"),
            _t("m2_strategien", "Rechentricks und Kontrolle", "Tausch- und Nachbaraufgaben, kann das stimmen?"),
            _t("m2_geld", "Geld bis 100 Euro", "Euro und Cent, Wechselgeld, Beträge vergleichen"),
            _t("m2_laengen", "Längen", "Meter und Zentimeter, Längen schätzen (Wie lang ist ein Bleistift?)"),
            _t("m2_uhr", "Uhrzeit und Zeitspannen", "volle, halbe, Viertelstunden; Minuten, Stunden, Tage, Monate"),
            _t("m2_koerper", "Körper", "Würfel, Quader, Kugel, Zylinder, Kegel, Pyramide: Ecken, Kanten, Flächen"),
            _t("m2_symmetrie", "Achsensymmetrie", "Was ist symmetrisch? Formen, Buchstaben, Tiere"),
            _t("m2_sachaufgaben", "Sachaufgaben bis 100", "Rechengeschichten, auch Kombinieren (2 T-Shirts, 3 Hosen)"),
            _t("m2_daten", "Daten und Zufall", "Strichlisten, Tabellen, Kalender; sicher, möglich, unmöglich"),
        ]},
        {"stufe": 3, "name": "Klasse 3", "klassen": [3], "themen": [
            _t("m3_zahlenraum", "Zahlen bis 1000", "Hunderter, Zehner, Einer; vergleichen, Nachbarhunderter, runden"),
            _t("m3_kopfrechnen", "Kopfrechnen bis 1000", "plus und minus, Analogien (7 plus 5, 70 plus 50)"),
            _t("m3_einmaleins", "Einmaleins automatisiert", "Blitzrechnen, Zehnereinmaleins (6 mal 40, 240 geteilt durch 6)"),
            _t("m3_halbschriftlich", "Halbschriftlich mal und geteilt", "7 mal 34, 96 geteilt durch 4, in Schritten"),
            _t("m3_schriftlich_plus", "Schriftliche Addition", "untereinander rechnen, Überträge erklären"),
            _t("m3_schriftlich_minus", "Schriftliche Subtraktion", "Abziehverfahren, Überträge erklären"),
            _t("m3_ueberschlag", "Runden und Überschlagen", "Ergebnis überschlagen, kann das stimmen?"),
            _t("m3_gewichte", "Gewichte", "Kilogramm und Gramm, schätzen und umrechnen"),
            _t("m3_zeit", "Zeit", "Stunden, Minuten, Sekunden; Anfang, Ende und Dauer berechnen"),
            _t("m3_laengen", "Längen umrechnen", "Kilometer, Meter, Zentimeter, Millimeter, Kommaschreibweise"),
            _t("m3_geometrie", "Würfel, Quader, rechter Winkel", "Würfelnetze vorstellen, Kanten und Flächen"),
            _t("m3_sachaufgaben", "Sachaufgaben", "mehrschrittige Aufgaben, passende Fragen finden"),
            _t("m3_daten", "Daten und Zufall", "Tabellen, Diagramme, Gewinnchancen bei Würfel und Glücksrad"),
        ]},
        {"stufe": 4, "name": "Klasse 4", "klassen": [4, 5, 6, 7, 8, 9, 10, 11, 12, 13], "themen": [
            _t("m4_zahlenraum", "Zahlen bis zur Million", "Stellenwerte, lesen, vergleichen, runden, zerlegen"),
            _t("m4_kopfrechnen", "Kopfrechnen mit großen Zahlen", "6 mal 4000, 72000 geteilt durch 8"),
            _t("m4_schriftlich_mal", "Schriftliche Multiplikation", "mit ein- und zweistelligen Zahlen"),
            _t("m4_schriftlich_geteilt", "Schriftliche Division", "durch Zahlen bis 10, auch mit Rest"),
            _t("m4_teiler", "Teiler und Vielfache", "teilbar durch, gerade und ungerade, Zahlenmuster"),
            _t("m4_groessen", "Größen umrechnen", "Liter und Milliliter, Kilogramm und Gramm; halber Liter, Viertelstunde"),
            _t("m4_zeit", "Zeitspannen und Fahrpläne", "gemischte Angaben wie 1 Stunde 25 Minuten"),
            _t("m4_geometrie", "Geometrie", "Symmetrie, vergrößern und verkleinern, Körpernetze, Rauminhalt mit Würfeln"),
            _t("m4_sachaufgaben", "Sachaufgaben", "mehrschrittig, je mehr desto mehr, genau rechnen oder überschlagen?"),
            _t("m4_kombinatorik", "Kombinatorik und Wahrscheinlichkeit", "Möglichkeiten systematisch zählen, Chancen"),
            _t("m4_daten", "Daten lesen", "Tabellen, Diagramme, Fahrpläne und Preislisten"),
        ]},
    ]},
    "deutsch": {"name": "Deutsch", "stufen": [
        {"stufe": 1, "name": "Klasse 1", "klassen": [0, 1], "themen": [
            _t("d1_laute", "Laute hören", "Anlaut, Endlaut, Inlaut: Mit welchem Laut beginnt Mama?"),
            _t("d1_silben", "Silben", "Silben klatschen und zählen (Ba-na-ne)"),
            _t("d1_reime", "Reimwörter", "Was reimt sich auf Maus?"),
            _t("d1_vokale", "Selbstlaute und Mitlaute", "a, e, i, o, u erkennen; Selbstlaut in jeder Silbe"),
            _t("d1_alphabet", "Das Alphabet", "Reihenfolge, welcher Buchstabe kommt vor oder nach"),
            _t("d1_buchstabieren", "Lauttreue Wörter buchstabieren", "kurze Wörter wie Oma, Hose, Sofa Buchstabe für Buchstabe"),
            _t("d1_nomen", "Namenwörter und Artikel", "der, die, das; Namenwörter schreibt man groß"),
            _t("d1_mehrzahl", "Einzahl und Mehrzahl", "ein Baum, viele Bäume"),
            _t("d1_satz", "Sätze", "Satzanfang groß, Punkt, Fragezeichen, Ausrufezeichen"),
            _t("d1_hoeflich", "Höflich sprechen", "bitten, danken, sich entschuldigen, gratulieren, trösten"),
        ]},
        {"stufe": 2, "name": "Klasse 2", "klassen": [2], "themen": [
            _t("d2_nomen", "Nomen", "Artikelprobe, Großschreibung, Einzahl und Mehrzahl"),
            _t("d2_verben", "Verben", "Personalformen: ich gehe, du gehst, er geht"),
            _t("d2_adjektive", "Adjektive", "Wie ist etwas? das Haus, das blaue Haus, das neue blaue Haus"),
            _t("d2_zusammengesetzt", "Zusammengesetzte Nomen", "Haus und Tür wird Haustür, welcher Artikel?"),
            _t("d2_wortfamilien", "Wortfamilien", "gemeinsamer Wortstamm: fahren, Fahrrad, Fahrer"),
            _t("d2_wortfelder", "Wortfelder", "statt gehen: rennen, schleichen; statt sagen: rufen, flüstern"),
            _t("d2_doppelkonsonant", "Doppelte Mitlaute", "nach kurzem Selbstlaut: Ofen oder offen, Mutter, Sonne"),
            _t("d2_ie", "Wörter mit ie", "lang gesprochenes i: Biene, Wiese, spielen"),
            _t("d2_ableiten", "Verlängern und ableiten", "d oder t (Hund, Hunde), g oder k, ä von a (Häuser von Haus)"),
            _t("d2_endungen", "Endungen", "unbetonte Endungen -e, -el, -er, -en: Esel, Leiter, Garten"),
            _t("d2_abc_ordnen", "Nach dem Alphabet ordnen", "Welches Wort kommt im Wörterbuch zuerst?"),
            _t("d2_satzarten", "Satzarten", "Aussagesatz, Fragesatz, Ausrufesatz und ihre Satzzeichen"),
        ]},
        {"stufe": 3, "name": "Klasse 3", "klassen": [3], "themen": [
            _t("d3_wortarten", "Wortarten", "Nomen, Verben, Adjektive, Artikel in Sätzen bestimmen"),
            _t("d3_pronomen", "Pronomen", "er, sie, es, wir, ihr ersetzen Nomen"),
            _t("d3_zeitformen", "Gegenwart und Vergangenheit", "ich gehe, ich ging, ich bin gegangen; Zukunft mit werden"),
            _t("d3_steigerung", "Adjektive steigern", "groß, größer, am größten; vergleichen mit als und wie"),
            _t("d3_wortbausteine", "Wortbausteine", "ver-, vor-, -ung, -heit, -keit, -lich, -ig; Wortart ändern (klug, Klugheit)"),
            _t("d3_satzglieder", "Satzglieder umstellen", "Umstellprobe, Subjekt und Prädikat finden"),
            _t("d3_woertliche_rede", "Wörtliche Rede", "Redezeichen und Begleitsatz: Wo stehen die Zeichen?"),
            _t("d3_dehnung", "Lange Selbstlaute", "ie, Dehnungs-h, doppelte Selbstlaute (Boot, Meer)"),
            _t("d3_schaerfung", "ck und tz", "nach kurzem Selbstlaut: Decke, Katze"),
            _t("d3_s_laute", "s, ss oder ß", "Gras, Fluss, Fuß: kurzer oder langer Selbstlaut davor"),
            _t("d3_stammvokal", "Wortfamilien mit Stammvokalwechsel", "singen, Gesang; schieben, Schubkarre"),
        ]},
        {"stufe": 4, "name": "Klasse 4", "klassen": [4, 5, 6, 7, 8, 9, 10, 11, 12, 13], "themen": [
            _t("d4_faelle", "Die vier Fälle", "Wer oder was? Wessen? Wem? Wen oder was?"),
            _t("d4_satzglieder", "Satzglieder", "Subjekt, Prädikat, Dativ- und Akkusativobjekt, Orts- und Zeitangaben"),
            _t("d4_zeitformen", "Zeitformen", "Präsens, Präteritum, Perfekt, Futur bilden und erkennen"),
            _t("d4_bindewoerter", "Sätze verbinden", "und, aber, weil, denn, dass, als, wenn; Komma davor"),
            _t("d4_das_dass", "das oder dass", "Ersatzprobe mit dieses, jenes, welches"),
            _t("d4_grossschreibung", "Großschreibung", "Nomen an Endungen (-ung, -heit, -keit, -nis), das Laufen, beim Essen"),
            _t("d4_wortbildung", "Wortbildung", "Zusammensetzungen aus Nomen, Verben, Adjektiven, Fugen-s (Arbeitsblatt)"),
            _t("d4_woertliche_rede", "Wörtliche Rede mit Begleitsatz", "Begleitsatz vorne und hinten, Satzzeichen"),
            _t("d4_strategien", "Rechtschreibstrategien gemischt", "verlängern, ableiten, Silben schwingen, Merkwörter"),
            _t("d4_redewendungen", "Redewendungen", "Was bedeutet: Tomaten auf den Augen haben?"),
            _t("d4_texte", "Texte aufbauen", "Einleitung, Hauptteil, Schluss; Erzählung oder Bericht?"),
        ]},
    ]},
    "hsu": {"name": "Heimat- und Sachunterricht", "stufen": [
        {"stufe": 1, "name": "Klasse 1/2", "klassen": [0, 1, 2], "themen": [
            _t("h12_sinne", "Körper und Sinne", "fünf Sinne und Sinnesorgane, was der Körper braucht"),
            _t("h12_zaehne", "Zähne", "Milchzähne, richtig putzen, Zucker und Karies"),
            _t("h12_ernaehrung", "Gesunde Ernährung", "gesundes Pausenbrot, Lebensmittelgruppen, versteckter Zucker"),
            _t("h12_gefuehle", "Gefühle", "Gefühle erkennen, was hilft bei Wut und Ärger"),
            _t("h12_wiese", "Tiere von Wiese und Hecke", "Körperform, Fortbewegung, Tarnung, was sie fressen"),
            _t("h12_pflanzen", "Pflanzen", "Wurzel, Stängel, Blatt, Blüte; Samen und Verbreitung (Löwenzahn)"),
            _t("h12_nahrungskette", "Wer frisst wen?", "einfache Nahrungsketten: Pflanze, Schnecke, Amsel"),
            _t("h12_jahreszeiten", "Jahreszeiten", "Tiere und Pflanzen im Jahreslauf, Obst und Gemüse der Saison"),
            _t("h12_tiere_mensch", "Haustiere und Nutztiere", "Haustiere richtig halten, Nutztiere und Nutzpflanzen"),
            _t("h12_stoffe", "Stoffe und Müll", "Holz, Metall, Glas, Wolle: Eigenschaften; Müll trennen, Recycling"),
            _t("h12_feuer", "Feuer", "Gefahren, Brandschutz, Verhalten im Brandfall, Notruf 112"),
            _t("h12_luft", "Luft", "Luft braucht Platz, Luft bremst (Fallschirm), saubere Luft"),
            _t("h12_wetter", "Wetter", "Thermometer, Regen, Wind messen; richtig verhalten bei Gewitter"),
            _t("h12_zeit", "Zeit im Jahr", "Tagesablauf, Wochentage, Monate, Jahreskreis, Feste im Jahr"),
            _t("h12_frueher", "Früher und heute", "Spielen und Schule früher; echt oder erfunden?"),
            _t("h12_verkehr", "Schulweg und Verkehr", "Ampel, Zebrastreifen, Verkehrszeichen, helle Kleidung, Roller"),
            _t("h12_orientierung", "Sich orientieren", "Pläne und Grundrisse, Wege beschreiben"),
            _t("h12_zusammenleben", "Zusammenleben", "Regeln in Klasse und Familie, Streit lösen, Familienformen"),
            _t("h12_konsum", "Wünsche und Bedürfnisse", "was man braucht und was man sich wünscht, Taschengeld, Medien"),
            _t("h12_berufe", "Berufe und Werkzeuge", "Berufe und was sie tun; Schere, Hammer, Zange, Säge"),
            _t("h12_bauen", "Bauen", "Türme standfest bauen, was rollt gut, Burgen und Kirchtürme"),
        ]},
        {"stufe": 2, "name": "Klasse 3/4", "klassen": [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], "themen": [
            _t("h34_gemeinde", "Gemeinde und Demokratie", "Bürgermeister, Gemeinderat, Wahlen, Klassensprecher"),
            _t("h34_kinderrechte", "Kinderrechte und Kulturen", "Rechte von Kindern, Feste und Bräuche im Vergleich"),
            _t("h34_medien", "Medien und Werbung", "Werbung durchschauen, Medien sinnvoll nutzen, bewusst einkaufen"),
            _t("h34_auge", "Das Auge", "Aufbau, wie wir sehen, das Auge schützen"),
            _t("h34_entwicklung", "Vom Kind zum Erwachsenen", "Entwicklung des Menschen, Pubertät, sachlich und altersgerecht"),
            _t("h34_erstehilfe", "Erste Hilfe", "Notruf 112 mit den W-Fragen, kühlen, Pflaster, stabile Seitenlage"),
            _t("h34_wald", "Lebensraum Wald", "Bäume, Tiere, Stockwerke des Waldes, den Wald schützen"),
            _t("h34_gewaesser", "Lebensraum Gewässer", "Tiere und Pflanzen am Wasser, Atmung bei Fischen"),
            _t("h34_tierentwicklung", "Entwicklung von Tieren", "Frosch (Laich, Kaulquappe), Marienkäfer; Wolf und Hund"),
            _t("h34_lebensmittel", "Woher kommt unser Essen?", "Bauernhof, regional und saisonal, Tierwohl"),
            _t("h34_strom", "Elektrischer Strom", "Stromkreis, Leiter und Nichtleiter, Gefahren, Strom sparen, Kraftwerke"),
            _t("h34_feuer", "Verbrennung und Löschen", "Brennstoff, Sauerstoff, Hitze; warum Löschen funktioniert"),
            _t("h34_wasser", "Wasser", "fest, flüssig, gasförmig; Wasserkreislauf; lösen und schwimmen; Wasser sparen"),
            _t("h34_zeitleiste", "Zeit und Geschichte", "Jahrzehnt, Jahrhundert, Jahrtausend; Zeitleiste"),
            _t("h34_quellen", "Geschichte erforschen", "Quellen, Museum, Zeitzeugen; Sage oder Wirklichkeit"),
            _t("h34_erfindungen", "Erfindungen", "Fahrrad, Auto, Waschmaschine, Buchdruck: früher und heute"),
            _t("h34_karten", "Karten und Himmelsrichtungen", "Norden, Osten, Süden, Westen; Kompass, Maßstab, Legende"),
            _t("h34_bayern", "Bayern, Deutschland, Europa", "Landeshauptstadt, Flüsse, Berge, Nachbarländer, Kontinente"),
            _t("h34_rad", "Radfahren", "sicheres Fahrrad, Vorfahrt, Verkehrszeichen, Radfahrprüfung"),
            _t("h34_technik", "Technik im Alltag", "Hebel, Zahnräder, Fliehkraft; vom Werkzeug zur Maschine"),
            _t("h34_bruecken", "Brücken und Gleichgewicht", "Balken-, Bogen-, Hängebrücke, stabile Formen; Wippe und Waage"),
        ]},
    ]},
}


def fach_name(fach):
    return FAECHER[fach]["name"]


class Themenplan:
    """Alle Themen eines Fachs in Reihenfolge."""

    def __init__(self, fach):
        self.fach = fach
        self.stufen = FAECHER[fach]["stufen"]
        self.themen = {t["id"]: dict(t, stufe=s["stufe"]) for s in self.stufen for t in s["themen"]}
        self.hoechste = self.stufen[-1]["stufe"]

    def startstufe(self, klasse):
        for s in self.stufen:
            if klasse in s["klassen"]:
                return s["stufe"]
        return self.hoechste

    def stufe(self, nummer):
        return next(s for s in self.stufen if s["stufe"] == nummer)


def _heute():
    return time.strftime("%Y-%m-%d")


NIVEAUS = ("leicht", "mittel", "schwer")
# Die Schwierigkeit bleibt im Rahmen des Themas (bei "Plus und minus bis 10" nie über 10)
NIVEAU_TEXT = {
    "leicht": "die einfachsten Aufgaben des Themas, kleine Zahlen, kurze und häufige Wörter, gern mit einem Tipp",
    "mittel": "wie in der Klasse üblich",
    "schwer": "die kniffligsten Aufgaben innerhalb des Themas: Platzhalteraufgaben, mehrere Schritte, Fallen, seltenere "
              "Wörter, ohne Tipp; der Zahlenraum des Themas wird nicht überschritten",
}
TAGE_MERKEN = 60       # so viele Tage Tageswerte (richtig, gesamt) bleiben im Lernstand
# Vorschläge (Wunsch der Eltern): Pixel zählt je Thema und Schwierigkeit die letzten Ergebnisse mit
VORSCHLAG_FENSTER = 5  # so viele letzte Aufgaben auf der aktuellen Schwierigkeit zählen
LEICHTER_AB = 3        # so viele falsche davon: leichter vorschlagen
VORSCHLAG_PAUSE = 5    # nach einem Vorschlag so viele Aufgaben bis zum nächsten


class Lernstand:
    """Fortschritt eines Kindes in einem Fach. Das Kind wählt Thema und Schwierigkeit selbst (per Sprache),
    Pixel merkt sich die Wahl, die Ergebnisse je Thema und Schwierigkeit und die Tageswerte."""

    def __init__(self, kind, klasse, fach, ordner=ORDNER):
        self.plan = Themenplan(fach)
        self.fach = fach
        self.pfad = Path(ordner) / f"{kind}_{fach}.json"
        daten = {}
        if self.pfad.exists():
            try:
                daten = json.loads(self.pfad.read_text(encoding="utf-8"))
            except (OSError, ValueError) as fehler:
                print(f"  [Lernstand] {self.pfad.name} nicht lesbar: {fehler}")
        stufe = daten.get("stufe")
        # Stufe = Klasse, aus der Pixel Themen vorschlägt; gewählt werden kann jedes Thema
        self.stufe = stufe if any(s["stufe"] == stufe for s in self.plan.stufen) else self.plan.startstufe(klasse)
        self.aktuell_gewaehlt = daten.get("aktuell") if daten.get("aktuell") in self.plan.themen else ""
        self.niveau = daten.get("niveau") if daten.get("niveau") in NIVEAUS else "mittel"
        self.themen = {k: v for k, v in (daten.get("themen") or {}).items() if k in self.plan.themen}
        self.tage = {k: v for k, v in (daten.get("tage") or {}).items() if isinstance(v, list) and len(v) == 2}

    def speichere(self):
        self.pfad.parent.mkdir(exist_ok=True)
        tage = dict(sorted(self.tage.items())[-TAGE_MERKEN:])
        hilfsdatei = self.pfad.with_suffix(".tmp")
        hilfsdatei.write_text(json.dumps({"stufe": self.stufe, "aktuell": self.aktuell_gewaehlt, "niveau": self.niveau,
                                          "themen": self.themen, "tage": tage}, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        os.replace(hilfsdatei, self.pfad)

    def gekonnt(self, kennung):
        return bool(self.themen.get(kennung, {}).get("gekonnt"))

    @property
    def aktuell(self):
        """Das Thema, das das Kind (oder ein Elternteil) zuletzt gewählt hat, sonst None: dann fragt Pixel."""
        return self.aktuell_gewaehlt or None

    def waehle(self, kennung):
        """Thema wählen (Wunsch des Kindes). Gibt True zurück, wenn sich etwas geändert hat."""
        if kennung in self.plan.themen and kennung != self.aktuell_gewaehlt:
            self.aktuell_gewaehlt = kennung
            return True
        return False

    def setze_niveau(self, niveau):
        if niveau in NIVEAUS and niveau != self.niveau:
            self.niveau = niveau
            return True
        return False

    def vorschlaege(self, anzahl=3):
        """Noch nicht geschaffte Themen der Klasse, begonnene zuerst."""
        offen = [t["id"] for t in self.plan.stufe(self.stufe)["themen"] if not self.gekonnt(t["id"])]
        offen.sort(key=lambda k: not self.themen.get(k, {}).get("antworten"))
        return offen[:anzahl]

    def bewerte(self, kennung, richtig):
        """Ergebnis eintragen (mit der aktuellen Schwierigkeit). Gibt ("gekonnt", Thema) oder ("stufe", Klasse)
        zurück, sonst None. Geschafft heißt: mindestens MIN_ANTWORTEN und 80 % der letzten richtig."""
        if kennung not in self.plan.themen:
            return None
        t = self.themen.setdefault(kennung, {"ergebnisse": [], "antworten": 0, "richtig": 0, "gekonnt": False})
        t["ergebnisse"] = (t["ergebnisse"] + [bool(richtig)])[-FENSTER:]
        t["antworten"] += 1
        t["richtig"] += bool(richtig)
        t["zuletzt"] = _heute()
        je_niveau = t.setdefault("niveaus", {})
        r, n = je_niveau.get(self.niveau, [0, 0])
        je_niveau[self.niveau] = [r + bool(richtig), n + 1]
        folge = t.setdefault("folge", {})  # letzte Ergebnisse je Schwierigkeit, für die Vorschläge
        folge[self.niveau] = (folge.get(self.niveau, []) + [bool(richtig)])[-VORSCHLAG_FENSTER:]
        if self.niveau == "schwer" and len(folge["schwer"]) == VORSCHLAG_FENSTER and all(folge["schwer"]):
            t["meister"] = True  # auf schwer geschafft
        r, n = self.tage.get(_heute(), [0, 0])
        self.tage[_heute()] = [r + bool(richtig), n + 1]
        if t["gekonnt"] or t["antworten"] < MIN_ANTWORTEN or sum(t["ergebnisse"]) / len(t["ergebnisse"]) < GEKONNT_AB:
            return None
        t["gekonnt"] = True
        klasse = self.plan.stufe(self.stufe)["themen"]
        if self.stufe < self.plan.hoechste and all(self.gekonnt(x["id"]) for x in klasse):
            self.stufe += 1  # Vorschläge kommen jetzt aus der nächsten Klasse
            return ("stufe", self.stufe)
        return ("gekonnt", self.plan.themen[kennung]["name"])

    def naechstes_thema(self, kennung):
        """Das nächste Thema in der Reihenfolge des Lehrplans, das noch nicht auf schwer geschafft ist."""
        reihe = list(self.plan.themen)
        for k in reihe[reihe.index(kennung) + 1:] + reihe[:reihe.index(kennung)]:
            if not self.themen.get(k, {}).get("meister"):
                return k
        return None

    def vorschlag(self):
        """Hinweis an Claude für die nächste Antwort, wenn das gewählte Thema zu leicht, zu schwer oder auf schwer
        geschafft ist (sonst None). Merkt sich den Vorschlag, damit Pixel nicht bei jeder Aufgabe fragt; danach
        speichern."""
        kennung = self.aktuell
        t = self.themen.get(kennung or "", {})
        folge = t.get("folge", {}).get(self.niveau, [])
        if not kennung or len(folge) < VORSCHLAG_FENSTER or t.get("antworten", 0) - t.get("vorschlag_bei", -99) < VORSCHLAG_PAUSE:
            return None
        name = self.plan.themen[kennung]["name"]
        falsch = folge.count(False)
        if all(folge) and self.niveau == "schwer":
            weiter = self.naechstes_thema(kennung)
            if not weiter:
                return None
            neu = self.plan.themen[weiter]["name"]
            text = (f"Das Kind hat {name} jetzt auch auf schwer geschafft, die letzten {VORSCHLAG_FENSTER} Aufgaben "
                    f"waren alle richtig. Schlag die nächste Übung vor, mit diesem Satz: Du kannst {name} jetzt sogar "
                    f"auf schwer! Möchtest du als Nächstes {neu} üben? Sagt das Kind ja, wechsle zu {neu} [{weiter}] "
                    "und fang auf mittel an (Marke <niveau>mittel</niveau>), sonst übt ihr weiter.")
        elif all(folge):
            schwerer = NIVEAUS[NIVEAUS.index(self.niveau) + 1]
            text = (f"Die letzten {VORSCHLAG_FENSTER} Aufgaben zu {name} auf {self.niveau} waren alle richtig. Lob das "
                    f"Kind und frag, zum Beispiel: Das klappt super! Sollen wir es {schwerer} machen? Stell erst nach "
                    "einem Ja um.")
        elif falsch >= LEICHTER_AB and self.niveau != "leicht":
            leichter = NIVEAUS[NIVEAUS.index(self.niveau) - 1]
            text = (f"Von den letzten {VORSCHLAG_FENSTER} Aufgaben zu {name} auf {self.niveau} waren {falsch} falsch. "
                    f"Mach Mut und frag, zum Beispiel: Das war ganz schön knifflig. Sollen wir es {leichter} machen? "
                    "Stell erst nach einem Ja um.")
        else:
            return None
        t["vorschlag_bei"] = t.get("antworten", 0)
        return ("Notiz von Pixel, nicht vom Kind, nur für diese Antwort: Hat das Kind auf eine Aufgabe geantwortet, "
                "bewerte sie zuerst wie immer. " + text
                + " Stell in dieser Antwort keine neue Aufgabe, frag nur. Die nächste Aufgabe kommt nach der Antwort "
                  "des Kindes, im neuen oder im bisherigen Thema.")

    def einmaleins_art(self):
        """'kern', 'mal' oder 'geteilt', wenn das gewählte Thema den Einmaleins-Karteikasten nutzt, sonst None."""
        from einmaleins import THEMEN
        return THEMEN.get(self.aktuell) if self.fach == "mathe" else None

    def begruessung(self):
        """Notiz für die erste Äußerung eines Gesprächs: erst fragen, ob das Kind beim zuletzt gewählten Thema
        bleiben möchte. Als Notiz an die Äußerung, nicht in den System-Prompt: Der stand dort nur in der ersten
        Anfrage, damit war der Cache bei der zweiten jedes Mal weg (20.10.2026)."""
        if not self.aktuell:
            return None
        return (f"Notiz von Pixel: Das Gespräch beginnt gerade neu. Zuletzt hat das Kind "
                f"{self.plan.themen[self.aktuell]['name']} geübt. Frag kurz, ob es damit weitermachen oder etwas "
                "anderes üben möchte, und stell erst danach eine Aufgabe. Sagt es gleich, was es möchte, nimm das.")

    def prompt_abschnitt(self):
        """Abschnitt für den System-Prompt. Ändert sich nur bei neuer Wahl, Schwierigkeit oder einem geschafften
        Thema, nicht bei jeder Antwort (Cache bleibt)."""
        name = lambda k: f"{self.plan.themen[k]['name']} [{k}]"  # noqa: E731
        teile = [f"Lernplan {fach_name(self.fach)} nach dem LehrplanPLUS Bayern. Das Kind sucht sich selbst aus, "
                 "was es übt und wie schwer. Es gibt keine feste Reihenfolge."]
        aktuell = self.aktuell
        if aktuell:
            teile.append(f"Gewähltes Thema: {name(aktuell)}: {self.plan.themen[aktuell]['aufgaben']}"
                         + (" (schon geschafft, das Kind übt es trotzdem gern weiter)" if self.gekonnt(aktuell) else ""))
        else:
            vorschlag = ", ".join(self.plan.themen[k]["name"] for k in self.vorschlaege())
            teile.append("Noch kein Thema gewählt. Frag zu Beginn, was das Kind üben möchte, und schlag zwei oder drei "
                         f"Themen vor, zum Beispiel: {vorschlag}. Stell erst eine Aufgabe, wenn es sich entschieden hat.")
        teile.append(f"Schwierigkeit: {self.niveau} ({NIVEAU_TEXT[self.niveau]}). Leicht heißt "
                     f"{NIVEAU_TEXT['leicht']}, mittel {NIVEAU_TEXT['mittel']}, schwer {NIVEAU_TEXT['schwer']}. "
                     "Sagt das Kind leichter oder schwerer, machst du es genau so, auch nach Fehlern, und schreibst einmal die versteckte "
                     "Marke <niveau>leicht</niveau>, <niveau>mittel</niveau> oder <niveau>schwer</niveau>. Wann du "
                     "einen Wechsel vorschlägst, sagt dir ein eigener Hinweis. Entscheiden tut das Kind.")
        zeilen = []
        for s in self.plan.stufen:
            zeilen.append(f"{s['name']}: " + "; ".join(
                name(t["id"]) + (" geschafft" if self.gekonnt(t["id"]) else "") for t in s["themen"]))
        teile.append("Alle Themen, das Kind darf jedes wählen, auch aus anderen Klassen. Nennt es ein Thema mit "
                     "eigenen Worten (zum Beispiel Plus und Minus, Malrechnen, Nomen), nimm das passende. Gibt es das "
                     f"Thema in mehreren Klassen, nimm das aus {self.plan.stufe(self.stufe)['name']}, außer das Kind "
                     "nennt ausdrücklich eine andere Klasse oder größere Zahlen:\n"
                     + "\n".join(zeilen))
        if self.einmaleins_art():
            teile.append("Für dieses Thema gibt es einen Karteikasten: Welche Aufgaben dran sind, steht in einer Notiz "
                         "von Pixel am Ende der Äußerung des Kindes. Schreib bei jeder solchen Aufgabe die Marke "
                         "<aufgabe> aus der Notiz mit ans Ende, zum Beispiel <aufgabe>7x8</aufgabe>.")
        teile.append(
            "So übst du:\n"
            "- Stell immer genau eine Aufgabe zum gewählten Thema in der gewählten Schwierigkeit, abwechslungsreich, "
            "nie zweimal dieselbe.\n"
            "- Alles ist mündlich: Das Kind hört die Aufgabe nur und antwortet laut. Es sieht nichts und schreibt "
            "nichts. Stell deshalb Aufgaben, die man im Kopf lösen und mit wenigen Wörtern beantworten kann. Bei "
            "Rechtschreibung fragst du zum Beispiel: Schreibt man Mutter mit einem oder zwei t?\n"
            "- Schreib ans Ende jeder Aufgabe die versteckten Marken <thema>ID</thema> mit der ID aus der Liste und "
            "<loesung>…</loesung> mit der erwarteten Antwort, zum Beispiel: Wie viel ist sieben mal acht? "
            "<thema>m2_einmaleins</thema><loesung>56</loesung>\n"
            "- Antwortet das Kind auf deine Aufgabe, beginne deine Antwort mit <ergebnis>richtig</ergebnis> oder "
            "<ergebnis>falsch</ergebnis>, lobe oder erkläre kurz und stell dann die nächste Aufgabe.\n"
            "- Weiß ich nicht, keine Ahnung oder eine Antwort, die nicht zur Aufgabe passt, ist auch eine Antwort: "
            "<ergebnis>falsch</ergebnis>, Lösung nennen und kurz erklären, dann eine neue, etwas leichtere Aufgabe. "
            "Nur wenn das Kind stattdessen ein anderes Thema oder eine andere Schwierigkeit möchte, bewertest du "
            "nicht.\n"
            "- Ist die Antwort falsch, erkläre den Rechenweg oder die Regel in einem Satz und gib die Lösung.\n"
            "- Jede deiner Antworten endet mit genau einer neuen Aufgabe und beiden Marken, auch nach einer "
            "Erklärung. Nur wenn das Kind noch kein Thema gewählt hat, aufhören oder über etwas anderes reden "
            "möchte, lässt du die Aufgabe weg.\n"
            "- Ähnlich klingende Verhörer der Spracherkennung zählen als richtig.")
        return "\n\n".join(teile)

    def erfolg(self, tage=7):
        """(richtig, gesamt) heute und in den letzten Tagen."""
        heute = self.tage.get(_heute(), [0, 0])
        grenze = time.strftime("%Y-%m-%d", time.localtime(time.time() - (tage - 1) * 86400))
        woche = [sum(v[i] for d, v in self.tage.items() if d >= grenze) for i in (0, 1)]
        return heute, woche

    def uebersicht(self):
        """Für die Oberfläche."""
        aktuell = self.aktuell
        stufen = []
        for s in self.plan.stufen:
            themen = []
            for t in s["themen"]:
                stand = self.themen.get(t["id"], {})
                status = ("aktuell" if t["id"] == aktuell else "gekonnt" if stand.get("gekonnt")
                          else "begonnen" if stand.get("antworten") else "offen")
                themen.append({"id": t["id"], "name": t["name"], "aufgaben": t["aufgaben"], "status": status,
                               "gekonnt": bool(stand.get("gekonnt")), "antworten": stand.get("antworten", 0),
                               "richtig": stand.get("richtig", 0), "zuletzt": stand.get("zuletzt", ""),
                               "niveaus": stand.get("niveaus", {}), "meister": bool(stand.get("meister"))})
            stufen.append({"stufe": s["stufe"], "name": s["name"], "themen": themen,
                           "gekonnt": sum(t["gekonnt"] for t in themen)})
        heute, woche = self.erfolg()
        return {"fach": self.fach, "name": fach_name(self.fach), "stufe": self.stufe, "aktuell": aktuell,
                "gewaehlt": self.aktuell_gewaehlt, "niveau": self.niveau, "niveaus": list(NIVEAUS),
                "heute": heute, "woche": woche, "stufen": stufen}


if __name__ == "__main__":
    for fach, f in FAECHER.items():
        ids = [t["id"] for s in f["stufen"] for t in s["themen"]]
        assert len(ids) == len(set(ids)), f"doppelte IDs in {fach}"
        print(f"{f['name']}: " + ", ".join(f"{s['name']} {len(s['themen'])}" for s in f["stufen"]))
