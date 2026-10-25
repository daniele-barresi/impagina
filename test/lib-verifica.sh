# Funzioni condivise dalle suite di verifica (run-tests.sh, run-tests-api.sh).
# Si include con:  source "$ROOT/test/lib-verifica.sh"

PASSATI=0
FALLITI=0

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; PASSATI=$((PASSATI + 1)); }
ko()   { printf '  \033[31m✗\033[0m %s\n' "$1"; FALLITI=$((FALLITI + 1)); }
capitolo() { printf '\n\033[1m%s\033[0m\n' "$1"; }

verifica() {  # verifica <descrizione> <atteso> <ottenuto>
  if [ "$2" = "$3" ]; then ok "$1"; else ko "$1 (atteso: '$2', ottenuto: '$3')"; fi
}

contiene() { # contiene <descrizione> <file> <testo>
  if grep -qF -- "$3" "$2"; then ok "$1"; else ko "$1 (testo '$3' assente)"; fi
}

riepilogo() {
  printf '\n\033[1mRisultato: %d superati, %d falliti\033[0m\n' "$PASSATI" "$FALLITI"
  [ "$FALLITI" -eq 0 ]
}
