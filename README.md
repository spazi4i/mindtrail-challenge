# MindTrail Challenge

Demo composta da:
- firmware Arduino (`mindtrail_challenge.ino`) per leggere 12 pulsanti;
- app desktop Python (`mindtrail_demo.py`) per gestire tempi, domande e stato gara.
- archivio domande esterno in `questions/*.json` selezionabile da UI.

## Requisiti
- Arduino IDE
- Python 3.x (installato localmente)
- Libreria Python `pyserial` (solo se usi Arduino via seriale)

## 1) Caricare il firmware Arduino
1. Apri `mindtrail_challenge.ino` in Arduino IDE.
2. Seleziona scheda e porta corretta.
3. Carica lo sketch sulla board.
4. Chiudi il `Serial Monitor`/`Serial Plotter` prima di avviare la GUI Python.

## 2) Installare dipendenze Python
Da terminale nella cartella progetto:

```powershell
cd "c:\Users\treds\Desktop\4.i\2025 2026 PROGETTI\MINDTRAIL CHALLENGE\MDC_APP"
& "C:\Users\treds\AppData\Local\Programs\Python\Python314\python.exe" -m pip install --upgrade pip
& "C:\Users\treds\AppData\Local\Programs\Python\Python314\python.exe" -m pip install pyserial
```

## 3) Avviare la demo Python
```powershell
cd "c:\Users\treds\Desktop\4.i\2025 2026 PROGETTI\MINDTRAIL CHALLENGE\MDC_APP"
 py -m watchdog.watchmedo auto-restart --patterns="*.py" --recursive -- py .\mindtrail_demo.py
```

## 3.1) Creare la build eseguibile (.exe)
Metodo rapido (script automatico):

```powershell
cd "c:\Users\treds\Desktop\4.i\2025 2026 PROGETTI\MINDTRAIL CHALLENGE\MDC_APP"
.\build_exe.bat
```

Output:
- `dist\MindTrailDemo.exe`

Metodo manuale:

```powershell
py -m pip install --upgrade pyinstaller
py -m PyInstaller --onefile --windowed --name MindTrailDemo mindtrail_demo.py
```

## 4) Configurazione in app
Nella schermata iniziale:
1. Imposta partecipanti, domande, run, tempo visualizzazione domanda.
2. Seleziona la `Materia` (caricata dai file JSON in `questions/`).
3. Clicca `Aggiorna porte` per rilevare le COM disponibili.
4. Seleziona la porta corretta (es. `COM12`) oppure inseriscila a mano.
5. Clicca `Avvia demo`.

## Domande esterne per materia
Ogni materia è un file JSON nella cartella `questions/` (esempio: `questions/scienze_motorie.json`).

Formato minimo:

```json
{
  "subject": "Nome materia",
  "levels": {
    "Facile": [
      { "question": "Testo domanda", "answer": "Testo risposta" }
    ],
    "Media": [],
    "Difficile": [],
    "Plus": []
  }
}
```

Regole:
- servono tutti i livelli: `Facile`, `Media`, `Difficile`, `Plus`;
- ogni livello deve avere almeno una domanda valida;
- la risposta è salvata nel dataset (utile per estensioni future).

## Modalità senza Arduino
Se vuoi usare solo la simulazione:
1. Apri `mindtrail_demo.py`.
2. Imposta `USE_SERIAL = False`.
3. Avvia l’app e usa il pulsante `Simula atleta 1`.

## Troubleshooting rapido
- Errore `Accesso negato` sulla COM:
  - la porta è occupata (chiudi Serial Monitor/altre app).
- Errore porta non valida:
  - inserisci formato `COMx` (es. `COM3`, `COM12`).
- Nessuna porta rilevata:
  - scollega/ricollega Arduino, poi `Aggiorna porte`.
- `pyserial` mancante:
  - reinstalla con `python -m pip install pyserial`.
