# 3D Fast Label (`v1.1 beta`)

Applicazione desktop in Python per generare targhette/portachiavi personalizzati pronti per la stampa 3D multi-colore, basata sui modelli STEP di riferimento presenti in `modelli/` (`Targhetta Pill.step`, `Targhetta rectangular.step`, `Targhetta round.step`).

![Anteprima dell'applicazione](screenshot.png)

## Funzionalità principali

- **Tre modelli parametrici selezionabili** (tutti con smussi `0.2 mm × 45°` sopra e sotto su bordo esterno e foro):
  - **Pillola verticale** (`Targhetta Pill.step`): altezza **65–85 mm** (predefinita **75 mm**), larghezza **20–30 mm** (predefinita **25 mm**), spessore base **1.2–2.4 mm** (predefinito **1.8 mm**), foro superiore ad anello (`Ø 17 mm` con anello robusto da `4.0 mm`) e testo verticale.
  - **Rettangolare orizzontale** (`Targhetta rectangular.step`): larghezza **70–90 mm** (predefinita **80 mm**), altezza **40–60 mm** (predefinita **50 mm**), spessore base **1.0–2.2 mm** (predefinito **1.6 mm**), angoli arrotondati (`r = 5 mm`), foro in alto a sinistra (`Ø 5 mm` a `6×6 mm`) e testo orizzontale.
  - **Circolare** (`Targhetta round.step`): diametro **30–40 mm** (predefinito **35 mm**), spessore base **1.0–2.2 mm** (predefinito **1.6 mm**), foro superiore (`Ø 5 mm` a `5.5 mm` dal bordo), bordino circolare esterno opzionale da `1.0 mm` (disattivo di default) e testo orizzontale.
- **Spessore base regolabile** (`±0.6 mm` rispetto al default STEP, passo `0.2 mm`) e **due stili di rilievo selezionabili su tutti i modelli**:
  - **A filo (`0.6 mm`, *face-down*)**: base con sede incassata `0.6 mm` (`T-0.6..T`) e testo a filo tramite sottrazione geometrica 2.5D senza sovrapposizioni, pronto per stampa capovolta sul piatto.
  - **In rilievo (`+0.6 mm`)**: base piena con testo in rilievo `0.6 mm` sopra la superficie (`T..T+0.6`).
- **Adattamento automatico e allineamento del testo**:
  - Supporto sia a **riga singola** che a **più righe** (a capo manuale con `Invio` oppure automatico se il testo è troppo lungo), con allineamento **Centro** o **Sinistra**.
  - Ridimensionamento automatico al massimo formato leggibile entro il margine configurabile (`1.0–5.0 mm`) dal bordo e dal foro.
- **Font e colori personalizzabili**:
  - Selezione tra tutti i font di sistema Windows (predefinito `Arial Narrow Bold`) oppure caricamento di un file `.ttf` / `.otf` personalizzato.
  - Scelta dei due colori per il file `.3mf` (predefiniti `#FDE68A` giallo chiaro per l'etichetta e `#000000` nero per il testo).
- **Esportazione flessibile**:
  - **`.3MF` multi-colore** (struttura compatibile Bambu Studio / OrcaSlicer con due estrusori separati: `Etichetta` ed `Testo`, più miniatura dinamica).
  - **2 file `.STL` separati** (`*_base.stl` e `*_testo.stl`) già allineati e orientati *face-down* sul piatto.
- **Generazione Multipla (Batch)**:
  - Creazione automatica in serie da elenco incollato o importato da file `.txt` / `.csv` (una targhetta per riga; usa `|` per forzare l'a capo).
- **Interfaccia moderna (`sv-ttk`) con Tema Chiaro / Scuro**:
  - Rilevamento automatico del tema di Windows all'avvio e pulsante nella barra superiore per passare in tempo reale tra tema **Chiaro** e **Scuro**.

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
git clone https://github.com/AmboniRider/3D-Fast-label.git
cd 3D-Fast-label
uv sync
.venv\Scripts\python.exe app.py
```

## Istruzioni d'uso

1. **Etichetta Singola**:
   - Scrivi il testo nella casella superiore (usa `Invio` per andare a capo manualmente, oppure lascia attiva l'opzione **Auto**).
   - Regola font, colori, dimensioni (`V`/`O` o `Ø`), spessore base e margine nella sezione **Stile e Parametri Modello** osservando l'anteprima in tempo reale a destra.
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
- `modelli/` — Modelli 3D di riferimento in formato STEP (`Targhetta Pill.step`, `Targhetta rectangular.step`, `Targhetta round.step`)
- `screenshot.png` — Anteprima dell'interfaccia dell'applicazione
