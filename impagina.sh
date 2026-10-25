#!/usr/bin/env bash
#
# impagina — wrapper attorno a "docker run".
#
#   ./impagina.sh documento.md --template company
#   ./impagina.sh ./note --output ./pdf --template company --recursive
#
# Si occupa di montare le cartelle giuste, di passare il tuo utente al
# container (altrimenti i PDF risulterebbero di proprieta' di root) e di
# tradurre i percorsi dell'host in percorsi interni al container.

set -euo pipefail

IMAGE="${IMPAGINA_IMAGE:-impagina}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
TEMPLATES_DIR="${IMPAGINA_TEMPLATES_DIR:-$SCRIPT_DIR/templates}"

# I codici di uscita coincidono con quelli del tool nel container:
#   2 input non trovato, 3 template non trovato, 1 uso errato.
die() { printf 'Errore: %s\n' "$1" >&2; exit "${2:-1}"; }

usage() {
  cat <<'USAGE'
Uso: ./impagina.sh <file.md|cartella> [opzioni]

Opzioni principali (inoltrate al tool nel container):
  -o, --output PERCORSO   file .pdf o cartella di destinazione
  -t, --template NOME     template da applicare (default: company)
  -r, --recursive         converte anche le sottocartelle
      --toc               genera l'indice
      --cover/--no-cover  copertina in prima pagina
      --watermark TESTO   filigrana diagonale, es. "BOZZA"
  -v, --verbose           mostra i comandi eseguiti nel container

Variabili d'ambiente:
  IMPAGINA_IMAGE          nome dell'immagine Docker (default: impagina)
  IMPAGINA_TEMPLATES_DIR  cartelle dei template, separate da ':' (default:
                          ./templates accanto a questo script); la prima
                          vince, i template inclusi restano disponibili

Servizio API (vedi ./impagina.sh --api aiuto):
  ./impagina.sh --api avvia|ferma|stato|log
  ./impagina.sh --api chiave nuova|elenco|revoca [NOME]
USAGE
}

# ===========================================================================
# Servizio API: ./impagina.sh --api ...
# ===========================================================================
# Riconosciuto solo come primo argomento: un'opzione con il trattino non si
# confonde mai con il nome di un file o di una cartella da convertire, quindi
# la modalita' one-shot qui sotto resta esattamente com'era.

API_CHIAVI="$SCRIPT_DIR/config/chiavi.conf"
API_PORTA="${IMPAGINA_API_PORTA_HOST:-8080}"
NOME_CHIAVE_RE='^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'

api_usage() {
  cat <<USAGE
Uso: ./impagina.sh --api <comando>

Servizio:
  avvia                 costruisce l'immagine e avvia il servizio (docker compose)
  ferma                 ferma il servizio (i lavori restano nel volume)
  stato                 stato del container e del servizio
  log                   segue i log (Ctrl+C per uscire)

Chiavi di accesso (in config/chiavi.conf):
  chiave nuova NOME     crea una chiave e mostra il token UNA sola volta
  chiave elenco         elenca le chiavi attive e revocate
  chiave revoca NOME    revoca una chiave (effetto immediato, senza riavvio)

Il servizio ascolta su http://127.0.0.1:$API_PORTA (IMPAGINA_API_PORTA_HOST
per cambiare porta). Configurazione e uso dell'API: README, "Servizio API".
USAGE
}

# docker compose (v2) oppure docker-compose (v1), sempre sul compose.yaml
# accanto allo script, da qualunque cartella si lanci il comando.
compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose --project-directory "$SCRIPT_DIR" -f "$SCRIPT_DIR/compose.yaml" "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose --project-directory "$SCRIPT_DIR" -f "$SCRIPT_DIR/compose.yaml" "$@"
  else
    die "serve Docker Compose (il plugin 'docker compose' oppure docker-compose)."
  fi
}

chiavi_attive() {
  [ -f "$API_CHIAVI" ] || return 0
  awk '!/^[[:space:]]*(#|$)/ { print $1 }' "$API_CHIAVI"
}

genera_token() {
  # 32 byte casuali in base64url: 256 bit, nessun carattere da proteggere
  # in un header HTTP o in una variabile d'ambiente.
  printf 'imp_%s' "$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n')"
}

chiave_nuova() {
  local nome="${1:-}" token impronta
  [ -n "$nome" ] || die "indica il nome della chiave, es.: ./impagina.sh --api chiave nuova nextcloud"
  [[ "$nome" =~ $NOME_CHIAVE_RE ]] \
    || die "nome non valido: '$nome' (lettere, cifre, . _ -, al massimo 64 caratteri)."
  if chiavi_attive | grep -qxF -- "$nome"; then
    die "la chiave '$nome' esiste gia'. Revocala prima di ricrearla."
  fi
  mkdir -p -- "$(dirname -- "$API_CHIAVI")"
  if [ ! -f "$API_CHIAVI" ]; then
    printf '# Chiavi di accesso al servizio API di impagina: vedi chiavi.conf.esempio\n' \
      > "$API_CHIAVI"
  fi
  # Il file contiene solo impronte, non i token: puo' essere leggibile
  # dall'utente del container (uid 10001), che non coincide con il tuo.
  chmod 644 "$API_CHIAVI"
  token="$(genera_token)"
  impronta="$(printf '%s' "$token" | sha256sum | cut -d' ' -f1)"
  printf '%s sha256:%s  # creata il %s\n' "$nome" "$impronta" "$(date +%F)" >> "$API_CHIAVI"
  cat <<FINE
Chiave '$nome' creata. Questo e' il token, e non verra' mostrato di nuovo:

  $token

Usalo nell'intestazione HTTP:  Authorization: Bearer $token
Se il servizio e' gia' avviato, la chiave vale da subito.
FINE
}

chiave_elenco() {
  [ -f "$API_CHIAVI" ] || { echo "Nessuna chiave: crea la prima con './impagina.sh --api chiave nuova NOME'."; return 0; }
  awk '
    /^[[:space:]]*#[[:space:]]*revocata[[:space:]]/ { print "  " $3 "\trevocata" ; next }
    /^[[:space:]]*(#|$)/ { next }
    { print "  " $1 "\tattiva" }
  ' "$API_CHIAVI"
}

chiave_revoca() {
  local nome="${1:-}" nuovo
  [ -n "$nome" ] || die "indica il nome della chiave da revocare."
  chiavi_attive | grep -qxF -- "$nome" || die "nessuna chiave attiva con nome '$nome'."
  # La riga resta, commentata: si vede quando e' stata revocata e il servizio
  # la ignora. Riscrittura atomica, perche' il servizio puo' leggere il file
  # in qualunque momento.
  nuovo="$API_CHIAVI.nuovo"
  awk -v nome="$nome" -v oggi="$(date +%F)" '
    !/^[[:space:]]*#/ && $1 == nome { print "# revocata " $0 " (revocata il " oggi ")"; next }
    { print }
  ' "$API_CHIAVI" > "$nuovo"
  chmod 644 "$nuovo"
  mv -f -- "$nuovo" "$API_CHIAVI"
  echo "Chiave '$nome' revocata: le richieste con quel token vengono rifiutate da subito."
}

attendi_salute() {
  local i
  for i in $(seq 1 30); do
    if compose exec -T impagina-api python3 -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/salute', timeout=2)" \
        >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

api() {
  command -v docker >/dev/null 2>&1 || die "Docker non e' installato o non e' nel PATH."
  case "${1:-aiuto}" in
    avvia)
      [ -n "$(chiavi_attive)" ] \
        || die "nessuna chiave in $API_CHIAVI: il servizio non partirebbe.
  Creane una con:  ./impagina.sh --api chiave nuova NOME"
      compose up -d --build
      if attendi_salute; then
        echo "impagina-api in ascolto su http://127.0.0.1:$API_PORTA"
      else
        compose logs --tail 20 impagina-api >&2
        die "il servizio non risponde: vedi i log qui sopra."
      fi ;;
    ferma)  compose down ;;
    stato)
      compose ps
      compose exec -T impagina-api python3 -c \
        "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/salute', timeout=3).read().decode())" \
        2>/dev/null || echo "Il servizio non risponde." ;;
    log)    compose logs -f --tail 100 impagina-api ;;
    chiave)
      case "${2:-}" in
        nuova)  chiave_nuova "${3:-}" ;;
        elenco) chiave_elenco ;;
        revoca) chiave_revoca "${3:-}" ;;
        *)      die "comando sconosciuto: 'chiave ${2:-}'. Usa nuova, elenco o revoca." ;;
      esac ;;
    aiuto|-h|--help) api_usage ;;
    *) api_usage >&2; exit 1 ;;
  esac
}

if [ "${1:-}" = "--api" ]; then
  shift
  api "$@"
  exit $?
fi

# --- percorso assoluto anche per file che non esistono ancora --------------
abspath() {
  local target="$1" dir base
  dir="$(dirname -- "$target")"
  base="$(basename -- "$target")"
  [ -d "$dir" ] || die "cartella inesistente: $dir"
  printf '%s/%s\n' "$(cd -- "$dir" && pwd -P)" "$base"
}

# --- separa l'input, l'output e il resto degli argomenti -------------------
INPUT=""
OUTPUT=""
PASSTHROUGH=()

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)             usage; exit 0 ;;
    -o|--output)           [ $# -ge 2 ] || die "$1 richiede un percorso"; OUTPUT="$2"; shift 2 ;;
    --output=*)            OUTPUT="${1#*=}"; shift ;;
    -i|--input)            [ $# -ge 2 ] || die "$1 richiede un percorso"; INPUT="$2"; shift 2 ;;
    --input=*)             INPUT="${1#*=}"; shift ;;
    -*)                    PASSTHROUGH+=("$1"); shift ;;
    *)
      if [ -z "$INPUT" ]; then INPUT="$1"; else PASSTHROUGH+=("$1"); fi
      shift ;;
  esac
done

[ -n "$INPUT" ] || { usage; exit 1; }

command -v docker >/dev/null 2>&1 \
  || die "Docker non e' installato o non e' nel PATH."

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  die "immagine Docker '$IMAGE' non trovata.
  Costruiscila con:  docker build -t $IMAGE \"$SCRIPT_DIR\""
fi

[ -e "$INPUT" ] || die "file o cartella non trovata: $INPUT" 2

HOST_PWD="$(pwd -P)"
INPUT_ABS="$(abspath "$INPUT")"

MOUNTS=(-v "$HOST_PWD:/data")
DISPLAY_MAP="/data=$HOST_PWD"

# --- traduzione dei percorsi host -> percorsi del container ----------------
# La cartella corrente e' sempre montata su /data. Se input o output stanno
# altrove, montiamo anche quelle cartelle, cosi' il tool funziona da
# qualunque posizione senza che tu debba pensare ai volumi.
# Il risultato viene messo in CONTAINER_PATH invece di essere stampato:
# in una sostituzione di comando la funzione girerebbe in una subshell e le
# aggiunte a MOUNTS andrebbero perse.
CONTAINER_PATH=""
to_container_path() {
  local host_path="$1" mount_point="$2" dir base
  case "$host_path" in
    "$HOST_PWD"/*) CONTAINER_PATH="/data/${host_path#"$HOST_PWD"/}" ;;
    "$HOST_PWD")   CONTAINER_PATH="/data" ;;
    *)
      if [ -d "$host_path" ]; then
        MOUNTS+=(-v "$host_path:$mount_point")
        DISPLAY_MAP="$DISPLAY_MAP"$'\n'"$mount_point=$host_path"
        CONTAINER_PATH="$mount_point"
      else
        dir="$(dirname -- "$host_path")"; base="$(basename -- "$host_path")"
        MOUNTS+=(-v "$dir:$mount_point")
        DISPLAY_MAP="$DISPLAY_MAP"$'\n'"$mount_point=$dir"
        CONTAINER_PATH="$mount_point/$base"
      fi ;;
  esac
}

to_container_path "$INPUT_ABS" /input
CONTAINER_INPUT="$CONTAINER_PATH"

ARGS=(--input "$CONTAINER_INPUT")
if [ -n "$OUTPUT" ]; then
  # La cartella di destinazione deve esistere per poterla montare.
  if [ "${OUTPUT: -1}" = "/" ] || [ -d "$OUTPUT" ]; then
    mkdir -p -- "$OUTPUT"
  else
    mkdir -p -- "$(dirname -- "$OUTPUT")"
  fi
  OUTPUT_ABS="$(abspath "$OUTPUT")"
  to_container_path "$OUTPUT_ABS" /output
  ARGS+=(--output "$CONTAINER_PATH")
fi

# Una o piu' cartelle di template, separate da ':' come IMPAGINA_TEMPLATES_PATH
# nel container. La prima si monta su /templates, le altre su /templates-2,
# /templates-3, ...; il tool le cerca nello stesso ordine, prima dei template
# inclusi nell'immagine.
PUNTI_TEMPLATE=()
IFS=':' read -r -a CARTELLE_TEMPLATE <<< "$TEMPLATES_DIR"
for cartella in ${CARTELLE_TEMPLATE[@]+"${CARTELLE_TEMPLATE[@]}"}; do
  [ -n "$cartella" ] || continue
  if [ ! -d "$cartella" ]; then
    # La cartella predefinita accanto allo script puo' mancare (i template
    # inclusi bastano); una indicata esplicitamente no.
    if [ -n "${IMPAGINA_TEMPLATES_DIR:-}" ]; then
      printf 'Attenzione: cartella dei template inesistente: %s\n' "$cartella" >&2
    fi
    continue
  fi
  if [ "${#PUNTI_TEMPLATE[@]}" -eq 0 ]; then
    punto=/templates
  else
    punto="/templates-$(( ${#PUNTI_TEMPLATE[@]} + 1 ))"
  fi
  cartella="$(cd -- "$cartella" && pwd -P)"
  MOUNTS+=(-v "$cartella:$punto:ro")
  DISPLAY_MAP="$DISPLAY_MAP"$'\n'"$punto=$cartella"
  PUNTI_TEMPLATE+=("$punto")
done
AMBIENTE=()
if [ "${#PUNTI_TEMPLATE[@]}" -gt 1 ]; then
  AMBIENTE+=(-e "IMPAGINA_TEMPLATES_PATH=$(IFS=:; printf '%s' "${PUNTI_TEMPLATE[*]}")")
fi

# --network=none: la conversione e' interamente locale, il container non ha
# alcun motivo di accedere alla rete.
exec docker run --rm \
  --network=none \
  --user "$(id -u):$(id -g)" \
  -e IMPAGINA_DISPLAY_MAP="$DISPLAY_MAP" \
  ${AMBIENTE[@]+"${AMBIENTE[@]}"} \
  "${MOUNTS[@]}" \
  "$IMAGE" \
  "${ARGS[@]}" ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
