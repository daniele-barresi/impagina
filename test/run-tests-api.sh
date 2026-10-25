#!/usr/bin/env bash
#
# Suite di verifica del servizio API di impagina.
#
#   docker build --target api -t impagina-api .
#   ./test/run-tests-api.sh
#
# Avvia container di prova su porte casuali di 127.0.0.1, con chiavi e limiti
# propri, e li rimuove alla fine. Richiede sull'host: docker, curl, python3 e
# poppler-utils (pdfinfo, pdftotext), come la suite della CLI.

set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
WORK="$(mktemp -d)"
IMAGE="${IMPAGINA_API_IMAGE:-impagina-api}"
CONTAINER="impagina-api-test-$$"
LENTO="impagina-api-lento-$$"

pulizia() {
  docker rm -f "$CONTAINER" "$LENTO" >/dev/null 2>&1
  rm -rf "$WORK"
}
trap pulizia EXIT

# shellcheck source=lib-verifica.sh
source "$ROOT/test/lib-verifica.sh"

for strumento in docker curl python3 pdfinfo pdftotext; do
  command -v "$strumento" >/dev/null 2>&1 || {
    printf 'Errore: manca %s.\n' "$strumento" >&2; exit 1; }
done
docker image inspect "$IMAGE" >/dev/null 2>&1 || {
  printf 'Errore: immagine %s assente. Esegui: docker build --target api -t %s "%s"\n' \
    "$IMAGE" "$IMAGE" "$ROOT" >&2; exit 1; }

# Come nella suite della CLI: template su filesystem locale (mmap dei font).
cp -r "$ROOT/templates" "$WORK/templates"
# Template esterni, montati a parte come farebbe chi installa un template
# aziendale: uno valido e uno di un formato che questa versione non conosce.
mkdir -p "$WORK/esterni"
cp -r "$ROOT/test/fixtures/templates/minimo" "$WORK/esterni/minimo"
sed -i 's/^mainfont:.*/mainfont: "Inter"/' "$WORK/esterni/minimo/theme.yaml"
cp -r "$WORK/esterni/minimo" "$WORK/esterni/rotto"
sed -i 's/^impagina-format:.*/impagina-format: 99/' "$WORK/esterni/rotto/theme.yaml"
chmod -R a+rX "$WORK/templates" "$WORK/esterni"

# --- chiavi di prova ------------------------------------------------------
TOKEN="imp_prova_$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
ALTRO="imp_altra_$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
impronta() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
mkdir -m 755 "$WORK/config"
scrivi_chiavi() {  # scrivi_chiavi <righe>: riscrittura atomica, come impagina.sh
  printf '%s' "$1" > "$WORK/config/chiavi.nuovo"
  chmod 644 "$WORK/config/chiavi.nuovo"
  mv -f "$WORK/config/chiavi.nuovo" "$WORK/config/chiavi.conf"
}
scrivi_chiavi "prova sha256:$(impronta "$TOKEN")
altra sha256:$(impronta "$ALTRO")
"

# --- avvio dei container --------------------------------------------------
# Stesse restrizioni di compose.yaml: sola lettura, nessuna capability.
avvia() {  # avvia <nome> [-e VAR=valore ...]
  local nome="$1"; shift
  docker run -d --name "$nome" --init --read-only --tmpfs /tmp:size=64m \
    --cap-drop ALL --security-opt no-new-privileges:true \
    -p 127.0.0.1::8080 \
    -v "$WORK/config:/etc/impagina:ro" -v "$WORK/templates:/templates:ro" \
    "$@" "$IMAGE" >/dev/null || return 1
  local porta i
  porta="$(docker port "$nome" 8080 | head -1 | sed 's/.*://')"
  for i in $(seq 1 50); do
    curl -sf "http://127.0.0.1:$porta/salute" >/dev/null 2>&1 && { echo "$porta"; return 0; }
    sleep 0.2
  done
  docker logs "$nome" >&2
  return 1
}

# --- richieste --------------------------------------------------------------
# api <metodo> <percorso> [argomenti curl...]: corpo in $WORK/corpo,
# intestazioni in $WORK/intestazioni, codice HTTP in $CODICE.
URL=""
AUTH=(-H "Authorization: Bearer $TOKEN")
CORPI="$WORK/tutti-i-corpi"
api() {
  local metodo="$1" percorso="$2"; shift 2
  CODICE="$(curl -sS -X "$metodo" -o "$WORK/corpo" -D "$WORK/intestazioni" \
            -w '%{http_code}' "$@" "$URL$percorso")"
  cat "$WORK/corpo" >> "$CORPI" 2>/dev/null
  printf '\n' >> "$CORPI"
}

# json <espressione Python su d>: legge $WORK/corpo (o il file indicato).
json() {
  python3 -c "import json,sys; d=json.load(open(sys.argv[2])); print(eval(sys.argv[1]))" \
    "$1" "${2:-$WORK/corpo}" 2>/dev/null
}

intestazione() { grep -i "^$1:" "$WORK/intestazioni" | head -1 | cut -d' ' -f2- | tr -d '\r'; }

# attendi_lavoro <id> [token]: aspetta che il lavoro esca dalla coda.
attendi_lavoro() {
  local id="$1" token="${2:-$TOKEN}" i stato
  for i in $(seq 1 120); do
    api GET "/lavori/$id" -H "Authorization: Bearer $token"
    stato="$(json 'd["stato"]')"
    case "$stato" in in_coda|in_corso) sleep 0.5 ;; *) return 0 ;; esac
  done
  return 1
}

# invia_md <file.md> [argomenti curl...]: nuovo lavoro multipart, id in $ID.
invia_md() {
  local file="$1"; shift
  api POST /lavori "${AUTH[@]}" -F "documento=@$file" "$@"
  ID="$(json 'd["id"]')"
}

# zip_da <archivio> <cartella>: comprime la cartella (con la cartella stessa
# come radice, come fa "comprimi" nei file manager).
zip_da() {
  python3 - "$1" "$2" <<'PY'
import os, sys, zipfile
archivio, cartella = sys.argv[1], sys.argv[2]
base = os.path.dirname(os.path.abspath(cartella))
with zipfile.ZipFile(archivio, "w", zipfile.ZIP_DEFLATED) as zf:
    for radice, _, file in os.walk(cartella):
        for nome in file:
            percorso = os.path.join(radice, nome)
            zf.write(percorso, os.path.relpath(percorso, base))
PY
}

invia_zip() {  # invia_zip <archivio> [query]
  api POST "/lavori${2:+?$2}" "${AUTH[@]}" -H "Content-Type: application/zip" \
    --data-binary "@$1"
  ID="$(json 'd.get("id", "")')"
}

ESEMPIO="$ROOT/examples/esempio.md"
IMMAGINE="$ROOT/examples/immagini/diagramma.svg"
ALLEGATO=(-F "allegato=@$IMMAGINE;filename=immagini/diagramma.svg")

PORTA="$(avvia "$CONTAINER" -e IMPAGINA_API_MAX_CORPO=2M -e IMPAGINA_API_MAX_FILE=5 \
          -e IMPAGINA_API_MAX_ESPANSO=5M \
          -v "$WORK/esterni:/opt/template-esterni:ro" \
          -e IMPAGINA_TEMPLATES_PATH=/templates:/opt/template-esterni)" || {
  printf 'Errore: il servizio di prova non si avvia.\n' >&2; exit 1; }
URL="http://127.0.0.1:$PORTA"

# ---------------------------------------------------------------------------
capitolo "1. Avvio"
api GET /salute
verifica "/salute risponde 200 senza autenticazione" "200" "$CODICE"
versione_cli="$(docker run --rm --network=none --entrypoint python3 "$IMAGE" \
                /opt/impagina/impagina.py --version | awk '{print $2}')"
verifica "la versione coincide con quella della CLI" "$versione_cli" "$(json 'd["versione"]')"
verifica "un solo worker per default" "1" "$(json 'd["worker"]')"
verifica "il servizio non gira come root" "10001" "$(docker exec "$CONTAINER" id -u)"
api GET /openapi.yaml
verifica "/openapi.yaml risponde 200 senza autenticazione" "200" "$CODICE"
verifica "il descrittore riporta la versione del servizio" "$versione_cli" \
  "$(sed -n 's/^  version: *//p' "$WORK/corpo" | head -1)"
python3 - "$WORK/corpo" "$ROOT/src/impagina_api/server.py" > "$WORK/rotte.txt" <<'PY'
# Ogni rotta del server deve comparire nel descrittore, e viceversa.
import re, sys
descrittore = set(re.findall(r"^  (/[^:]*):$", open(sys.argv[1]).read(), re.M))
server = set()
for schema in re.findall(r're\.compile\(r"\^(/[^"]*)\$"\)', open(sys.argv[2]).read()):
    server.add(schema.replace("([^/]+)", "{id}").replace("\\.", "."))
print("ok" if descrittore == server else "differenze: %s" % sorted(descrittore ^ server))
PY
verifica "il descrittore documenta tutte e sole le rotte del server" "ok" "$(cat "$WORK/rotte.txt")"
docker logs "$CONTAINER" > "$WORK/log-avvio.txt" 2>&1
contiene "all'avvio il log elenca i template e la loro directory" "$WORK/log-avvio.txt" \
  "template disponibili: company (/templates), minimo (/opt/template-esterni)"
contiene "all'avvio il log segnala i template non validi" "$WORK/log-avvio.txt" \
  "template 'rotto' in /opt/template-esterni non valido, escluso: formato '99'"

# ---------------------------------------------------------------------------
capitolo "2. Autenticazione"
api GET /template
verifica "senza token: 401" "401" "$CODICE"
contiene "401 con WWW-Authenticate: Bearer" "$WORK/intestazioni" 'WWW-Authenticate: Bearer'
api GET /template -H "Authorization: Bearer imp_sbagliato"
verifica "token errato: 401" "401" "$CODICE"
api GET /template -H "Authorization: Basic $TOKEN"
verifica "schema diverso da Bearer: 401" "401" "$CODICE"
api GET /template "${AUTH[@]}"
verifica "token valido: 200" "200" "$CODICE"
verifica "elenca i template, anche quelli esterni" "['company', 'minimo']" "$(json 'd["template"]')"

scrivi_chiavi "prova sha256:$(impronta "$TOKEN")
# revocata altra sha256:$(impronta "$ALTRO")
"
api GET /template -H "Authorization: Bearer $ALTRO"
verifica "chiave revocata: 401 senza riavvio" "401" "$CODICE"
api GET /template "${AUTH[@]}"
verifica "le altre chiavi restano valide" "200" "$CODICE"
scrivi_chiavi "prova sha256:$(impronta "$TOKEN")
altra sha256:$(impronta "$ALTRO")
"
docker logs "$CONTAINER" > "$WORK/log.txt" 2>&1
contiene "i log riportano il nome della chiave" "$WORK/log.txt" "chiave=prova"
if grep -qF -- "$TOKEN" "$WORK/log.txt" || grep -qF -- "imp_sbagliato" "$WORK/log.txt"; then
  ko "i log non contengono mai i token"
else ok "i log non contengono mai i token"; fi

# ---------------------------------------------------------------------------
capitolo "3. Dipendenze di un documento"
api POST /dipendenze "${AUTH[@]}" -H "Content-Type: text/markdown" --data-binary "@$ESEMPIO"
verifica "risponde 200" "200" "$CODICE"
verifica "trova l'immagine dell'esempio" "immagini/diagramma.svg" "$(json 'd["file"][0]["percorso"]')"
verifica "da allegare" "da_allegare" "$(json 'd["file"][0]["stato"]')"
api POST /dipendenze "${AUTH[@]}" -F "documento=@$ESEMPIO" "${ALLEGATO[@]}"
verifica "con l'allegato: gia' allegato" "allegato" "$(json 'd["file"][0]["stato"]')"
printf '![a](https://example.com/a.png)\n\n![b](../fuori.png)\n\n![c](./img/c.png)\n' > "$WORK/dip.md"
api POST /dipendenze "${AUTH[@]}" -H "Content-Type: text/markdown" --data-binary "@$WORK/dip.md"
verifica "i riferimenti remoti ed esterni sono ignorati" "['remoto', 'esterno']" \
  "$(json '[x["stato"] for x in d["ignorati"]]')"
verifica "i percorsi sono normalizzati" "img/c.png" "$(json 'd["file"][0]["percorso"]')"
printf -- '---\ntitle: [non chiuso\n---\ntesto\n' > "$WORK/rotto.md"
api POST /dipendenze "${AUTH[@]}" -H "Content-Type: text/markdown" --data-binary "@$WORK/rotto.md"
verifica "front-matter rotto: 422" "422" "$CODICE"
verifica "codice front_matter_non_valido" "front_matter_non_valido" "$(json 'd["errore"]["codice"]')"

# ---------------------------------------------------------------------------
capitolo "4. Un documento con la sua immagine (multipart)"
invia_md "$ESEMPIO" "${ALLEGATO[@]}"
verifica "l'invio risponde 202" "202" "$CODICE"
verifica "Location punta al lavoro" "/lavori/$ID" "$(intestazione Location)"
verifica "il lavoro parte in coda" "in_coda" "$(json 'd["stato"]')"
attendi_lavoro "$ID"
verifica "il lavoro si completa" "completato ok" "$(json 'd["stato"] + " " + d["esito"]')"
verifica "il documento compare nell'esito" "esempio.md -> esempio.pdf" \
  "$(json 'd["documenti"][0]["sorgente"] + " -> " + d["documenti"][0]["pdf"]')"
api GET "/lavori/$ID/risultato" "${AUTH[@]}"
cp "$WORK/corpo" "$WORK/esempio.pdf"
verifica "il risultato e' un PDF" "application/pdf" "$(intestazione Content-Type)"
contiene "con il nome del documento" "$WORK/intestazioni" 'filename="esempio.pdf"'
verifica "di 3 pagine, come con la CLI" "3" "$(pdfinfo "$WORK/esempio.pdf" 2>/dev/null | awk '/^Pages:/ {print $2}')"
pdftotext "$WORK/esempio.pdf" "$WORK/esempio.txt" 2>/dev/null
contiene "con il testo del documento" "$WORK/esempio.txt" "Relazione trimestrale"

# ---------------------------------------------------------------------------
capitolo "5. Opzioni"
invia_md "$ESEMPIO" "${ALLEGATO[@]}" -F toc=true
attendi_lavoro "$ID"
api GET "/lavori/$ID/risultato" "${AUTH[@]}"; cp "$WORK/corpo" "$WORK/opzioni.pdf"
pdftotext "$WORK/opzioni.pdf" "$WORK/opzioni.txt" 2>/dev/null
contiene "toc=true genera l'indice" "$WORK/opzioni.txt" "Indice"
invia_md "$ESEMPIO" "${ALLEGATO[@]}" -F template=minimo
attendi_lavoro "$ID"
api GET "/lavori/$ID/risultato" "${AUTH[@]}"; cp "$WORK/corpo" "$WORK/esterno.pdf"
pdftotext "$WORK/esterno.pdf" "$WORK/esterno.txt" 2>/dev/null
contiene "template=minimo applica il template esterno" "$WORK/esterno.txt" "Template minimo"
invia_md "$ESEMPIO" -F template=rotto
verifica "un template non valido non si puo' scegliere: 422" "422 template_non_trovato" \
  "$CODICE $(json 'd["errore"]["codice"]')"
invia_md "$ESEMPIO" "${ALLEGATO[@]}" -F cover=false
attendi_lavoro "$ID"
api GET "/lavori/$ID/risultato" "${AUTH[@]}"; cp "$WORK/corpo" "$WORK/senza-copertina.pdf"
verifica "cover=false toglie la pagina di copertina" "2" \
  "$(pdfinfo "$WORK/senza-copertina.pdf" 2>/dev/null | awk '/^Pages:/ {print $2}')"
invia_md "$ESEMPIO" "${ALLEGATO[@]}" -F "watermark=--templates-dir=/"
attendi_lavoro "$ID"
verifica "un watermark che sembra un'opzione resta testo" "completato --templates-dir=/" \
  "$(json 'd["stato"] + " " + d["opzioni"]["watermark"]')"
invia_md "$ESEMPIO" -F "allegato[0]=@$IMMAGINE;filename=immagini/diagramma.svg"
attendi_lavoro "$ID"
verifica "gli allegati come allegato[0] (PHP) valgono come allegato" "completato" "$(json 'd["stato"]')"
api POST "/lavori?template=minimo" "${AUTH[@]}" -F "documento=@$ESEMPIO" "${ALLEGATO[@]}"
ID="$(json 'd["id"]')"; attendi_lavoro "$ID"
verifica "le opzioni valgono anche in query string" "minimo" "$(json 'd["opzioni"]["template"]')"

# ---------------------------------------------------------------------------
capitolo "6. Cartella in uno ZIP"
mkdir -p "$WORK/note/immagini" "$WORK/note/capitoli"
cp "$ESEMPIO" "$WORK/note/"; cp "$IMMAGINE" "$WORK/note/immagini/"
printf -- '---\ntitle: Secondo\n---\n# Due\n\ntesto\n' > "$WORK/note/capitoli/due.md"
zip_da "$WORK/note.zip" "$WORK/note"
invia_zip "$WORK/note.zip" "recursive=true"
verifica "l'invio dello ZIP risponde 202" "202" "$CODICE"
attendi_lavoro "$ID"
verifica "due documenti convertiti" "2" "$(json 'len(d["documenti"])')"
api GET "/lavori/$ID/risultato" "${AUTH[@]}"; cp "$WORK/corpo" "$WORK/risultato.zip"
verifica "con piu' PDF il risultato e' uno ZIP" "application/zip" "$(intestazione Content-Type)"
verifica "che replica la struttura delle cartelle" "['capitoli/due.pdf', 'esempio.pdf']" \
  "$(python3 -c 'import sys,zipfile; print(sorted(zipfile.ZipFile(sys.argv[1]).namelist()))' "$WORK/risultato.zip")"
invia_zip "$WORK/note.zip"
attendi_lavoro "$ID"
verifica "senza recursive: solo il primo livello, e un solo PDF" "1 application/pdf" \
  "$(json 'str(len(d["documenti"])) + " " + d["risultato"]["tipo"]')"
mkdir -p "$WORK/solo-sotto/a"; printf '# x\n' > "$WORK/solo-sotto/a/x.md"
zip_da "$WORK/solo-sotto.zip" "$WORK/solo-sotto/a/.."
invia_zip "$WORK/solo-sotto.zip"
verifica "md solo nelle sottocartelle, senza recursive: 422" "422" "$CODICE"
contiene "con il suggerimento di usare recursive" "$WORK/corpo" "recursive=true"
invia_md "$ESEMPIO" -F recursive=true
verifica "recursive con multipart: 400" "400 opzione_non_valida" "$CODICE $(json 'd["errore"]["codice"]')"

# ---------------------------------------------------------------------------
capitolo "7. Errori"
invia_md "$ESEMPIO" -F template=inesistente
verifica "template inesistente: 422" "422 template_non_trovato" "$CODICE $(json 'd["errore"]["codice"]')"
contiene "con l'elenco dei template" "$WORK/corpo" "company, minimo"
invia_md "$WORK/rotto.md"
attendi_lavoro "$ID"
verifica "front-matter rotto: lavoro fallito con codice 4" "fallito 4" \
  "$(json 'd["stato"] + " " + str(d["documenti"][0]["codice_uscita"])')"
api GET "/lavori/$ID/risultato" "${AUTH[@]}"
verifica "e il risultato risponde 422" "422 front_matter_non_valido" "$CODICE $(json 'd["errore"]["codice"]')"
invia_md "$ESEMPIO"
attendi_lavoro "$ID"
verifica "immagine non allegata: conversione fallita" "conversione_fallita" "$(json 'd["errore"]["codice"]')"
contiene "il messaggio indica l'immagine" "$WORK/corpo" "immagini/diagramma.svg"
if grep -qF "/var/lib/impagina-api" "$WORK/corpo"; then
  ko "i messaggi non mostrano i percorsi del server"
else ok "i messaggi non mostrano i percorsi del server"; fi
api POST /lavori "${AUTH[@]}" -H "Content-Type: text/plain" --data "ciao"
verifica "tipo non supportato: 415" "415" "$CODICE"
api POST /lavori "${AUTH[@]}" -H "Transfer-Encoding: chunked" -F "documento=@$ESEMPIO"
verifica "corpo chunked: 411" "411" "$CODICE"
head -c $((3 * 1024 * 1024)) /dev/zero > "$WORK/grande.bin"
invia_md "$ESEMPIO" -F "allegato=@$WORK/grande.bin;filename=grande.bin"
verifica "corpo oltre il limite: 413" "413 troppo_grande" "$CODICE $(json 'd["errore"]["codice"]')"
troppi=()
for n in 1 2 3 4 5; do troppi+=(-F "allegato=@$IMMAGINE;filename=img/$n.svg"); done
invia_md "$ESEMPIO" "${troppi[@]}"
verifica "troppi file: 413" "413 troppi_file" "$CODICE $(json 'd["errore"]["codice"]')"
invia_md "$ESEMPIO" -F colore=rosso
verifica "opzione sconosciuta: 400" "400 opzione_non_valida" "$CODICE $(json 'd["errore"]["codice"]')"
api POST /lavori "${AUTH[@]}" -F "allegato=@$IMMAGINE"
verifica "senza documento: 400" "400" "$CODICE"
api GET /lavori/0123456789abcdef0123456789abcdef "${AUTH[@]}"
verifica "lavoro inesistente: 404" "404" "$CODICE"
api PUT /lavori "${AUTH[@]}"
verifica "metodo non consentito: 405 con Allow" "405 POST" "$CODICE $(intestazione Allow)"
if grep -q "Traceback" "$CORPI"; then ko "nessuna risposta contiene uno stack trace"
else ok "nessuna risposta contiene uno stack trace"; fi

# ---------------------------------------------------------------------------
capitolo "8. Sicurezza"
crea_zip() {  # crea_zip <archivio> <nome-voce> [symlink]
  python3 - "$@" <<'PY'
import stat, sys, zipfile
archivio, voce = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(archivio, "w") as zf:
    zf.writestr("doc.md", "# ok\n")
    if len(sys.argv) > 3:
        info = zipfile.ZipInfo(voce)
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc")
    else:
        zf.writestr(voce, "# fuori\n")
PY
}
for voce in "../evaso.md" "/evaso.md" "a/../../evaso.md"; do
  crea_zip "$WORK/slip.zip" "$voce"
  invia_zip "$WORK/slip.zip"
  verifica "voce ZIP '$voce': 400" "400 percorso_non_valido" "$CODICE $(json 'd["errore"]["codice"]')"
done
crea_zip "$WORK/link.zip" "link" symlink
invia_zip "$WORK/link.zip"
verifica "collegamento simbolico nello ZIP: 400" "400" "$CODICE"
if docker exec "$CONTAINER" find / -xdev -name 'evaso.md' 2>/dev/null | grep -q .; then
  ko "nessun file scritto fuori dalla cartella del lavoro"
else ok "nessun file scritto fuori dalla cartella del lavoro"; fi
python3 -c "
import zipfile
with zipfile.ZipFile('$WORK/bomba.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('doc.md', '# x\n'); zf.writestr('zeri.md', b'\0' * 20 * 1024 * 1024)"
invia_zip "$WORK/bomba.zip"
verifica "zip bomb (pochi KB che diventano 20 MB): 413" "413 troppo_grande" "$CODICE $(json 'd["errore"]["codice"]')"
invia_md "$ESEMPIO" -F "allegato=@$IMMAGINE;filename=../../evaso.svg"
verifica "allegato con '..' nel nome: 400" "400 percorso_non_valido" "$CODICE $(json 'd["errore"]["codice"]')"
invia_md "$ESEMPIO" -F "template=../company"
verifica "template con '..': 400" "400" "$CODICE"

printf '# A\n\n```{=typst}\n#read("/etc/hostname")\n```\n' > "$WORK/grezzo.md"
invia_md "$WORK/grezzo.md"; attendi_lavoro "$ID"
verifica "Typst grezzo: rifiutato" "fallito conversione_fallita" "$(json 'd["stato"] + " " + d["errore"]["codice"]')"
contiene "con un messaggio chiaro" "$WORK/corpo" "Typst grezzo"
printf -- '---\nfontsize: "11pt, fill: red"\n---\nx\n' > "$WORK/metadato.md"
invia_md "$WORK/metadato.md"; attendi_lavoro "$ID"
verifica "codice Typst in un metadato: rifiutato" "fallito" "$(json 'd["stato"]')"
printf '![x](/opt/impagina/templates/company/assets/logo.svg)\n' > "$WORK/assoluta.md"
invia_md "$WORK/assoluta.md"; attendi_lavoro "$ID"
verifica "immagine con percorso assoluto: rifiutata" "fallito" "$(json 'd["stato"]')"
printf -- '---\ntitle: Il "progetto" alfa\n---\n# Uno\n' > "$WORK/virgolette.md"
invia_md "$WORK/virgolette.md"; attendi_lavoro "$ID"
verifica "un titolo con le virgolette invece funziona" "completato" "$(json 'd["stato"]')"
invia_md "$ESEMPIO" "${ALLEGATO[@]}"; attendi_lavoro "$ID"
api GET "/lavori/$ID" -H "Authorization: Bearer $ALTRO"
verifica "il lavoro di una chiave non e' visibile a un'altra" "404" "$CODICE"
api GET "/lavori/$ID/risultato" -H "Authorization: Bearer $ALTRO"
verifica "ne' il suo risultato" "404" "$CODICE"
api DELETE "/lavori/$ID" -H "Authorization: Bearer $ALTRO"
verifica "ne' si puo' eliminare" "404" "$CODICE"

# ---------------------------------------------------------------------------
capitolo "9. Eliminazione e riavvio"
invia_md "$ESEMPIO" "${ALLEGATO[@]}"; attendi_lavoro "$ID"
api DELETE "/lavori/$ID" "${AUTH[@]}"
verifica "DELETE risponde 204" "204" "$CODICE"
api GET "/lavori/$ID" "${AUTH[@]}"
verifica "poi il lavoro non esiste piu'" "404" "$CODICE"
if docker exec "$CONTAINER" test -e "/var/lib/impagina-api/lavori/$ID"; then
  ko "e la sua cartella e' stata rimossa"
else ok "e la sua cartella e' stata rimossa"; fi
invia_md "$ESEMPIO" "${ALLEGATO[@]}"; attendi_lavoro "$ID"
if docker exec "$CONTAINER" test -e "/var/lib/impagina-api/lavori/$ID/sorgente"; then
  ko "a lavoro finito i sorgenti vengono cancellati"
else ok "a lavoro finito i sorgenti vengono cancellati"; fi
docker restart "$CONTAINER" >/dev/null
PORTA="$(docker port "$CONTAINER" 8080 | head -1 | sed 's/.*://')"; URL="http://127.0.0.1:$PORTA"
for i in $(seq 1 50); do curl -sf "$URL/salute" >/dev/null 2>&1 && break; sleep 0.2; done
api GET "/lavori/$ID/risultato" "${AUTH[@]}"
verifica "dopo un riavvio il risultato e' ancora scaricabile" "200 application/pdf" \
  "$CODICE $(intestazione Content-Type)"

# ---------------------------------------------------------------------------
capitolo "10. Coda, timeout e scadenza (secondo servizio, lento di proposito)"
# Typst grezzo ammesso solo qui, per costruire un documento che non finisce.
PORTA_LENTO="$(avvia "$LENTO" -e IMPAGINA_API_TYPST_GREZZO=1 -e IMPAGINA_API_TIMEOUT=3 \
  -e IMPAGINA_API_CODA_MAX=2 -e IMPAGINA_API_TTL=3 -e IMPAGINA_API_PULIZIA_OGNI=1)"
URL="http://127.0.0.1:$PORTA_LENTO"
printf '# Lento\n\n```{=typst}\n#for i in range(100000) { for j in range(100000) { } }\n```\n' \
  > "$WORK/lento.md"
invia_md "$WORK/lento.md"; PRIMO="$ID"
for i in $(seq 1 20); do
  api GET "/lavori/$PRIMO" "${AUTH[@]}"; [ "$(json 'd["stato"]')" = "in_corso" ] && break; sleep 0.2
done
invia_md "$WORK/lento.md"; SECONDO="$ID"
verifica "il secondo lavoro attende in posizione 1" "1" "$(json 'd["posizione_in_coda"]')"
invia_md "$WORK/lento.md"; TERZO="$ID"
verifica "il terzo in posizione 2" "2" "$(json 'd["posizione_in_coda"]')"
invia_md "$WORK/lento.md"
verifica "con la coda piena: 503 con Retry-After" "503 coda_piena 30" \
  "$CODICE $(json 'd["errore"]["codice"]') $(intestazione Retry-After)"
api GET /salute
verifica "una conversione alla volta" "1" "$(json 'd["in_corso"]')"
api DELETE "/lavori/$TERZO" "${AUTH[@]}"
verifica "un lavoro in coda si puo' togliere" "204" "$CODICE"
api DELETE "/lavori/$PRIMO" "${AUTH[@]}"
verifica "uno in corso no: 409" "409" "$CODICE"
attendi_lavoro "$PRIMO"
verifica "oltre il timeout il lavoro viene interrotto" "fallito tempo_scaduto" \
  "$(json 'd["stato"] + " " + d["errore"]["codice"]')"
sleep 1
if docker exec "$LENTO" sh -c 'cat /proc/[0-9]*/comm' 2>/dev/null | grep -qx typst; then
  # Il secondo lavoro puo' essere gia' partito: conta solo typst in piu'.
  n="$(docker exec "$LENTO" sh -c 'cat /proc/[0-9]*/comm' | grep -cx typst)"
  verifica "nessun processo typst orfano" "1" "$n"
else ok "nessun processo typst orfano"; fi
attendi_lavoro "$SECONDO"
sleep 5
api GET "/lavori/$PRIMO" "${AUTH[@]}"
verifica "scaduto il TTL, il lavoro sparisce" "404" "$CODICE"
if docker exec "$LENTO" test -e "/var/lib/impagina-api/lavori/$PRIMO"; then
  ko "e la cartella viene rimossa"
else ok "e la cartella viene rimossa"; fi

# ---------------------------------------------------------------------------
capitolo "11. Consumo a riposo (informativo)"
# Con --init il PID 1 e' tini: il server e' l'unico processo python3.
rss="$(docker exec "$CONTAINER" sh -c 'for p in /proc/[0-9]*; do
  [ "$(cat $p/comm 2>/dev/null)" = python3 ] && grep VmRSS $p/status; done' | awk '{print $2}' | head -1)"
printf '  memoria del server a riposo: %s KB\n' "${rss:-?}"

riepilogo
