# Lizenzen und Hinweise

## Programmcode

Der Programmcode dieses Repositorys steht unter der GNU General Public License v3.0, siehe [LICENSE](LICENSE).

## Wake-Word-Modell „Hey Pixel“ (`wakewords/hey_pixel.onnx`)

Das Modell wurde mit der Trainings-Pipeline von [openWakeWord](https://github.com/dscripka/openWakeWord) erstellt. Dabei werden Trainingsdaten verwendet, die nur für nicht kommerzielle Zwecke freigegeben sind; auch die mit openWakeWord mitgelieferten Modelle stehen unter CC BY-NC-SA 4.0. Das Modell darf deshalb **nur für nicht kommerzielle Zwecke** verwendet und weitergegeben werden (CC BY-NC-SA 4.0). Wer Pixel kommerziell nutzen will, braucht ein eigenes, entsprechend lizenziertes Wake-Word-Modell.

## Bibliotheken

Die Bibliotheken werden bei der Installation aus dem Python Package Index geladen und sind nicht Teil dieses Repositorys. Es gelten ihre eigenen Lizenzen, unter anderem:

- [piper-tts](https://github.com/OHF-Voice/piper1-gpl): GPL-3.0-or-later (Sprachausgabe)
- [openWakeWord](https://github.com/dscripka/openWakeWord) 0.4.0: Wake Word und Sprechpausen-Erkennung
- [anthropic](https://github.com/anthropics/anthropic-sdk-python): MIT
- numpy, requests, sounddevice: jeweils eigene freie Lizenzen

## Stimmen

Die Piper-Stimmen (z. B. `de_DE-kerstin-low`, `de_DE-thorsten-medium`, `de_DE-ramona-low`) werden beim ersten Start aus dem Repository [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) heruntergeladen und nicht mitgeliefert. Für jede Stimme gilt die Lizenz, die dort in ihrer Modellkarte steht.

Google-Stimmen und Deepgram werden als Cloud-Dienste über eure eigenen Konten genutzt; es gelten deren Nutzungsbedingungen.

## Lernpläne

Die Themen und der Englisch-Wortschatz (`lernthemen.py`, `lernplan_englisch.json`, `baue_lernplan.py`) sind am LehrplanPLUS Grundschule Bayern ausgerichtet (Staatsinstitut für Schulqualität und Bildungsforschung, [lehrplanplus.bayern.de](https://www.lehrplanplus.bayern.de/)). Es handelt sich um eine eigene Zusammenstellung von Themen und Wörtern, nicht um eine Kopie der Lehrplandokumente. Pixel ist kein offizielles Angebot des Freistaats Bayern.
