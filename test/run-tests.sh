#!/usr/bin/env bash
#
# Suite di verifica di impagina.
#
#   ./test/run-tests.sh
#
# Richiede: docker, l'immagine gia' costruita (docker build -t impagina .)
# poppler-utils sull'host (pdfinfo, pdftotext, pdffonts) e il font DejaVu Serif
# (fonts-dejavu-core, gia' presente quasi ovunque).
#   Ubuntu/ZorinOS:  sudo apt install poppler-utils fonts-dejavu-core

set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
WORK="$(mktemp -d)"
IMAGE="${IMPAGINA_IMAGE:-impagina}"
trap 'rm -rf "$WORK"' EXIT

# shellcheck source=lib-verifica.sh
source "$ROOT/test/lib-verifica.sh"

for strumento in docker pdfinfo pdftotext pdffonts; do
  command -v "$strumento" >/dev/null 2>&1 || {
    printf 'Errore: manca %s.\n' "$strumento" >&2; exit 1; }
done
docker image inspect "$IMAGE" >/dev/null 2>&1 || {
  printf 'Errore: immagine %s assente. Esegui: docker build -t %s "%s"\n' \
    "$IMAGE" "$IMAGE" "$ROOT" >&2; exit 1; }

# I template vengono copiati su filesystem locale prima dei test: Typst mappa
# in memoria i file dei font e su alcuni filesystem condivisi (virtiofs, 9p,
# certe reti) la mmap fallisce in silenzio, facendo sembrare assenti font che
# ci sono. La copia rende la suite indipendente da dove vive il repository.
cp -r "$ROOT/templates" "$WORK/templates"
TEMPLATES="$WORK/templates"

# Esegue il tool nel container. Stampa stdout+stderr, restituisce l'exit code.
impagina() {
  docker run --rm --network=none \
    --user "$(id -u):$(id -g)" \
    -v "$ROOT:/data:ro" \
    -v "$TEMPLATES:/templates:ro" \
    -v "$WORK:/out" \
    "$IMAGE" "$@" 2>&1
}

ESEMPIO=/data/examples/esempio.md

# ---------------------------------------------------------------------------
capitolo "1. Conversione di base (template company, copertina)"
uscita="$(impagina -i "$ESEMPIO" -o /out/base.pdf -t company)"; codice=$?
verifica "esce con 0" "0" "$codice"
if [ -f "$WORK/base.pdf" ]; then ok "il PDF viene creato"; else ko "il PDF viene creato"; fi

pdfinfo "$WORK/base.pdf" > "$WORK/info.txt" 2>/dev/null
pagine="$(awk '/^Pages:/ {print $2}' "$WORK/info.txt")"
verifica "il documento ha 3 pagine" "3" "$pagine"

formato="$(awk '/^Page size:/ {print $NF}' "$WORK/info.txt")"
verifica "formato pagina A4" "(A4)" "$formato"
contiene "il titolo del front-matter finisce nei metadati del PDF" \
  "$WORK/info.txt" "Relazione trimestrale"

pdftotext "$WORK/base.pdf" "$WORK/base.txt"
contiene "il pie' di pagina compare nel documento" "$WORK/base.txt" "Acme S.r.l."
if grep -qE '1 ?/ ?2' "$WORK/base.txt"; then
  ok "la numerazione e' nel formato n / totale"
else
  ko "la numerazione e' nel formato n / totale"
fi
contiene "il blocco di codice e' presente"           "$WORK/base.txt" "verifica_nodo"
contiene "la tabella e' presente"                    "$WORK/base.txt" "99,82"
contiene "la nota a pie' di pagina e' presente"      "$WORK/base.txt" "continuita-operativa"

# La sillabazione spezza le parole a fine riga: poppler estrae il trattino
# inserito da Typst come soft hyphen (U+00AD).
if grep -q "$(printf '\xc2\xad')" "$WORK/base.txt"; then
  ok "la sillabazione italiana e' attiva"
else
  ko "la sillabazione italiana e' attiva"
fi

# ---------------------------------------------------------------------------
capitolo "2. Font incorporati"
pdffonts "$WORK/base.pdf" > "$WORK/fonts.txt"
contiene "Inter e' incorporato"          "$WORK/fonts.txt" "Inter-Regular"
contiene "JetBrains Mono e' incorporato" "$WORK/fonts.txt" "JetBrainsMono"
if awk 'NR>2 && $0 != "" {print $(NF-3)}' "$WORK/fonts.txt" | grep -q "no"; then
  ko "tutti i font sono incorporati (nessuna sostituzione)"
else
  ok "tutti i font sono incorporati (nessuna sostituzione)"
fi

# ---------------------------------------------------------------------------
capitolo "3. Opzioni: indice, copertina, filigrana"
impagina -i "$ESEMPIO" -o /out/toc.pdf -t company --no-cover --toc >/dev/null
pdftotext -f 1 -l 1 "$WORK/toc.pdf" "$WORK/toc.txt"
contiene "l'indice viene generato in prima pagina" "$WORK/toc.txt" "Indice"
contiene "le voci d'indice riportano il numero di pagina" "$WORK/toc.txt" "Dettaglio tecnico"

impagina -i "$ESEMPIO" -o /out/mark.pdf -t company --watermark "BOZZA" >/dev/null
pdftotext "$WORK/mark.pdf" "$WORK/mark.txt"
# La filigrana e' ruotata di -30 gradi: poppler non riesce a raggruppare in
# parole il testo inclinato e ne estrae le lettere una per riga. E' il
# comportamento normale di qualunque filigrana diagonale, quindi contiamo la
# prima lettera, che deve comparire esattamente una volta per pagina.
occorrenze="$(grep -c '^B$' "$WORK/mark.txt")"
attese="$(pdfinfo "$WORK/mark.pdf" 2>/dev/null | awk '/^Pages:/ {print $2}')"
verifica "la filigrana compare su ogni pagina" "$attese" "$occorrenze"
# Controllo: senza --watermark quella lettera isolata non deve esserci.
verifica "senza --watermark non c'e' nessuna filigrana" "0" \
  "$(grep -c '^B$' "$WORK/base.txt")"

senza="$(pdfinfo "$WORK/base.pdf" 2>/dev/null | awk '/^Pages:/ {print $2}')"
impagina -i "$ESEMPIO" -o /out/nocover.pdf -t company --no-cover >/dev/null
con="$(pdfinfo "$WORK/nocover.pdf" 2>/dev/null | awk '/^Pages:/ {print $2}')"
verifica "--no-cover elimina una pagina" "$((senza - 1))" "$con"

# ---------------------------------------------------------------------------
capitolo "4. Cartelle e modalita' ricorsiva"
mkdir -p "$WORK/src/liv1/liv2"
for f in "$WORK/src/a.md" "$WORK/src/liv1/b.md" "$WORK/src/liv1/liv2/c.md"; do
  printf -- '---\ntitle: Prova\n---\n\n# Prova\n\nTesto.\n' > "$f"
done
docker run --rm --network=none --user "$(id -u):$(id -g)" \
  -v "$TEMPLATES:/templates:ro" -v "$WORK:/out" "$IMAGE" \
  -i /out/src -o /out/pdf-piatto -t company >/dev/null 2>&1
verifica "senza --recursive converte solo il primo livello" "1" \
  "$(find "$WORK/pdf-piatto" -name '*.pdf' 2>/dev/null | wc -l | tr -d ' ')"

docker run --rm --network=none --user "$(id -u):$(id -g)" \
  -v "$TEMPLATES:/templates:ro" -v "$WORK:/out" "$IMAGE" \
  -i /out/src -o /out/pdf-albero -t company --recursive >/dev/null 2>&1
verifica "con --recursive converte tutti i livelli" "3" \
  "$(find "$WORK/pdf-albero" -name '*.pdf' 2>/dev/null | wc -l | tr -d ' ')"
if [ -f "$WORK/pdf-albero/liv1/liv2/c.pdf" ]; then
  ok "la struttura delle sottocartelle viene replicata"
else
  ko "la struttura delle sottocartelle viene replicata"
fi

# ---------------------------------------------------------------------------
capitolo "5. Gestione degli errori"
uscita="$(impagina -i /data/inesistente.md -o /out/x.pdf)"; codice=$?
verifica "input inesistente -> exit 2" "2" "$codice"
case "$uscita" in *Traceback*) ko "nessuno stack trace" ;; *) ok "nessuno stack trace" ;; esac
case "$uscita" in *"non trovata"*) ok "messaggio comprensibile" ;; *) ko "messaggio comprensibile: $uscita" ;; esac

uscita="$(impagina -i "$ESEMPIO" -o /out/x.pdf -t inesistente)"; codice=$?
verifica "template inesistente -> exit 3" "3" "$codice"
case "$uscita" in *"Template disponibili"*) ok "elenca i template disponibili" ;;
                  *) ko "elenca i template disponibili: $uscita" ;; esac

printf -- '---\ntitle: "non chiusa\nlista: [a, b\n---\n\n# X\n' > "$WORK/rotto.md"
uscita="$(docker run --rm --network=none --user "$(id -u):$(id -g)" \
  -v "$TEMPLATES:/templates:ro" -v "$WORK:/out" "$IMAGE" \
  -i /out/rotto.md -o /out/rotto.pdf -t company 2>&1)"; codice=$?
verifica "front-matter non valido -> exit 4" "4" "$codice"
case "$uscita" in *Traceback*) ko "nessuno stack trace sul front-matter" ;;
                  *) ok "nessuno stack trace sul front-matter" ;; esac

mkdir -p "$WORK/vuota"
uscita="$(docker run --rm --network=none --user "$(id -u):$(id -g)" \
  -v "$TEMPLATES:/templates:ro" -v "$WORK:/out" "$IMAGE" \
  -i /out/vuota -t company 2>&1)"; codice=$?
verifica "cartella senza .md -> exit 0 con avviso" "0" "$codice"
case "$uscita" in *"nessun file .md"*) ok "avvisa che non ci sono file .md" ;;
                  *) ko "avvisa che non ci sono file .md" ;; esac

# Un documento rotto non deve impedire la conversione degli altri.
cp "$WORK/rotto.md" "$WORK/src/rotto.md"
uscita="$(docker run --rm --network=none --user "$(id -u):$(id -g)" \
  -v "$TEMPLATES:/templates:ro" -v "$WORK:/out" "$IMAGE" \
  -i /out/src -o /out/pdf-misto -t company --recursive 2>&1)"
case "$uscita" in *"3 convertiti, 1 falliti"*) ok "un file rotto non blocca gli altri" ;;
                  *) ko "un file rotto non blocca gli altri: $uscita" ;; esac
rm -f "$WORK/src/rotto.md"

# ---------------------------------------------------------------------------
capitolo "6. Proprieta' dei file prodotti"
# Con --user il PDF appartiene all'utente dell'host: senza, sarebbe di root
# e il client Nextcloud non potrebbe piu' sovrascriverlo.
verifica "il PDF appartiene all'utente corrente" "$(id -u)" \
  "$(stat -c '%u' "$WORK/base.pdf")"

# ---------------------------------------------------------------------------
capitolo "7. Personalizzazione del template senza ricostruire l'immagine"
immagine_prima="$(docker images -q "$IMAGE")"
cp -r "$TEMPLATES/company" "$WORK/tema-alternativo"
sed -i 's/^accent:.*/accent: "7A2E2E"/' "$WORK/tema-alternativo/theme.yaml"
sed -i 's/^footer-text:.*/footer-text: "Piede di pagina modificato"/' "$WORK/tema-alternativo/theme.yaml"
mkdir -p "$WORK/templates-alt"
mv "$WORK/tema-alternativo" "$WORK/templates-alt/company"
printf -- '---\ntitle: Senza piede proprio\n---\n\n# Titolo\n\nTesto.\n' > "$WORK/nofooter.md"
docker run --rm --network=none --user "$(id -u):$(id -g)" \
  -v "$WORK/templates-alt:/templates:ro" -v "$WORK:/out" "$IMAGE" \
  -i /out/nofooter.md -o /out/alt.pdf -t company >/dev/null 2>&1
pdftotext "$WORK/alt.pdf" "$WORK/alt.txt" 2>/dev/null
contiene "il theme.yaml modificato ha effetto" "$WORK/alt.txt" "Piede di pagina modificato"
verifica "l'immagine Docker non e' stata ricostruita" \
  "$immagine_prima" "$(docker images -q "$IMAGE")"

# ---------------------------------------------------------------------------
capitolo "8. Template inclusi nell'immagine (senza montare /templates)"
# L'immagine deve funzionare da sola: il montaggio di /templates serve solo a
# personalizzare i template senza ricostruirla.
uscita="$(docker run --rm --network=none --user "$(id -u):$(id -g)" \
  -v "$ROOT/examples:/in:ro" -v "$WORK:/out" "$IMAGE" \
  -i /in/esempio.md -o /out/builtin.pdf -t company 2>&1)"; codice=$?
verifica "converte senza volume dei template" "0" "$codice"
verifica "produce lo stesso numero di pagine" "3" \
  "$(pdfinfo "$WORK/builtin.pdf" 2>/dev/null | awk '/^Pages:/ {print $2}')"

uscita="$(docker run --rm --network=none "$IMAGE" --version 2>&1)"
case "$uscita" in impagina\ *) ok "--version risponde: $uscita" ;;
                  *) ko "--version risponde ($uscita)" ;; esac

# ---------------------------------------------------------------------------
capitolo "9. Template esterni (IMPAGINA_TEMPLATES_PATH)"
# Due directory esterne, come le monterebbe chi installa un template a parte:
#   esterni-a: minimo (font proprio in fonts/), rotto-formato, solo-tema,
#              .nascosto
#   esterni-b: un secondo "minimo", che non deve vincere
# Il font di minimo e' DejaVu Serif, che il container non ha fra i font di
# sistema: se compare nel PDF, impagina ha passato a Typst la cartella fonts/
# del template esterno.
FONT_DEJAVU="$(find /usr/share/fonts -name DejaVuSerif.ttf 2>/dev/null | head -1)"
ESTERNI="$WORK/esterni"
mkdir -p "$ESTERNI/a" "$ESTERNI/b"
cp -r "$ROOT/test/fixtures/templates/minimo" "$ESTERNI/a/minimo"
mkdir -p "$ESTERNI/a/minimo/fonts"
if [ -n "$FONT_DEJAVU" ]; then cp "$FONT_DEJAVU" "$ESTERNI/a/minimo/fonts/"; fi
sed -i 's/^mainfont:.*/mainfont: "DejaVu Serif"/' "$ESTERNI/a/minimo/theme.yaml"
cp -r "$ESTERNI/a/minimo" "$ESTERNI/b/minimo"
sed -i 's/Template minimo/Template minimo B/' "$ESTERNI/b/minimo/template.typ"
cp -r "$ESTERNI/a/minimo" "$ESTERNI/a/rotto-formato"
sed -i 's/^impagina-format:.*/impagina-format: 99/' "$ESTERNI/a/rotto-formato/theme.yaml"
mkdir -p "$ESTERNI/a/solo-tema" "$ESTERNI/a/.nascosto"
cp "$ESTERNI/a/minimo/theme.yaml" "$ESTERNI/a/solo-tema/"
cp "$ESTERNI/a/minimo/template.typ" "$ESTERNI/a/.nascosto/"

esterni() {  # esterni <IMPAGINA_TEMPLATES_PATH> <argomenti...>
  local percorso="$1"; shift
  docker run --rm --network=none --user "$(id -u):$(id -g)" \
    -v "$ESTERNI:/esterni:ro" -v "$WORK:/out" \
    -e IMPAGINA_TEMPLATES_PATH="$percorso" "$IMAGE" "$@" 2>&1
}
printf -- '---\ntitle: Prova esterna\n---\n\nTesto del documento.\n' > "$WORK/esterno.md"

uscita="$(esterni /esterni/a:/esterni/b -i /out/esterno.md -o /out/esterno.pdf -t minimo)"
codice=$?
verifica "converte con un template di una directory esterna" "0" "$codice"
pdftotext "$WORK/esterno.pdf" "$WORK/esterno.txt" 2>/dev/null
contiene "il template esterno e' quello applicato" "$WORK/esterno.txt" "Template minimo"
case "$(cat "$WORK/esterno.txt")" in
  *"Template minimo B"*) ko "con nomi duplicati vince la prima directory" ;;
  *) ok "con nomi duplicati vince la prima directory" ;; esac
case "$uscita" in *"template 'minimo' in /esterni/b ignorato"*)
  ok "il duplicato e' segnalato" ;; *) ko "il duplicato e' segnalato ($uscita)" ;; esac
case "$uscita" in *"template 'rotto-formato' in /esterni/a non valido"*"formato '99'"*)
  ok "un formato non supportato e' segnalato" ;;
  *) ko "un formato non supportato e' segnalato ($uscita)" ;; esac
case "$uscita" in *"template 'solo-tema'"*"manca template.typ"*)
  ok "una cartella con theme.yaml ma senza template.typ e' segnalata" ;;
  *) ko "una cartella con theme.yaml ma senza template.typ e' segnalata ($uscita)" ;; esac
case "$uscita" in *nascosto*) ko "le cartelle nascoste sono ignorate ($uscita)" ;;
  *) ok "le cartelle nascoste sono ignorate" ;; esac

if [ -n "$FONT_DEJAVU" ]; then
  pdffonts "$WORK/esterno.pdf" > "$WORK/esterno-font.txt" 2>/dev/null
  contiene "il font della cartella fonts/ del template e' incorporato" \
    "$WORK/esterno-font.txt" "DejaVuSerif"
else
  ko "font di prova assente: installa fonts-dejavu-core sull'host"
fi

uscita="$(esterni /esterni/a -i /out/esterno.md -o /out/rotto.pdf -t rotto-formato)"
verifica "un template malformato non si usa (esce con 3)" "3" "$?"
case "$uscita" in *"template 'rotto-formato' non valido"*)
  ok "l'errore spiega perche' il template non e' valido" ;;
  *) ko "l'errore spiega perche' il template non e' valido ($uscita)" ;; esac

uscita="$(esterni /esterni/inesistente:/esterni/a -i /out/esterno.md -o /out/inesistente.pdf -t minimo)"
verifica "una directory inesistente non ferma la conversione" "0" "$?"
case "$uscita" in *"directory dei template inesistente: /esterni/inesistente"*)
  ok "la directory inesistente e' segnalata" ;;
  *) ko "la directory inesistente e' segnalata ($uscita)" ;; esac

uscita="$(esterni /esterni/a -i /out/esterno.md -o /out/incluso.pdf -t company)"
verifica "i template inclusi restano disponibili" "0" "$?"

# IMPAGINA_TEMPLATES, il nome storico, vale ancora per una sola directory.
uscita="$(docker run --rm --network=none --user "$(id -u):$(id -g)" \
  -v "$ESTERNI:/esterni:ro" -v "$WORK:/out" -e IMPAGINA_TEMPLATES=/esterni/b \
  "$IMAGE" -i /out/esterno.md -o /out/alias.pdf -t minimo 2>&1)"
verifica "IMPAGINA_TEMPLATES resta valida come alias" "0" "$?"
uscita="$(docker run --rm --network=none --user "$(id -u):$(id -g)" \
  -v "$ESTERNI:/esterni:ro" -v "$WORK:/out" -e IMPAGINA_TEMPLATES=/esterni/b \
  -e IMPAGINA_TEMPLATES_PATH=/esterni/a "$IMAGE" \
  -i /out/esterno.md -o /out/entrambe.pdf -t minimo 2>&1)"
pdftotext "$WORK/entrambe.pdf" "$WORK/entrambe.txt" 2>/dev/null
case "$(cat "$WORK/entrambe.txt")" in
  *"Template minimo B"*) ko "IMPAGINA_TEMPLATES_PATH ha la precedenza sull'alias" ;;
  *) ok "IMPAGINA_TEMPLATES_PATH ha la precedenza sull'alias" ;; esac
case "$uscita" in *"IMPAGINA_TEMPLATES ignorata"*) ok "e l'alias ignorato e' segnalato" ;;
  *) ko "e l'alias ignorato e' segnalato ($uscita)" ;; esac

# --templates-dir ripetibile: sostituisce l'elenco, la prima vince.
uscita="$(docker run --rm --network=none --user "$(id -u):$(id -g)" \
  -v "$ESTERNI:/esterni:ro" -v "$WORK:/out" "$IMAGE" \
  -i /out/esterno.md -o /out/opzione.pdf -t minimo \
  --templates-dir /esterni/b --templates-dir /esterni/a 2>&1)"
pdftotext "$WORK/opzione.pdf" "$WORK/opzione.txt" 2>/dev/null
contiene "--templates-dir ripetuta: vince la prima" "$WORK/opzione.txt" "Template minimo B"

# Il /templates predefinito che ridefinisce company (capitolo 7) e' un uso
# normale: nessun avviso.
case "$(impagina -i "$ESEMPIO" -o /out/silenzio.pdf -t company)" in
  *Attenzione*) ko "ridefinire un template incluso non produce avvisi" ;;
  *) ok "ridefinire un template incluso non produce avvisi" ;; esac

# ---------------------------------------------------------------------------
capitolo "10. Precedenza dei metadati"
# Il front-matter del documento deve vincere sul theme.yaml del template.
contiene "il front-matter ha la precedenza sul theme.yaml" "$WORK/base.txt" \
  "Acme S.r.l. — Documento riservato · Rev. 3"

# ---------------------------------------------------------------------------
capitolo "11. Tabelle"
# Le colonne sono dimensionate sul contenuto e le parole restano intere: in una
# colonna stretta un termine spezzato a meta' si legge peggio.
cat > "$WORK/tabelle.md" <<'FINE'
---
title: Prova tabelle
cover: false
---

Paragrafo di riferimento per confrontare la dimensione del testo.

| Voce | Descrizione |
|---|---|
| Decommissionamento | Dismissione controllata dell'ambiente precedente dopo il collaudo finale. |
FINE
uscita="$(impagina -i /out/tabelle.md -o /out/tabelle.pdf -t company)"; codice=$?
verifica "converte un documento con tabelle" "0" "$codice"
pdftotext "$WORK/tabelle.pdf" "$WORK/tabelle.txt" 2>/dev/null
contiene "le parole nelle tabelle non sono sillabate" "$WORK/tabelle.txt" "Decommissionamento"

# Il testo delle tabelle e' piu' piccolo di quello del corpo (tablesize).
# pdftotext -bbox da' il riquadro di ogni parola: si confronta l'altezza dei
# glifi di una parola nella tabella con una di un paragrafo normale.
pdftotext -bbox "$WORK/tabelle.pdf" "$WORK/tabelle-bbox.html" 2>/dev/null
altezza_parola() { # altezza_parola <file bbox> <parola>
  python3 -c "
import re, sys
h = open(sys.argv[1], encoding='utf-8').read()
for m in re.finditer(r'yMin=\"([\d.]+)\" xMax=\"[\d.]+\" yMax=\"([\d.]+)\">([^<]+)<', h):
    if m.group(3) == sys.argv[2]:
        print(round(float(m.group(2)) - float(m.group(1)), 2)); break
else:
    print(0)
" "$1" "$2"
}
CORPO="$(altezza_parola "$WORK/tabelle-bbox.html" Paragrafo)"
CELLA="$(altezza_parola "$WORK/tabelle-bbox.html" Decommissionamento)"
verifica "il testo delle tabelle e' piu' piccolo del corpo" "1" \
  "$(python3 -c "print(1 if 0 < $CELLA < $CORPO else 0)")"

# Le larghezze indicate con trattini di lunghezze diverse vengono rispettate,
# quelle tutte uguali no: le due tabelle devono impaginarsi in modo diverso.
cat > "$WORK/larghezze.md" <<'FINE'
---
title: Larghezze
cover: false
---

| Voce | Descrizione |
|---|---|
| AAA | Testo di riferimento per il confronto delle larghezze. |

| Voce | Descrizione |
|:-----|:---------------------------------------------------------|
| AAA | Testo di riferimento per il confronto delle larghezze. |
FINE
impagina -i /out/larghezze.md -o /out/larghezze.pdf -t company >/dev/null 2>&1
pdftotext -bbox "$WORK/larghezze.pdf" "$WORK/larghezze-bbox.html" 2>/dev/null
verifica "i trattini sbilanciati cambiano la larghezza delle colonne" "1" \
  "$(python3 -c "
import re
h = open('$WORK/larghezze-bbox.html', encoding='utf-8').read()
x = [float(m.group(1)) for m in
     re.finditer(r'<word xMin=\"([\d.]+)\"[^>]*>Testo<', h)]
# due tabelle: 'Testo' inizia a x diverse se le larghezze sono diverse
print(1 if len(x) >= 2 and abs(x[0] - x[1]) > 2 else 0)")"

# La chiave table-hyphenate, portata a true nel front-matter, deve riattivare
# la sillabazione: serve per le tabelle troppo affollate.
sed 's/^cover: false$/cover: false\ntable-hyphenate: true/' \
  "$WORK/tabelle.md" > "$WORK/tabelle-hyp.md"
verifica "table-hyphenate: true resta convertibile" "0" \
  "$(impagina -i /out/tabelle-hyp.md -o /out/tabelle-hyp.pdf -t company >/dev/null 2>&1; echo $?)"

# ---------------------------------------------------------------------------
capitolo "12. Icona del tipo di documento"
cat > "$WORK/tipo-doc.md" <<'FINE'
---
title: Documento con tipo
doc-type: offerta-economica
---

Testo.
FINE
verifica "doc-type converte senza errori" "0" \
  "$(impagina -i /out/tipo-doc.md -o /out/tipo-doc.pdf -t company >/dev/null 2>&1; echo $?)"
pdftotext -f 1 -l 1 "$WORK/tipo-doc.pdf" "$WORK/tipo-doc.txt" 2>/dev/null
contiene "l'etichetta della categoria compare in copertina" "$WORK/tipo-doc.txt" "OFFERTA ECONOMICA"

# doc-label sostituisce l'etichetta, doc-hide-label la toglie.
sed 's/^doc-type: .*/doc-type: analisi\ndoc-label: "Analisi preliminare"/' \
  "$WORK/tipo-doc.md" > "$WORK/tipo-label.md"
impagina -i /out/tipo-label.md -o /out/tipo-label.pdf -t company >/dev/null 2>&1
pdftotext -f 1 -l 1 "$WORK/tipo-label.pdf" "$WORK/tipo-label.txt" 2>/dev/null
contiene "doc-label sostituisce l'etichetta" "$WORK/tipo-label.txt" "ANALISI PRELIMINARE"

sed 's/^doc-type: .*/doc-type: collaudo\ndoc-hide-label: true/' \
  "$WORK/tipo-doc.md" > "$WORK/tipo-muto.md"
impagina -i /out/tipo-muto.md -o /out/tipo-muto.pdf -t company >/dev/null 2>&1
pdftotext -f 1 -l 1 "$WORK/tipo-muto.pdf" "$WORK/tipo-muto.txt" 2>/dev/null
case "$(cat "$WORK/tipo-muto.txt")" in
  *COLLAUDO*|*VERBALE*) ko "doc-hide-label lascia la sola icona" ;;
  *) ok "doc-hide-label lascia la sola icona" ;;
esac

# Una categoria inesistente deve fermare la conversione con un messaggio utile.
sed 's/^doc-type: .*/doc-type: categoria-inventata/' "$WORK/tipo-doc.md" > "$WORK/tipo-errato.md"
uscita="$(impagina -i /out/tipo-errato.md -o /out/tipo-errato.pdf -t company 2>&1)"; codice=$?
verifica "un doc-type sconosciuto fallisce" "1" \
  "$([ "$codice" -ne 0 ] && echo 1 || echo 0)"
case "$uscita" in *"doc-type sconosciuto"*) ok "l'errore elenca le categorie valide" ;;
                  *) ko "l'errore elenca le categorie valide ($uscita)" ;; esac

# ---------------------------------------------------------------------------
capitolo "13. Guide dei template"
# Le guide usano tutta la sintassi che documentano: convertirle verifica che
# quanto promesso a chi scrive continui a funzionare.
verifica "la guida di company si converte" "0" \
  "$(impagina -i /data/templates/company/guida.md -o /out/guida-company.pdf -t company >/dev/null 2>&1; echo $?)"
pdftotext "$WORK/guida-company.pdf" "$WORK/guida.txt" 2>/dev/null
contiene "la guida elenca le categorie di doc-type" "$WORK/guida.txt" "offerta-tecnico-economica"
contiene "la guida spiega le larghezze di colonna" "$WORK/guida.txt" "Larghezza delle colonne"

# ---------------------------------------------------------------------------
capitolo "14. Opzioni per l'integrazione (--report, --sandbox) e titoli con virgolette"
printf -- '---\ntitle: Il "progetto" alfa\n---\n# Uno\n\ntesto\n' > "$WORK/virgolette.md"
uscita="$(impagina -i /out/virgolette.md -o /out/virgolette.pdf)"; codice=$?
verifica "un titolo con le virgolette si converte" "0" "$codice"
titolo="$(pdfinfo "$WORK/virgolette.pdf" 2>/dev/null | sed -n 's/^Title: *//p')"
verifica "il titolo arriva intatto nei metadati del PDF" 'Il "progetto" alfa' "$titolo"

uscita="$(impagina -i "$ESEMPIO" -o /out/report.pdf --report /out/report.json)"; codice=$?
verifica "--report: la conversione esce con 0" "0" "$codice"
contiene "--report: il rapporto riporta l'esito" "$WORK/report.json" '"esito": "ok"'
uscita="$(impagina -i /data/examples/nessuno.md --report /out/report-errore.json)"; codice=$?
verifica "--report: input assente esce con 2" "2" "$codice"
contiene "--report: il rapporto riporta il codice di uscita" "$WORK/report-errore.json" '"codice_uscita": 2'

uscita="$(impagina -i "$ESEMPIO" -o /out/sandbox.pdf --sandbox)"; codice=$?
verifica "--sandbox: un documento normale si converte" "0" "$codice"
printf -- '---\nfontsize: "11pt, fill: red"\n---\nx\n' > "$WORK/iniezione.md"
uscita="$(impagina -i /out/iniezione.md -o /out/iniezione.pdf --sandbox)"; codice=$?
verifica "--sandbox: un metadato con codice Typst esce con 5" "5" "$codice"
if printf '%s' "$uscita" | grep -qF "il metadato 'fontsize'"; then
  ok "--sandbox: il messaggio indica il metadato"
else ko "--sandbox: il messaggio indica il metadato ($uscita)"; fi
printf '![x](/opt/impagina/templates/company/assets/logo.svg)\n' > "$WORK/assoluta.md"
uscita="$(impagina -i /out/assoluta.md -o /out/assoluta.pdf --sandbox)"; codice=$?
verifica "--sandbox: un'immagine con percorso assoluto esce con 5" "5" "$codice"

# ---------------------------------------------------------------------------
riepilogo
