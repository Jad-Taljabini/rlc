# Havannah — UI Fuzzing benchmark

Progetto PII: fuzzing guidato da coverage su una GUI Tkinter del gioco **Havannah**, scritto in [Rulebook](https://rl-language.github.io) (RLC).

Repository: [Jad-Taljabini/rlc](https://github.com/Jad-Taljabini/rlc) — branch **`UI_Fuzzer`**, cartella `projects/Havannah/`.

```bash
git clone https://github.com/Jad-Taljabini/rlc.git
cd rlc
git checkout UI_Fuzzer
cd projects/Havannah
```

## Prerequisiti

- **macOS** (testato su Apple Silicon; Tkinter incluso in Python di sistema)
- **Python 3** (`python3`)
- **Compilatore RLC** — build Rulebook come da [documentazione ufficiale](https://rl-language.github.io/rlc.html), oppure installazione locale in `rlc-infrastructure/rlc-release/install/bin/rlc`

Se RLC non è nel path predefinito:

```bash
export RLC=/percorso/a/rlc
```

## Avvio rapido

Dalla cartella `projects/Havannah/` (dopo clone e checkout):

```bash
./run.sh build             # genera build/lib.dylib e build/wrapper.py
./run.sh gui               # GUI pulita (src/gui.py)
./run.sh fuzz --help       # fuzzer UI
```

`build/` non è versionato: va rigenerato con `./run.sh build` dopo ogni clone.

## Smoke test (~1 minuto)

Verifica che build, GUI buggy e fuzzer funzionino:

```bash
./scripts/smoke_test.sh
```

## Benchmark GUI (`gui_buggy.py`)

`src/gui_buggy.py` è una fork di `gui.py` con **6 bug artificiali principali** su reset, redraw, label, click dopo fine partita, click occupato e status terminale. L’oracle in `src/ui_fuzz_engine.py` li rileva e li registra in `bugs_found.json`.

Esempio — una run breve con scheduler RGR:

```bash
./run.sh build

python3 src/ui_fuzz_engine.py \
  --target gui \
  --gui-file src/gui_buggy.py \
  --mode rgr_positive_rate \
  --bug-variant-mod 100 \
  --time-budget-seconds 120 \
  --iterations 100000000 \
  --report-every 50 \
  --seed 1 \
  --run-id smoke_rgr_x100_s1 \
  --out-dir fuzz_out/smoke_rgr_x100_s1
```

Oppure, passando gli argomenti tramite `run.sh`:

```bash
./run.sh fuzz --target gui --gui-file src/gui_buggy.py --mode random_raw \
  --time-budget-seconds 60 --iterations 100000000 --seed 1 \
  --out-dir fuzz_out/smoke_random
```

## Modalità di fuzzing

| Modalità | Descrizione breve |
|----------|-------------------|
| `random_raw` | Sequenze casuali da zero (baseline) |
| `valid_random` | Solo click validi sulla board |
| `coverage_guided` | Corpus + peso per coverage guadagnata |
| `coverage_guided_rate` | Come sopra, peso per `(coverage + 5×bug) / tempo` |
| `rgr_positive` | Premia traiettorie che hanno già trovato bug |
| `rgr_positive_rate` | Variante rate del precedente |
| `anti_rgr_negative` | Penalizza traiettorie bug-yielding |
| `anti_rgr_negative_rate` | Variante rate del precedente |

## Parametro `--bug-variant-mod` (X)

Con `X=1` ogni bug oracle conta una sola volta (comportamento storico). Con `X>1` lo stesso bug base produce varianti sintetiche `BASE::vN` (hash del contesto di esecuzione mod `X`), per simulare scenari clusterizzati nel **conteggio**, senza aggiungere bug reali in `gui_buggy.py`.

## Replica esperimento principale (cluster v2)

Campagna usata per i risultati della relazione: **7 modalità × X ∈ {1,10,100,500} × 3 seed**, 240 s per run (~5.5 h sequenziali + pause).

```bash
./scripts/replicate_cluster_v2.sh
```

Su Mac, per evitare sleep durante run lunghi:

```bash
caffeinate -dims ./scripts/replicate_cluster_v2.sh
```

Output in `fuzz_out/cluster_final_v2_<timestamp>/`. I risultati non vanno committati (vedi `.gitignore`).

## Output di ogni run

Ogni cartella `--out-dir` contiene:

| File | Contenuto |
|------|-----------|
| `stats.json` | Metriche aggregate (bugs/sec, bugs/sample, coverage, …) |
| `bugs_found.json` | Bug unici con `base_bug_id` e variante sintetica |
| `timeline.csv` | Serie temporale per grafici |
| `corpus.json` / `top_corpus.json` | Seed mutati salvati |
| `coverage.json` | Bitmap coverage azioni/GUI |

## Struttura

```
projects/Havannah/
├── run.sh                 # build / gui / fuzz
├── scripts/
│   ├── smoke_test.sh
│   └── replicate_cluster_v2.sh
├── src/
│   ├── main.rl            # logica di gioco Rulebook
│   ├── gui.py             # GUI Tkinter
│   ├── gui_buggy.py       # GUI con bug iniettati (benchmark)
│   └── ui_fuzz_engine.py  # fuzzer + oracle + scheduler
└── build/                 # generato (non in git)
```

## Riferimenti

- [Rulebook / RLC](https://rl-language.github.io)
- [Fork del progetto](https://github.com/Jad-Taljabini/rlc) — branch `UI_Fuzzer`, cartella `projects/Havannah`
