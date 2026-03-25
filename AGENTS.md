# MindTrail Challenge - Repo Overview

## Scopo del progetto
Questo repository implementa una demo didattica del **MindTrail Challenge** con:
- un firmware Arduino che rileva la pressione di 12 pulsanti;
- un'app desktop Python (Tkinter) che gestisce gara, tempi, domande e classifica parziale.

## Struttura file
- `mindtrail_challenge.ino`: codice Arduino per lettura pulsanti e invio eventi su seriale.
- `mindtrail_demo.py`: interfaccia grafica e logica della gara.

## Flusso generale
1. Arduino inizializza i 12 ingressi in `INPUT_PULLUP`.
2. Alla pressione di un pulsante invia su seriale:
   - `beep`
   - `PULSANTE:<numero>`
3. L'app Python apre la porta seriale (`COM12`, `9600 baud`) e ascolta le righe in ingresso.
4. Quando riceve `PULSANTE:n`, aggiorna lo stato dell'atleta `n`:
   - avvio cronometro alla prima pressione;
   - registrazione split/run alle pressioni successive;
   - visualizzazione domande per i run di quiz;
   - completamento gara all'ultimo run.

## Logica della gara (Python)
- Numero massimo atleti: `12`.
- Parametri configurabili da UI:
  - partecipanti;
  - numero domande;
  - numero run;
  - durata visualizzazione domanda.
- Le domande sono in 4 livelli:
  - `Facile`, `Media`, `Difficile`, `Plus`.
- Il livello viene scelto in base alla progressione della gara.
- La UI mostra per ogni atleta:
  - tempo totale (formato `mm:ss.cc`);
  - run completati;
  - livello corrente;
  - posizione run (provvisoria/definitiva);
  - fase (corsa, risposta, gara terminata);
  - testo domanda o prompt "CORRI".

## Calcolo posizioni
- Per ogni numero di run, l'app ordina gli atleti per tempo cumulativo.
- Se non tutti hanno completato quel run, la posizione è mostrata come provvisoria.
- Quando tutti lo completano, la posizione diventa definitiva.

## Modalità demo/simulazione
- Pulsante UI: `Simula atleta 1` per test senza Arduino.
- `USE_SERIAL = True` abilita la lettura reale da seriale (richiede `pyserial`).

## Dipendenze e avvio
- Python 3
- Tkinter (normalmente incluso in Python desktop)
- `pyserial` (se si usa Arduino via seriale)

Esecuzione app:
- `python mindtrail_demo.py`

Caricamento firmware:
- aprire `mindtrail_challenge.ino` in Arduino IDE e caricare sulla scheda.

## Note tecniche importanti
- Porta seriale hardcoded: `PORTA = "COM12"` in `mindtrail_demo.py` (da adattare al PC).
- In `mindtrail_challenge.ino` è presente un possibile refuso nell'ultima riga del loop:
  - `statoPrecedente[i] = statoAttuale;s`
  - la `s` finale causa errore di compilazione e va rimossa.
