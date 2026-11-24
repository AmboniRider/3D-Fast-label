# Generatore Targhette 3D (`.3MF` / `.STL`)

Applicazione desktop in Python per generare targhette/portachiavi personalizzati pronti per la stampa 3D multi-colore, basata sui modelli di riferimento `San_P_0.3mf` e `San_P_0.stl`.

![Anteprima dell'applicazione](screenshot.png)

## Funzionalità principali

- **Geometria parametrica fedelissima al modello originale**:
  - Dimensioni personalizzabili: altezza verticale **60–80 mm** (predefinita **70 mm**) e larghezza orizzontale **20–30 mm** (predefinita **25 mm**), con mantenimento dello spessore dell'anello attorno al foro.
  - Spessori esatti: base da **1.0 mm** e testo incassato a filo da **0.6 mm** (`Z = 0.4..1.0 mm`).
  - Orientamento *face-down* pronto per il piatto di stampa (testo rivolto verso il basso sulla superficie testurizzata).
- **Sottrazione geometrica 2.5D senza sovrapposizioni**:
  - La mesh del testo viene sottratta geometricamente dalla base nella fascia `0.4–1.0 mm`, generando due solidi chiusi (*watertight*) compatibili con qualsiasi slicer senza conflitti tra mesh.
- **Adattamento automatico del testo**:
  - Testo verticale lungo la targhetta con supporto sia a **riga singola** che a **più righe** (a capo manuale con `Invio` oppure automatico se il testo è troppo lungo).
  - Ridimensionamento automatico al massimo formato leggibile entro il margine configurabile (`1.0–5.0 mm`) dal bordo e dal foro.
- **Font e colori personalizzabili**:
  - Selezione tra tutti i font di sistema Windows (predefinito `Arial Narrow Bold`) oppure caricamento di un file `.ttf` / `.otf` personalizzato.
  - Scelta dei due colori per il file `.3mf` (predefiniti `#E03D19` per l'etichetta e `#FFFFFF` per il testo).
- **Esportazione flessibile**:
  - **`.3MF` multi-colore** (struttura compatibile Bambu Studio / OrcaSlicer con due estrusori separati: `Etichetta` ed `Testo`, più miniatura dinamica).
  - **2 file `.STL` separati** (`*_base.stl` e `*_testo.stl`) già allineati e orientati *face-down* sul piatto.
- **Generazione Multipla (Batch)**:
  - Creazione automatica in serie da elenco incollato o importato da file `.txt` / `.csv` (una targhetta per riga; usa `|` per forzare l'a capo).

## Requisiti

- Windows 10 / 11 con **Python 3.11+** (oppure gestito automaticamente da `uv`)
- **[uv](https://docs.astral.sh/uv/)** (gestore di pacchetti e ambienti virtuali Python)

Installazione rapida di `uv` su Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Installazione e Avvio

### Metodo rapido (consigliato)

Fai doppio clic su **`avvia.bat`**.  
Al primo avvio lo script crea automaticamente l'ambiente virtuale `.venv` tramite `uv sync` usando `pyproject.toml` e `uv.lock`, quindi avvia l'interfaccia grafica.

### Metodo manuale da terminale

```powershell
git clone https://github.com/AmboniRider/targhette.git
cd targhette
uv sync
.venv\Scripts\python.exe app.py
```

## Istruzioni d'uso

1. **Etichetta Singola**:
   - Scrivi il testo nella casella superiore (usa `Invio` per andare a capo manualmente, oppure lascia attiva l'opzione **Auto**).
   - Regola font, colori, dimensioni (`V` e `O`) e margine nella sezione **Stile e Parametri Modello** osservando l'anteprima in tempo reale a destra.
   - Clicca **Salva .3MF (Multi-colore)** per ottenere un unico file pronto per Bambu Studio / OrcaSlicer, oppure **Salva 2 .STL (Base + Testo)** / **Salva Entrambi**.
2. **Generazione Multipla**:
   - Passa alla scheda **Generazione Multipla**, inserisci un testo per riga (o carica un file `.txt`/`.csv`), scegli i formati e la cartella di destinazione, poi clicca **Genera Tutte le Targhette**.
3. **Stampa nello Slicer (Bambu Studio / OrcaSlicer)**:
   - Apri il file `.3MF`: `Etichetta` (estrusore 1) e `Testo` (estrusore 2) sono già separati e puoi cambiare il filamento/colore di ciascuna parte con un clic.
   - Se usi i due `.STL`, trascinali insieme sullo stesso piatto confermando di caricarli come un unico oggetto a più parti, quindi assegna gli estrusori a `*_base.stl` e `*_testo.stl`.

## Struttura del repository

- `app.py` — Interfaccia grafica desktop Tkinter e flusso di esportazione singola/batch
- `tag_generator.py` — Motore geometrico 2D/3D, estrazione glifi TTF/OTF ed esportatori `.3MF` e `.STL`
- `avvia.bat` — Script di avvio automatico con `uv`
- `pyproject.toml` / `uv.lock` — Dipendenze e lockfile riproducibile
- `San_P_0.3mf` / `San_P_0.stl` — Modelli 3D di riferimento
- `screenshot.png` — Anteprima dell'interfaccia dell'applicazione
