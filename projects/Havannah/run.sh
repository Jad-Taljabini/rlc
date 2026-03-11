#!/usr/bin/env bash
set -u -o pipefail # errore se usi una variabile non definita o una pipe fallisce
set -e # lo script si ferma appena un comando restituisce errore

RLC="$HOME/Documents/rlc-infrastructure/rlc-release/install/bin/rlc" # Definisce una variabile RLC con il percorso dell'eseguibile rlc
mkdir -p build # Crea la directory build se non esiste
"$RLC" src/main.rl -o build/app # Compila il programma main.rl in build/app

set +e # Disabilita il flag di errore per il comando successivo, perché adesso vuole eseguire il programma anche se termina con errore, senza far morire subito lo script
./build/app 
code=$? # Salva il codice di uscita del programma
set -e # Riabilita il flag di errore per il comando successivo, perché adesso vuole eseguire il programma anche se termina con errore, senza far morire subito lo script

echo "Exit code: $code" # Stampa il codice di uscita del programma
exit $code # Termina lo script con il codice di uscita del programma
