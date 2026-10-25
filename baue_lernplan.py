"""Erzeugt lernplan_englisch.json nach LehrplanPLUS Bayern Englisch 3/4 (verbindlicher Wortschatz, Redemittel).

Aufruf: python baue_lernplan.py  (schreibt lernplan_englisch.json neben dieses Skript)
Wortlisten hier ändern, nicht in der JSON-Datei. Das Skript prüft, dass kein Eintrag doppelt vorkommt und dass
alle Inhaltswörter des verbindlichen Wortschatzes in Stufe 1 bis 3 enthalten sind.
Quellen (isb.bayern.de, Grundschule/Lehrplan_aktualisiert): Fachlehrplan Englisch 3/4, Liste verbindlicher
Wortschatz, Liste empfohlener Redemittel.
"""
import json
import re
import sys
from pathlib import Path

# (en, de, thema, Optionen) - Optionen: P = Pflicht (verbindlicher Wortschatz bzw. empfohlene Redemittel),
# S = Satz, R = nur als Rollenspiel mit erfundenen Personen (persönliche Angaben), auch=[...]
def e(en, de, thema, opt="", auch=None):
    d = {"en": en, "de": de, "thema": thema}
    if "S" in opt:
        d["typ"] = "satz"
    if "P" in opt:
        d["pflicht"] = True
    if "R" in opt:
        d["rollenspiel"] = True
    if auch:
        d["auch"] = auch
    return d


stufe1 = [
    e("hello", "Hallo", "Begrüßung", "P"), e("bye", "Tschüss", "Begrüßung", "P", ["Auf Wiedersehen"]),
    e("good morning", "Guten Morgen", "Begrüßung", "P"), e("yes", "ja", "Begrüßung", "P"),
    e("no", "nein", "Begrüßung", "P"), e("please", "bitte", "Begrüßung", "P"),
    e("thank you", "danke", "Begrüßung", "P", ["danke schön"]),
    *[e(en, de, "Farben", "P") for en, de in [("red", "rot"), ("blue", "blau"), ("green", "grün"),
      ("yellow", "gelb"), ("orange", "orange"), ("pink", "rosa"), ("brown", "braun"), ("black", "schwarz"),
      ("white", "weiß"), ("grey", "grau")]],
    *[e(en, de, "Zahlen bis 10", "P") for en, de in [("one", "eins"), ("two", "zwei"), ("three", "drei"),
      ("four", "vier"), ("five", "fünf"), ("six", "sechs"), ("seven", "sieben"), ("eight", "acht"),
      ("nine", "neun"), ("ten", "zehn")]],
    *[e(en, de, "Tiere", "P") for en, de in [("dog", "Hund"), ("cat", "Katze"), ("fish", "Fisch"),
      ("horse", "Pferd"), ("mouse", "Maus"), ("hamster", "Hamster")]],
    e("rabbit", "Kaninchen", "Tiere", "P", ["Hase"]),
    e("mother", "Mutter", "Familie", "P", ["Mama"]), e("father", "Vater", "Familie", "P", ["Papa"]),
    e("sister", "Schwester", "Familie", "P"), e("brother", "Bruder", "Familie", "P"),
    e("family", "Familie", "Familie", "P"),
    e("colour", "Farbe", "Farben", "P"),
    e("What colour is it?", "Welche Farbe hat es?", "Sätze", "PS"),
    e("How are you?", "Wie geht es dir?", "Sätze", "PS"),
    e("I'm fine, thanks.", "Mir geht es gut, danke.", "Sätze", "PS"),
    e("This is my dog.", "Das ist mein Hund.", "Sätze", "PS"),
]

stufe2 = [
    e("friend", "Freund", "Familie und Freunde", "P", ["Freundin"]), e("boy", "Junge", "Familie und Freunde", "P"),
    e("girl", "Mädchen", "Familie und Freunde", "P"), e("pet", "Haustier", "Familie und Freunde", "P"),
    e("house", "Haus", "Familie und Freunde", "P"), e("room", "Zimmer", "Familie und Freunde", "P"),
    e("name", "Name", "Familie und Freunde", "P"),
    e("eleven", "elf", "Zahlen", "P"), e("twelve", "zwölf", "Zahlen", "P"),
    e("Germany", "Deutschland", "Länder und Sprachen", "P"), e("England", "England", "Länder und Sprachen", "P"),
    e("German", "Deutsch", "Länder und Sprachen", "P"), e("English", "Englisch", "Länder und Sprachen", "P"),
    e("school", "Schule", "Schule", "P"), e("schoolbag", "Schultasche", "Schule", "P", ["Schulranzen"]),
    e("classroom", "Klassenzimmer", "Schule", "P"), e("teacher", "Lehrerin", "Schule", "P", ["Lehrer"]),
    e("book", "Buch", "Schule", "P"), e("pen", "Kuli", "Schule", "P", ["Stift", "Füller"]),
    e("pencil", "Bleistift", "Schule", "P"), e("rubber", "Radiergummi", "Schule", "P"),
    e("board", "Tafel", "Schule", "P"), e("chair", "Stuhl", "Schule", "P"), e("picture", "Bild", "Schule", "P"),
    e("sports", "Sport", "Schule", "P"),
    e("happy", "fröhlich", "Gefühle", "P", ["glücklich", "froh"]), e("sad", "traurig", "Gefühle", "P"),
    e("big", "groß", "Eigenschaften", "P"), e("small", "klein", "Eigenschaften", "P"),
    e("little", "klein", "Eigenschaften", "P"), e("old", "alt", "Eigenschaften", "P"),
    e("in", "in", "Wo ist es?", "P"), e("on", "auf", "Wo ist es?", "P"), e("under", "unter", "Wo ist es?", "P"),
    e("behind", "hinter", "Wo ist es?", "P"), e("next to", "neben", "Wo ist es?", "P"),
    e("in front of", "vor", "Wo ist es?", "P"),
    e("sorry", "Entschuldigung", "Höflichkeit", "P", ["tut mir leid"]),
    e("great", "toll", "Gefühle", "P", ["super", "großartig"]),
    e("My name is Tom.", "Ich heiße Tom.", "Sätze", "PSR"),
    e("What's your name?", "Wie heißt du?", "Sätze", "PSR"),
    e("How old are you?", "Wie alt bist du?", "Sätze", "PSR"),
    e("Where are you from?", "Woher kommst du?", "Sätze", "PSR"),
    e("I'm from Germany.", "Ich komme aus Deutschland.", "Sätze", "PS"),
    e("This is my family.", "Das ist meine Familie.", "Sätze", "PS"),
    e("I've got a little sister.", "Ich habe eine kleine Schwester.", "Sätze", "PS"),
    e("Who's this?", "Wer ist das?", "Sätze", "PS"),
    e("Have you got a pet?", "Hast du ein Haustier?", "Sätze", "PS"),
    e("It's black.", "Es ist schwarz.", "Sätze", "PS"),
    e("This is my room. It's small.", "Das ist mein Zimmer. Es ist klein.", "Sätze", "PS"),
    e("I'm happy.", "Ich bin fröhlich.", "Sätze", "PS"),
    e("Where is my pen, please?", "Wo ist bitte mein Kuli?", "Sätze", "PS"),
    e("It's under the chair.", "Er ist unter dem Stuhl.", "Sätze", "PS"),
    e("Sorry, I don't know.", "Tut mir leid, ich weiß es nicht.", "Sätze", "PS"),
    e("I like English.", "Ich mag Englisch.", "Sätze", "PS"),
    e("What time is it, please?", "Wie spät ist es, bitte?", "Uhrzeit", "PS"),
    e("It's seven o'clock.", "Es ist sieben Uhr.", "Uhrzeit", "PS"),
    e("It's two thirty.", "Es ist halb drei.", "Uhrzeit", "PS", ["Es ist zwei Uhr dreißig"]),
    e("Can I have your red pen, please?", "Kann ich bitte deinen roten Kuli haben?", "Sätze", "PS"),
    e("Here you are.", "Bitte schön.", "Sätze", "PS", ["Hier, bitte"]),
    e("You're welcome.", "Gern geschehen.", "Sätze", "PS"),
    e("Please help me.", "Hilf mir bitte.", "Sätze", "PS"),
]

stufe3 = [
    e("hobby", "Hobby", "Freizeit", "P"), e("football", "Fußball", "Freizeit", "P"),
    e("tennis", "Tennis", "Freizeit", "P"), e("swim", "schwimmen", "Freizeit", "P"),
    e("bike", "Fahrrad", "Freizeit", "P", ["Rad"]), e("ride a bike", "Fahrrad fahren", "Freizeit", "P"), e("play", "spielen", "Freizeit", "P"),
    e("weekend", "Wochenende", "Freizeit", "P"),
    e("party", "Party", "Feste", "P", ["Feier"]), e("birthday", "Geburtstag", "Feste", "P"),
    e("Halloween", "Halloween", "Feste", "P"),
    *[e(en, de, "Essen und Trinken", "P") for en, de in [("apple", "Apfel"), ("bread", "Brot"),
      ("butter", "Butter"), ("cheese", "Käse"), ("chips", "Pommes"), ("chocolate", "Schokolade"), ("egg", "Ei"),
      ("fruit", "Obst"), ("ham", "Schinken"), ("plum", "Pflaume"), ("salad", "Salat"),
      ("strawberry", "Erdbeere"), ("sweets", "Süßigkeiten"), ("tea", "Tee"), ("tomato", "Tomate"),
      ("water", "Wasser"), ("eat", "essen"), ("drink", "trinken")]],
    e("chicken", "Hähnchen", "Essen und Trinken", "P", ["Huhn"]),
    e("hot", "heiß", "Essen und Trinken", "P"), e("cold", "kalt", "Essen und Trinken", "P"),
    *[e(en, de, "Kleidung", "P") for en, de in [("dress", "Kleid"), ("jeans", "Jeans"),
      ("pullover", "Pullover"), ("shoes", "Schuhe")]],
    e("shirt", "Hemd", "Kleidung", "P", ["T-Shirt"]),
    e("fifteen", "fünfzehn", "Zahlen und Geld", "P"), e("thirty", "dreißig", "Zahlen und Geld", "P"),
    e("forty-five", "fünfundvierzig", "Zahlen und Geld", "P"),
    e("pound", "Pfund", "Zahlen und Geld", "P"), e("euro", "Euro", "Zahlen und Geld", "P"),
    e("dollar", "Dollar", "Zahlen und Geld", "P"),
    e("Can you come to my party?", "Kannst du zu meiner Party kommen?", "Sätze", "PS"),
    e("No, I'm sorry.", "Nein, tut mir leid.", "Sätze", "PS"),
    e("Happy birthday!", "Alles Gute zum Geburtstag!", "Sätze", "PS"),
    e("Merry Christmas!", "Frohe Weihnachten!", "Sätze", "PS"),
    e("When is your birthday?", "Wann hast du Geburtstag?", "Sätze", "PSR"),
    e("What's your hobby?", "Was ist dein Hobby?", "Sätze", "PS"),
    e("My hobby is football.", "Mein Hobby ist Fußball.", "Sätze", "PS"),
    e("I can swim.", "Ich kann schwimmen.", "Sätze", "PS"),
    e("I can't play tennis.", "Ich kann nicht Tennis spielen.", "Sätze", "PS"),
    e("Do you like chocolate?", "Magst du Schokolade?", "Sätze", "PS"),
    e("Yes, I do.", "Ja, mag ich.", "Sätze", "PS", ["Ja"]),
    e("No, I don't.", "Nein, mag ich nicht.", "Sätze", "PS"),
    e("Can I help you?", "Kann ich dir helfen?", "Einkaufen", "PS", ["Kann ich Ihnen helfen"]),
    e("I'd like an apple, please.", "Ich hätte gern einen Apfel, bitte.", "Einkaufen", "PS"),
    e("How many apples?", "Wie viele Äpfel?", "Einkaufen", "PS"),
    e("Two, please.", "Zwei, bitte.", "Einkaufen", "PS"),
    e("How much is it?", "Wie viel kostet das?", "Einkaufen", "PS"),
    e("It's eight pounds.", "Es kostet acht Pfund.", "Einkaufen", "PS"),
    e("It's five forty-five.", "Es ist Viertel vor sechs.", "Uhrzeit", "PS", ["Es ist fünf Uhr fünfundvierzig"]),
]

stufe4 = [
    e("purple", "lila", "Farben"), e("good night", "Gute Nacht", "Begrüßung"),
    e("mum", "Mama", "Familie"), e("dad", "Papa", "Familie"), e("grandma", "Oma", "Familie"),
    e("grandpa", "Opa", "Familie"), e("baby", "Baby", "Familie"),
    *[e(en, de, "Tiere") for en, de in [("bird", "Vogel"), ("cow", "Kuh"), ("pig", "Schwein"),
      ("sheep", "Schaf"), ("duck", "Ente")]],
    *[e(en, de, "Körper") for en, de in [("head", "Kopf"), ("eye", "Auge"), ("ear", "Ohr"), ("nose", "Nase"),
      ("mouth", "Mund"), ("hair", "Haare"), ("hand", "Hand"), ("arm", "Arm"), ("leg", "Bein"), ("foot", "Fuß")]],
    *[e(en, de, "Kleidung") for en, de in [("T-shirt", "T-Shirt"), ("trousers", "Hose"), ("skirt", "Rock"),
      ("socks", "Socken"), ("jacket", "Jacke")]],
    e("jumper", "Pullover", "Kleidung", "", ["Pulli"]), e("hat", "Mütze", "Kleidung", "", ["Hut"]),
    *[e(en, de, "Essen") for en, de in [("banana", "Banane"), ("milk", "Milch"), ("juice", "Saft"),
      ("cake", "Kuchen"), ("carrot", "Karotte")]],
    *[e(en, de, "Schule") for en, de in [("ruler", "Lineal"), ("scissors", "Schere"), ("glue", "Kleber")]],
    e("pencil case", "Federmäppchen", "Schule", "", ["Mäppchen"]),
    *[e(en, de, "Zahlen") for en, de in [("thirteen", "dreizehn"), ("fourteen", "vierzehn"),
      ("sixteen", "sechzehn"), ("seventeen", "siebzehn"), ("eighteen", "achtzehn"), ("nineteen", "neunzehn"),
      ("twenty", "zwanzig"), ("forty", "vierzig"), ("fifty", "fünfzig"), ("sixty", "sechzig"),
      ("seventy", "siebzig"), ("eighty", "achtzig"), ("ninety", "neunzig")]],
    e("one hundred", "hundert", "Zahlen", "", ["einhundert"]),
    *[e(en, de, "Wochentage") for en, de in [("Monday", "Montag"), ("Tuesday", "Dienstag"),
      ("Wednesday", "Mittwoch"), ("Thursday", "Donnerstag"), ("Friday", "Freitag"), ("Saturday", "Samstag"),
      ("Sunday", "Sonntag")]],
    *[e(en, de, "Monate") for en, de in [("January", "Januar"), ("February", "Februar"), ("March", "März"),
      ("April", "April"), ("May", "Mai"), ("June", "Juni"), ("July", "Juli"), ("August", "August"),
      ("September", "September"), ("October", "Oktober"), ("November", "November"), ("December", "Dezember")]],
    *[e(en, de, "Wetter") for en, de in [("sun", "Sonne"), ("rain", "Regen"), ("snow", "Schnee"),
      ("wind", "Wind"), ("cloud", "Wolke"), ("sunny", "sonnig"), ("rainy", "regnerisch"), ("warm", "warm")]],
    *[e(en, de, "Tätigkeiten") for en, de in [("read", "lesen"), ("sing", "singen"), ("dance", "tanzen"),
      ("cook", "kochen")]],
    e("run", "rennen", "Tätigkeiten", "", ["laufen"]), e("draw", "malen", "Tätigkeiten", "", ["zeichnen"]),
    e("jump", "springen", "Tätigkeiten", "", ["hüpfen"]),
    *[e(en, de, "Zuhause") for en, de in [("kitchen", "Küche"), ("bedroom", "Schlafzimmer"),
      ("living room", "Wohnzimmer"), ("garden", "Garten"), ("door", "Tür"), ("window", "Fenster")]],
    e("bathroom", "Badezimmer", "Zuhause", "", ["Bad"]),
    *[e(en, de, "Eigenschaften") for en, de in [("new", "neu"), ("fast", "schnell"), ("slow", "langsam"),
      ("hungry", "hungrig"), ("tired", "müde"), ("between", "zwischen")]],
    e("What's the weather like?", "Wie ist das Wetter?", "Sätze", "S"),
    e("It's sunny and warm.", "Es ist sonnig und warm.", "Sätze", "S"),
    e("Today is Monday.", "Heute ist Montag.", "Sätze", "S"),
    e("I am reading.", "Ich lese gerade.", "Ausblick Klasse 5", "S"),
    e("The dog is sleeping.", "Der Hund schläft gerade.", "Ausblick Klasse 5", "S"),
    e("We are playing football.", "Wir spielen gerade Fußball.", "Ausblick Klasse 5", "S"),
    e("What are you doing?", "Was machst du gerade?", "Ausblick Klasse 5", "S"),
    e("The ball is under the table.", "Der Ball ist unter dem Tisch.", "Ausblick Klasse 5", "S"),
    e("Let's play a game.", "Lass uns ein Spiel spielen.", "Ausblick Klasse 5", "S"),
]

plan = {
    "fach": "Englisch",
    "quelle": "LehrplanPLUS Grundschule Bayern, Englisch 3/4 (ISB, aktualisierte Fassung): Themengebiete 4.1 bis 4.4, "
              "Liste verbindlicher Wortschatz, Liste empfohlener Redemittel. Stufe 4 geht darüber hinaus.",
    "hinweis": "Britisches Englisch. pflicht = verbindlicher Wortschatz bzw. empfohlene Redemittel. rollenspiel = "
               "persönliche Angaben, nur mit erfundenen Personen üben, nie nach echten Daten des Kindes fragen.",
    "stufen": [
        {"stufe": 1, "name": "Start", "klassen": "vor Klasse 3 (freiwillig)",
         "beschreibung": "erste Wörter aus dem Pflichtwortschatz: Begrüßung, Farben, Zahlen bis 10, Tiere, Familie "
                         "(Englisch beginnt in Bayern in Klasse 3)", "eintraege": stufe1},
        {"stufe": 2, "name": "Klasse 3: Familie, Freunde, Schule", "klassen": "3",
         "beschreibung": "Lehrplan 4.1 Familie und Freunde, 4.2 Schule: sich vorstellen, Befinden, Schulsachen, "
                         "wo etwas ist, Uhrzeit, bitten und danken", "eintraege": stufe2},
        {"stufe": 3, "name": "Klasse 4: Freizeit, Feste, Einkaufen", "klassen": "4",
         "beschreibung": "Lehrplan 4.3 Freizeit und Feste, 4.4 Einkaufen: Hobbys, einladen, gratulieren, Essen, "
                         "Kleidung, einkaufen mit Mengen und Preisen", "eintraege": stufe3},
        {"stufe": 4, "name": "Extra", "klassen": "über den Pflichtwortschatz hinaus",
         "beschreibung": "zusätzliche Wörter (Körper, Wetter, Wochentage, Monate, Zahlen bis 100) und Ausblick "
                         "Klasse 5 (-ing-Form)", "eintraege": stufe4},
    ],
}

# Prüfungen: eindeutig, und alle Inhaltswörter des verbindlichen Wortschatzes kommen in Stufe 1 bis 3 vor
alle = [x for s in plan["stufen"] for x in s["eintraege"]]
schluessel = lambda t: " ".join(re.sub(r"[^\wäöüß ]", " ", t.lower().replace("'", "")).split())  # noqa: E731
doppelt = {k for k in [schluessel(x["en"]) for x in alle] if [schluessel(y["en"]) for y in alle].count(k) > 1}
assert not doppelt, doppelt
pflicht_text = " ".join(x["en"].lower() for s in plan["stufen"][:3] for x in s["eintraege"])
INHALT = """apple behind big bike birthday black blue board book boy bread brother brown butter bye cat chair cheese
chicken chips chocolate class classroom cold colour dog dress drink eat egg england english family father fine fish
football friend fruit german germany girl good great green grey halloween ham hamster happy hello help hobby horse hot
house little merry christmas morning mother mouse name next to o'clock old orange party pen pencil pet picture pink
plum pullover rabbit red ride room rubber sad salad school schoolbag shirt shoes sister small sorry sports
strawberry sweets swim tea teacher tennis tomato under water weekend welcome white yellow jeans in front of""".split()
fehlt = [w for w in INHALT if w not in pflicht_text]
assert not fehlt, f"Pflichtwörter fehlen: {fehlt}"
ziel = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "lernplan_englisch.json"
ziel.write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print({s["stufe"]: len(s["eintraege"]) for s in plan["stufen"]}, "gesamt", len(alle),
      "Pflicht", sum(1 for x in alle if x.get("pflicht")))
