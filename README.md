# impagina

Converte documenti **Markdown in PDF** applicando un template aziendale (font,
colori, logo, intestazione, piè di pagina, numerazione). Gira interamente in un
container Docker: sull'host serve **solo Docker**, niente LaTeX, Node o Python.

Nato per un flusso di lavoro concreto: si scrive in Markdown (per esempio con
[Apostrophe](https://gitlab.gnome.org/World/apostrophe)), si archivia su
Nextcloud, e si vuole ottenere un PDF presentabile con un comando solo.

```bash
./impagina.sh relazione.md --template company
```

Può anche restare in ascolto come **servizio HTTP autenticato**, per farsi
chiamare da altre applicazioni (per esempio un'app Nextcloud): si invia il
Markdown con le sue immagini, si riceve il PDF. Vedi [Servizio API](#servizio-api).

<!-- --------------------------------------------------------------------- -->

## Indice

- [Come funziona](#come-funziona)
- [Requisiti](#requisiti)
- [Installazione](#installazione)
- [Uso](#uso)
- [Opzioni](#opzioni)
- [Metadati del documento](#metadati-del-documento)
- [Template](#template)
  - [Template disponibili](#template-disponibili)
  - [Template esterni](#template-esterni)
  - [Cambiare colori, font e logo](#cambiare-colori-font-e-logo)
  - [Creare un nuovo template](#creare-un-nuovo-template)
  - [Il file template.typ](#il-file-templatetyp)
- [Servizio API](#servizio-api)
  - [Avvio e chiavi di accesso](#avvio-e-chiavi-di-accesso)
  - [Inviare un documento](#inviare-un-documento)
  - [Seguire il lavoro e scaricare il PDF](#seguire-il-lavoro-e-scaricare-il-pdf)
  - [Quali file allegare: /dipendenze](#quali-file-allegare-dipendenze)
  - [Da un'applicazione PHP (Nextcloud)](#da-unapplicazione-php-nextcloud)
  - [Configurazione](#configurazione)
  - [Errori](#errori)
  - [Sicurezza](#sicurezza)
- [Codici di uscita](#codici-di-uscita)
- [Test](#test)
- [Dipendenze e versioni](#dipendenze-e-versioni)
- [Limiti noti](#limiti-noti)
- [Licenza](#licenza)

<!-- --------------------------------------------------------------------- -->

## Come funziona

```
documento.md ──▶ pandoc ──▶ sorgente Typst ──▶ typst ──▶ documento.pdf
                    ▲                             ▲
              template.typ                  theme.yaml, logo, font
```

**Pandoc** converte il Markdown in un sorgente [Typst](https://typst.app)
usando il template scelto; **Typst** lo compila in PDF.

Questa combinazione è stata scelta rispetto alle alternative (LaTeX,
WeasyPrint, Chrome headless) perché:

| | Pandoc + Typst | Pandoc + LaTeX | Chrome/Puppeteer |
|---|---|---|---|
| Immagine Docker | **~340 MB** | 1–1,5 GB | ~900 MB |
| Tempo per documento | **~0,3 s** | 1–3 s | 1–2 s |
| Intestazioni, piè di pagina, numerazione | nativi | nativi ma verbosi | limitati e separati dal CSS |
| Leggibilità del template | alta | bassa | alta |

Typst offre una qualità tipografica vicina a LaTeX (giustificazione,
sillabazione italiana, tabelle che ripetono l'intestazione a cavallo di pagina)
con un linguaggio di template che resta comprensibile a distanza di mesi.

<!-- --------------------------------------------------------------------- -->

## Requisiti

- **Docker** (testato con 28.x). Su ZorinOS/Ubuntu:
  ```bash
  sudo apt install docker.io
  sudo usermod -aG docker "$USER"   # poi esci e rientra dalla sessione
  ```
- `bash` e `coreutils` per lo script wrapper (già presenti su ZorinOS/Ubuntu).
- `poppler-utils` solo se vuoi eseguire la suite di test:
  `sudo apt install poppler-utils`.
- Solo per il [servizio API](#servizio-api): Docker Compose (il plugin
  `docker compose` oppure `docker-compose`) e, per la sua suite di test, `curl`
  e `python3`.

Nessun'altra dipendenza: pandoc, Typst e i font vivono dentro l'immagine.

<!-- --------------------------------------------------------------------- -->

## Installazione

```bash
git clone <url-del-repository> impagina
cd impagina
docker build -t impagina .
```

La build scarica pandoc, Typst e i font dalle release ufficiali: richiede
connessione a Internet e qualche minuto. Una volta costruita, l'immagine
funziona **senza rete** (il wrapper avvia i container con `--network=none`).

Per avere il comando disponibile ovunque:

```bash
ln -s "$PWD/impagina.sh" ~/.local/bin/impagina
```

<!-- --------------------------------------------------------------------- -->

## Uso

### Con lo script wrapper (consigliato)

```bash
# un file, PDF creato accanto al sorgente
./impagina.sh relazione.md

# scegliendo il template e la destinazione
./impagina.sh relazione.md --template company --output ~/Nextcloud/PDF/relazione.pdf

# una cartella intera, solo il primo livello
./impagina.sh ./note --output ./pdf

# tutto l'albero, con indice
./impagina.sh ./note --output ./pdf --recursive --toc

# bozza da far girare internamente
./impagina.sh contratto.md --watermark "BOZZA"

# con un template installato a parte (vedi "Template esterni")
IMPAGINA_TEMPLATES_DIR=~/impagina-template ./impagina.sh offerta.md --template aziendale
```

Il wrapper monta le cartelle necessarie, passa il tuo utente al container
(così i PDF **non** risultano di proprietà di `root`, cosa che impedirebbe a
Nextcloud di sovrascriverli) e traduce i percorsi dell'host.

### Con `docker run` diretto

```bash
docker run --rm --network=none \
  --user "$(id -u):$(id -g)" \
  -v "$(pwd)":/data \
  -v "$(pwd)/templates":/templates:ro \
  impagina \
  --input /data/documento.md --output /data/documento.pdf --template company
```

e per una cartella:

```bash
docker run --rm --network=none \
  --user "$(id -u):$(id -g)" \
  -v "$(pwd)":/data \
  -v "$(pwd)/templates":/templates:ro \
  impagina \
  --input /data/cartella --output /data/out --template company --recursive
```

Il montaggio di `/templates` è **facoltativo**: l'immagine contiene già il
template `company`. Montandolo, però, puoi modificare i template o aggiungerne
di nuovi senza ricostruire l'immagine (vedi [Template esterni](#template-esterni)).

<!-- --------------------------------------------------------------------- -->

## Opzioni

| Opzione | Descrizione |
|---|---|
| `-i, --input PERCORSO` | file `.md` o cartella da convertire (obbligatorio) |
| `-o, --output PERCORSO` | file `.pdf` o cartella di destinazione. Se omesso, il PDF viene creato accanto al sorgente |
| `-t, --template NOME` | template da applicare (default: `company`) |
| `-r, --recursive` | scende nelle sottocartelle, replicando la struttura nella destinazione |
| `--toc` | genera l'indice con i numeri di pagina |
| `--cover` / `--no-cover` | forza o disattiva la copertina |
| `--watermark TESTO` | filigrana diagonale su ogni pagina, es. `"BOZZA"` |
| `--templates-dir PERCORSO` | cartella dei template; ripetibile, la prima vince. Sostituisce l'intero elenco predefinito, template inclusi compresi (vedi [Template esterni](#template-esterni)) |
| `-v, --verbose` | mostra i comandi `pandoc` e `typst` eseguiti |
| `--version` | versione del tool |

Due opzioni pensate per i programmi che usano impagina (il servizio API le usa
sempre):

| Opzione | Descrizione |
|---|---|
| `--report PERCORSO` | scrive l'esito di ogni documento in JSON: codice di uscita, messaggio e suggerimento per chi è fallito, avvisi per chi è riuscito |
| `--sandbox` | modalità protetta per documenti scritti da altri: niente Typst grezzo, immagini solo con percorsi relativi dentro la cartella di input, metadati validati (vedi [Sicurezza](#sicurezza)) |

Variabili d'ambiente riconosciute dal wrapper:

| Variabile | Default | Uso |
|---|---|---|
| `IMPAGINA_IMAGE` | `impagina` | nome dell'immagine Docker |
| `IMPAGINA_TEMPLATES_DIR` | `./templates` accanto allo script | cartelle dei template da montare, separate da `:`; la prima vince e i template inclusi restano disponibili |

<!-- --------------------------------------------------------------------- -->

## Metadati del documento

Titolo, autore, data e testo del piè di pagina si scrivono nel **front-matter**
del `.md`, fra due righe di `---`:

```markdown
---
title: Relazione trimestrale sulla continuità operativa
subtitle: Analisi dei sistemi e piano di intervento
author:
  - Daniele Barresi
date: 1 settembre 2026
footer-text: "Acme S.r.l. — Documento riservato · Rev. 3"
toc: true
watermark: BOZZA
---

# Primo capitolo
```

**Precedenza dei valori**, dal più forte al più debole:

```
front-matter del documento  >  flag della riga di comando  >  theme.yaml del template
```

Così il template definisce l'aspetto predefinito, la riga di comando lo adatta
alla singola esecuzione, e un documento che ha esigenze proprie (per esempio un
piè di pagina diverso) se le porta dietro.

Qualunque chiave di `theme.yaml` può essere sovrascritta nel front-matter.

### Tipo di documento

`doc-type` mette sulla copertina l'icona del tipo di documento, accanto al
filetto colorato, con l'etichetta già pronta:

```markdown
---
title: Migrazione dell'infrastruttura applicativa in cloud
doc-type: offerta-economica
---
```

| `doc-type` | Etichetta |
|---|---|
| `documento-tecnico` | Documento tecnico |
| `analisi` | Analisi |
| `proposta` | Proposta progettuale |
| `offerta-economica` | Offerta economica |
| `offerta-tecnico-economica` | Offerta tecnico-economica |
| `stato-avanzamento` | Stato di avanzamento |
| `piano-progetto` | Piano di progetto |
| `specifiche` | Specifiche e requisiti |
| `collaudo` | Verbale di collaudo |
| `manuale` | Manuale |
| `verbale` | Verbale di riunione |
| `contratto` | Contratto |
| `sicurezza` | Audit di sicurezza |
| `relazione` | Relazione |

Un `doc-type` non in elenco interrompe la conversione con l'elenco di quelli
validi, invece di far sparire l'icona senza spiegazione.

Le tre chiavi che lo accompagnano:

| Chiave | Effetto |
|---|---|
| `doc-label` | sostituisce l'etichetta predefinita (`doc-label: "Analisi preliminare"`) |
| `doc-hide-label` | `true` lascia la sola icona |
| `doc-icon` | percorso di un'icona propria, relativo al documento; ha la precedenza su `doc-type` |

Le icone predefinite sono di [Lucide](https://lucide.dev) (licenza ISC) e stanno
in `templates/company/assets/icons/`; l'elenco delle categorie è in
`template.typ`, quindi ogni template può avere icone e categorie proprie. Sono
SVG disegnati con
`stroke="currentColor"`: il template sostituisce quella parola con il colore
`accent`, quindi **seguono la tinta del tema**. Vale anche per un SVG tuo, se
usa `currentColor`; un PNG viene invece inserito con i suoi colori.

<!-- --------------------------------------------------------------------- -->

## Template

### Template disponibili

| Nome | Aspetto | Font | Colore |
|---|---|---|---|
| `company` | template neutro di partenza, copertina chiara | Inter + JetBrains Mono | `#1F4E79` |

`company` è il template predefinito e il **modello di riferimento** per
crearne di nuovi: copialo, rinominalo e modifica `theme.yaml` (vedi
[Creare un nuovo template](#creare-un-nuovo-template)). Altri template, per
esempio quello con l'identità visiva della tua azienda, si tengono in un
repository a parte e si installano come [template esterni](#template-esterni).

**Guida per chi scrive** — il template porta con sé la propria guida, in
sorgente e già impaginata: `templates/company/guida.md` e `guida.pdf`. Spiega
il front-matter e la sintassi Markdown supportata con esempi, ed è prodotta con
il template che documenta, quindi mostra davvero il risultato che si ottiene.

### Template esterni

I template che non fanno parte del tool vivono in **directory esterne**, montate
nel container. impagina le cerca in quest'ordine:

1. le directory di `IMPAGINA_TEMPLATES_PATH`, separate da `:`
   (`IMPAGINA_TEMPLATES`, il nome usato fino alla 1.2, vale ancora per una sola
   directory; se ci sono entrambe vince `IMPAGINA_TEMPLATES_PATH`);
2. se nessuna delle due è impostata, `/templates`;
3. infine i template inclusi nell'immagine (`/opt/impagina/templates`).

In ogni directory, **ogni sottocartella con un `template.typ` è un template**,
e il nome della sottocartella è il nome del template. Le sottocartelle che
iniziano con `.` sono ignorate, così come quelle che non contengono né
`template.typ` né `theme.yaml`.

```
~/impagina-template/          ← la directory da montare
├── aziendale/                ← --template aziendale
│   ├── template.typ
│   ├── theme.yaml
│   └── ...
└── relazioni/                ← --template relazioni
```

Le regole, uguali per la CLI e per il servizio API:

| Caso | Comportamento |
|---|---|
| due template con lo stesso nome | vince quello della directory che viene prima; l'altro è ignorato con un avviso |
| un template esterno con il nome di uno incluso (per esempio `company`) | lo **sostituisce**, senza avvisi: è il modo di personalizzare quelli inclusi |
| directory indicata ma inesistente o illeggibile | avviso, e si prosegue con le altre (il `/templates` predefinito invece può mancare in silenzio) |
| template malformato: `template.typ` o `theme.yaml` illeggibili, `theme.yaml` senza `template.typ`, logo indicato ma assente, formato non supportato | errore con il motivo, e il template è **escluso**; se una directory successiva ha un template valido con lo stesso nome, si usa quello |

La CLI stampa avvisi ed errori su stderr a ogni esecuzione (`Attenzione: ...`);
chi chiede esplicitamente un template escluso riceve il motivo ed esce con 3.
Il servizio API li scrive nel log **all'avvio**, insieme all'elenco dei
template trovati e della loro directory:

```
… template disponibili: company (/templates), aziendale (/opt/template-esterni)
```

e `GET /template` elenca tutti e soli i template utilizzabili, nell'ordine di
precedenza. Le directory si rileggono a ogni richiesta: un template aggiunto o
corretto è disponibile subito, senza riavviare il servizio.

**Versione del formato** — `theme.yaml` può dichiarare `impagina-format: 1`,
la versione del formato dei template che rispetta (se manca vale 1). impagina
2.x gestisce il formato 1; un template che dichiara un formato diverso viene
escluso con un errore invece di produrre PDF sbagliati.

**Con `docker run`** si monta la directory su `/templates`, oppure altrove
indicandola con `IMPAGINA_TEMPLATES_PATH`:

```bash
docker run --rm --network=none --user "$(id -u):$(id -g)" \
  -v "$(pwd)":/data \
  -v ~/impagina-template:/opt/template-esterni:ro \
  -e IMPAGINA_TEMPLATES_PATH=/opt/template-esterni \
  impagina --input /data/offerta.md --template aziendale
```

**Con il wrapper** basta `IMPAGINA_TEMPLATES_DIR`, che accetta più cartelle
separate da `:` e le monta da sé:

```bash
IMPAGINA_TEMPLATES_DIR=./templates:~/impagina-template ./impagina.sh offerta.md -t aziendale
```

**Con il servizio API** si aggiunge un `compose.override.yaml` accanto a
`compose.yaml`, che Compose unisce da solo senza toccare il file originale:

```yaml
services:
  impagina-api:
    volumes:
      - /srv/impagina-template:/opt/template-esterni:ro
    environment:
      IMPAGINA_TEMPLATES_PATH: /templates:/opt/template-esterni
```

### Anatomia di un template

Ogni template è una cartella:

```
templates/
└── company/
    ├── theme.yaml         ← colori, font, margini, testi: quello che modifichi
    ├── template.typ       ← la struttura della pagina: raramente da toccare
    ├── assets/
    │   ├── logo.svg       ← il logo
    │   └── icons/         ← le icone di doc-type (facoltative)
    └── fonts/             ← i tuoi .ttf/.otf, se non usi quelli inclusi
```

Solo `template.typ` è obbligatorio. `theme.yaml` passa i suoi valori al
template; `fonts/` viene aggiunta ai font che Typst conosce; `assets/icons/`
arriva al template come `iconspath`.

Le tabelle ricevono un trattamento a parte, uguale per tutti i template: il
testo è più piccolo di quello del corpo (`tablesize`) e le parole non vengono
sillabate, perché in colonna stretta un termine spezzato si legge peggio. Se
una tabella è così affollata che una parola risulta più larga della propria
colonna, quella parola sborda: in quel caso, e solo in quello, conviene
`table-hyphenate: true` nel front-matter di quel documento.

**La larghezza delle colonne la decidi dal Markdown**, con la lunghezza dei
trattini nella riga separatrice:

```markdown
| Voce | Descrizione |
|---|---|                                 ← trattini uguali: decide il contenuto

| Voce | Descrizione                     |
|:-----|:--------------------------------|  ← 1 : 5, e 1 : 5 sarà nel PDF
```

Trattini tutti uguali non dicono nulla sul contenuto — darebbero lo stesso
spazio a una colonna di `99,20 %` e a una di testo discorsivo — quindi vengono
ignorati e la larghezza la calcola Typst sul contenuto effettivo. Trattini di
lunghezze diverse sono invece un'indicazione tua e vengono rispettati: vale
anche per le grid table (`+------+---------+`), dove contano le proporzioni del
disegno. Incolonnare le tabelle nel sorgente per leggerle meglio, quindi, è già
un modo di dimensionarle.

### Cambiare colori, font e logo

**Non serve ricostruire l'immagine Docker.** La cartella `templates/` viene
montata come volume a ogni esecuzione: modifichi un file, rilanci il comando e
il PDF successivo è già aggiornato.

1. **Colori e testi** — apri `templates/company/theme.yaml`:

   | Chiave | Effetto |
   |---|---|
   | `accent` | colore dei titoli, dei filetti e del bordo dei blocchi di codice |
   | `accent-soft` | sfondo della riga di intestazione delle tabelle |
   | `text-color` | colore del testo del corpo |
   | `muted-color` | intestazione, piè di pagina, didascalie |
   | `code-bg` | sfondo dei blocchi di codice |
   | `rule-color` | filetti e bordi sottili |
   | `mainfont`, `headingfont`, `codefont` | nomi delle famiglie di font (`headingfont` è facoltativo: se manca, i titoli usano `mainfont`) |
   | `fontsize`, `codesize`, `linestretch` | dimensioni e interlinea |
   | `tablesize` | dimensione del testo nelle tabelle, di norma relativa al corpo (`"0.85em"`) |
   | `papersize`, `margin-top`, `margin-bottom`, `margin-x` | geometria della pagina |
   | `lang`, `justify` | lingua (sillabazione) e giustificazione |
   | `table-hyphenate` | sillabazione dentro le tabelle: `false` (predefinito) tiene le parole intere |
   | `logo`, `logo-header-height`, `logo-cover-height` | logo e sue dimensioni |
   | `header-rule`, `footer-rule` | filetti sotto l'intestazione e sopra il piè di pagina |
   | `footer-text` | testo del piè di pagina |
   | `page-numbering` | formato Typst della numerazione: `"1 / 1"` produce `3 / 12` |
   | `cover`, `toc`, `toc-depth` | comportamenti predefiniti |

   > I colori si scrivono in esadecimale **senza** il carattere `#`
   > (`accent: "1F4E79"`), perché il cancelletto ha un significato speciale sia
   > in YAML sia in Typst.

2. **Logo** — sostituisci `templates/company/assets/logo.svg` con il tuo file
   (SVG o PNG) e, se cambi nome o estensione, aggiorna la chiave `logo:`.

3. **Font aziendali** — copia i file `.ttf`/`.otf` in
   `templates/company/fonts/` e imposta `mainfont` / `codefont` con il **nome
   della famiglia** (quello che vedi in un gestore di font), non con il nome
   del file. Verifica il risultato con `pdffonts documento.pdf`: se il tuo font
   non compare, il nome della famiglia è sbagliato e Typst ha usato un ripiego.

### Creare un nuovo template

```bash
cp -r templates/company templates/relazioni
# modifica templates/relazioni/theme.yaml e, se serve, template.typ
./impagina.sh documento.md --template relazioni
```

Il tool cerca i template prima nelle directory esterne (di norma `/templates`,
la cartella montata) e poi fra quelli inclusi nell'immagine: un template che si
chiama `company` nella tua cartella **sostituisce** quello predefinito. Per
tenerlo in un repository a parte vedi [Template esterni](#template-esterni).

### Il file `template.typ`

È un template Pandoc che produce codice Typst:

- `$variabile$` viene sostituita da pandoc con il valore preso da `theme.yaml`
  o dal front-matter;
- `$if(x)$ ... $endif$` è un blocco condizionale;
- tutto il resto è normale codice [Typst](https://typst.app/docs/).

Definisce la copertina, l'intestazione, il piè di pagina, lo stile dei titoli,
delle tabelle, dei blocchi di codice e delle citazioni. Per un semplice cambio
di identità visiva non serve aprirlo.

<!-- --------------------------------------------------------------------- -->

## Servizio API

Oltre al comando one-shot, impagina può restare in ascolto come servizio HTTP
autenticato, pensato per essere chiamato da altre applicazioni: per esempio
un'app Nextcloud che converte in PDF il Markdown aperto dall'utente.

Stessa immagine, stessi template, stessa pipeline. Il servizio è un piccolo
server scritto con la sola libreria standard di Python: riceve i documenti, li
mette in coda e li converte **uno alla volta** (configurabile) eseguendo
impagina come sottoprocesso, in una cartella di lavoro dedicata.

```
client ── POST /lavori (documento + immagini) ──▶ 202 {"id": ...}
                                                    │
                        coda ──▶ esecutore ──▶ impagina.py --sandbox
                                                    │
client ── GET /lavori/<id> ──▶ in_coda → in_corso → completato
client ── GET /lavori/<id>/risultato ──▶ il PDF (o uno ZIP di PDF)
```

Il contratto completo dell'API è descritto in **OpenAPI 3.1** in
[`src/impagina_api/openapi.yaml`](src/impagina_api/openapi.yaml), che il servizio
espone anche su `GET /openapi.yaml` (senza autenticazione): si può aprire con
Swagger UI o Redoc, o usare per generare un client.

Il modello è **asincrono**: l'invio risponde subito con l'identificativo del
lavoro, il client chiede a che punto è e scarica il risultato quando è pronto.
Un documento lungo non tiene aperta una connessione, e le richieste in eccesso
aspettano in coda invece di competere per CPU e memoria.

**A riposo** il servizio è un processo Python fermo: circa **20 MB di memoria**,
nessun uso di CPU, nessun thread che si sveglia se non per la pulizia dei
lavori scaduti (una volta al minuto). `docker stats` mostra un valore più alto
perché conteggia anche la cache dei file (pandoc, typst, font), che il kernel
libera quando serve.

### Avvio e chiavi di accesso

```bash
./impagina.sh --api chiave nuova nextcloud   # crea la chiave e mostra il token UNA volta
./impagina.sh --api avvia                    # costruisce l'immagine e avvia il servizio
./impagina.sh --api stato                    # stato del container e del servizio
./impagina.sh --api log                      # segue i log
./impagina.sh --api ferma                    # ferma il servizio (i lavori restano)
```

`--api` va scritto come primo argomento; tutto il resto di `impagina.sh`
funziona come prima. Senza lo script, il servizio si gestisce con Docker
Compose dalla cartella del progetto (`docker compose up -d --build`), usando
[`compose.yaml`](compose.yaml).

Il servizio ascolta su **`http://127.0.0.1:8080`**, raggiungibile quindi solo
dalla macchina stessa. `IMPAGINA_API_PORTA_HOST` cambia la porta; per
raggiungerlo da altre macchine vedi [Sicurezza](#sicurezza).

Ogni richiesta, tranne `GET /salute`, porta il token nell'intestazione:

```
Authorization: Bearer imp_<il-token-mostrato-alla-creazione>
```

Le chiavi hanno un **nome** (`nextcloud`, `script-backup`, …) e vivono in
`config/chiavi.conf`, che contiene l'impronta SHA-256 del token e **mai il
token**: se il file venisse letto, non darebbe accesso a nulla. Il nome compare
nei log accanto a ogni richiesta, il token mai.

```bash
./impagina.sh --api chiave elenco            # chiavi attive e revocate
./impagina.sh --api chiave revoca nextcloud  # effetto immediato, senza riavvio
```

Ogni chiave vede **solo i propri lavori**: chiedere il lavoro di un'altra chiave
risponde `404`, come se non esistesse.

### Inviare un documento

`POST /lavori` accetta due forme.

**Un documento con le sue immagini** (`multipart/form-data`): il Markdown nel
campo `documento`, ogni file che referenzia in un campo `allegato`, con il
**percorso relativo come nome del file**. È ciò che permette a
`![](immagini/schema.png)` di trovare l'immagine.

```bash
TOKEN=imp_...
curl -H "Authorization: Bearer $TOKEN" \
  -F documento=@relazione.md \
  -F "allegato=@immagini/schema.png;filename=immagini/schema.png" \
  -F template=company -F toc=true \
  http://127.0.0.1:8080/lavori
```

> **Attenzione con curl**: `-F allegato=@immagini/schema.png` invia solo
> `schema.png`, perché curl toglie la cartella dal nome. Il `;filename=...`
> esplicito serve a conservarla.

**Una cartella intera** (`application/zip`), con uno o più `.md` e le immagini,
e le opzioni nella query string:

```bash
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/zip" \
  --data-binary @note.zip \
  "http://127.0.0.1:8080/lavori?template=company&recursive=true"
```

Se tutto l'archivio sta sotto un'unica cartella (il caso tipico di "Comprimi"
nel file manager), quella cartella viene tolta: `note.zip` con dentro
`note/relazione.md` si comporta come se si fosse compressa direttamente la
cartella.

Le opzioni sono le stesse della CLI, come campi del form oppure nella query
string (con multipart, il campo del form vince):

| Opzione | Valori | Come nella CLI |
|---|---|---|
| `template` | nome di un template (default `company`) | `--template` |
| `toc` | `true` / `false` | `--toc` |
| `cover` | `true` / `false`; se assente decide il template | `--cover` / `--no-cover` |
| `watermark` | testo, al massimo 100 caratteri | `--watermark` |
| `recursive` | `true` / `false`, solo con ZIP | `--recursive` |

Un'opzione sconosciuta è un errore (`400`): meglio accorgersi subito di un
refuso che ricevere un PDF diverso da quello atteso.

La risposta è `202 Accepted`, con l'intestazione `Location` che punta al lavoro:

```json
{"id": "169e201112dc4da9876768b16991ac02", "stato": "in_coda", "posizione_in_coda": 1,
 "stato_url": "/lavori/169e201112dc4da9876768b16991ac02",
 "risultato_url": "/lavori/169e201112dc4da9876768b16991ac02/risultato"}
```

### Seguire il lavoro e scaricare il PDF

`GET /lavori/<id>` restituisce lo stato: `in_coda` (con la posizione),
`in_corso`, `completato` oppure `fallito`. Finché il lavoro non è terminato la
risposta include `Retry-After: 2`, un suggerimento su quando richiedere.

```json
{"id": "169e...", "stato": "completato", "esito": "ok",
 "creato": "2026-09-18T19:20:42Z", "terminato": "2026-09-18T19:20:42Z",
 "scade": "2026-09-18T20:20:42Z",
 "opzioni": {"template": "company", "toc": true, "cover": null, "watermark": null, "recursive": false},
 "documenti": [{"sorgente": "relazione.md", "esito": "ok", "pdf": "relazione.pdf", "avvisi": []}],
 "errore": null,
 "risultato": {"url": "/lavori/169e.../risultato", "tipo": "application/pdf",
               "nome": "relazione.pdf", "byte": 92269}}
```

- `esito` vale `ok` se tutti i documenti sono stati convertiti, `parziale` se
  qualcuno è fallito (il risultato contiene i PDF riusciti e `documenti` dice
  perché gli altri no), `errore` se non è riuscito nessuno.
- `GET /lavori/<id>/risultato` scarica il **PDF**, oppure uno **ZIP** che
  replica la struttura delle cartelle se i PDF sono più di uno. Finché il
  lavoro non è pronto risponde `409`.
- Il risultato resta disponibile per un'ora (`IMPAGINA_API_TTL`), poi viene
  cancellato. I file ricevuti vengono cancellati appena la conversione termina.
- `DELETE /lavori/<id>` cancella subito il lavoro e il suo risultato, oppure lo
  toglie dalla coda se non è ancora partito.

Un ciclo completo in bash:

```bash
ID=$(curl -s -H "Authorization: Bearer $TOKEN" -F documento=@nota.md \
       http://127.0.0.1:8080/lavori | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
while curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/lavori/$ID \
      | grep -qE '"stato": "in_(coda|corso)"'; do sleep 1; done
curl -s -H "Authorization: Bearer $TOKEN" -o nota.pdf \
  http://127.0.0.1:8080/lavori/$ID/risultato
```

### Quali file allegare: /dipendenze

Chi invia un documento deve sapere quali file il Markdown referenzia.
`POST /dipendenze` lo dice subito, senza convertire nulla: basta il `.md`, come
corpo `text/markdown` o come campo `documento` di un multipart (in questo caso,
gli `allegato` già presenti vengono segnati come tali).

```bash
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: text/markdown" \
  --data-binary @relazione.md http://127.0.0.1:8080/dipendenze
```

```json
{"file": [{"percorso": "immagini/schema.png", "tipo": "immagine", "stato": "da_allegare"}],
 "ignorati": [{"riferimento": "https://example.com/logo.png", "stato": "remoto",
               "motivo": "Typst non scarica file remoti: scaricalo e allegalo."}],
 "typst_grezzo": false, "documento": null}
```

I percorsi sono già normalizzati: sono esattamente i nomi da usare per gli
allegati. `ignorati` elenca ciò che non si può allegare (indirizzi remoti,
percorsi assoluti o che escono dalla cartella), `typst_grezzo` avvisa se il
documento contiene blocchi Typst che la modalità protetta rifiuterebbe.

`GET /template` elenca i template disponibili, per esempio per un menu a
tendina.

### Da un'applicazione PHP (Nextcloud)

```php
$ch = curl_init('http://127.0.0.1:8080/lavori');
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER     => ['Authorization: Bearer ' . $token],
    CURLOPT_POSTFIELDS     => [
        'documento'   => new CURLFile($percorsoMd, 'text/markdown', 'relazione.md'),
        // il terzo argomento e' il nome inviato: con la cartella
        'allegato[0]' => new CURLFile($percorsoPng, 'image/png', 'immagini/schema.png'),
        'template'    => 'company',
    ],
]);
$lavoro = json_decode(curl_exec($ch), true);   // $lavoro['id'], poi GET come sopra
```

Un array PHP non può ripetere una chiave, quindi gli allegati si chiamano
`allegato[0]`, `allegato[1]`, …: il servizio li tratta come `allegato`. Con un
client che ripete lo stesso nome (Guzzle, usato anche da Nextcloud, con
l'opzione `multipart`) si può usare semplicemente `allegato`.

Se Nextcloud gira a sua volta in un container, `127.0.0.1` è il container
stesso, non l'host: collega i due servizi alla stessa rete Docker e usa
`http://impagina-api:8080`, oppure pubblica la porta sull'indirizzo del bridge
Docker invece che su `127.0.0.1`.

### Configurazione

Le variabili più comuni si impostano in un file `.env` accanto a `compose.yaml`
(o nell'ambiente); le altre nella sezione `environment` di `compose.yaml`.

| Variabile | Default | Significato |
|---|---|---|
| `IMPAGINA_API_PORTA_HOST` | `8080` | porta su `127.0.0.1` (solo compose e `impagina.sh`) |
| `IMPAGINA_API_WORKER` | `1` | conversioni in parallelo (da 1 a 16) |
| `IMPAGINA_API_TIMEOUT` | `120` | secondi concessi a un lavoro, poi viene interrotto |
| `IMPAGINA_API_TTL` | `3600` | secondi di conservazione dei risultati |
| `IMPAGINA_API_MAX_CORPO` | `50M` | dimensione massima di una richiesta (`K`, `M`, `G`) |
| `IMPAGINA_API_TYPST_GREZZO` | `0` | `1` ammette il Typst grezzo: **solo con client fidati** |
| `IMPAGINA_API_MAX_ESPANSO` | `200M` | dimensione massima del contenuto estratto da uno ZIP |
| `IMPAGINA_API_MAX_FILE` | `200` | file per lavoro (documento più allegati, o voci dello ZIP) |
| `IMPAGINA_API_MAX_MD` | `5M` | dimensione massima del Markdown per `/dipendenze` |
| `IMPAGINA_API_CODA_MAX` | `50` | lavori in attesa; oltre, `503` con `Retry-After` |
| `IMPAGINA_API_CARICAMENTI` | `4` | caricamenti gestiti insieme; oltre, `503` |
| `IMPAGINA_API_PULIZIA_OGNI` | `60` | secondi fra due pulizie dei lavori scaduti |
| `IMPAGINA_API_CHIAVI` | `/etc/impagina/chiavi.conf` | file delle chiavi, nel container |
| `IMPAGINA_API_LAVORI` | `/var/lib/impagina-api` | cartella dei lavori, nel container (un volume) |
| `IMPAGINA_TEMPLATES_PATH` | `/templates` | directory dei template esterni, separate da `:` (vedi [Template esterni](#template-esterni)) |

Un valore non valido ferma l'avvio con un messaggio che dice quale variabile
correggere. Anche un file delle chiavi assente o senza chiavi valide ferma
l'avvio: il servizio non parte mai aperto.

I lavori stanno in un volume Docker: se il container si riavvia, i lavori in
coda ripartono e i risultati pronti restano scaricabili fino alla scadenza.

### Errori

Ogni errore ha la stessa forma, con un `codice` stabile che il client può
confrontare e un messaggio in italiano per le persone:

```json
{"errore": {"codice": "template_non_trovato",
            "messaggio": "template 'relazioni' non trovato.",
            "suggerimento": "Template disponibili: company"}}
```

| HTTP | Codici |
|---|---|
| `400` | `richiesta_non_valida`, `opzione_non_valida`, `percorso_non_valido` |
| `401` | `non_autorizzato` |
| `404` | `lavoro_non_trovato` (inesistente, scaduto o di un'altra chiave), `risorsa_non_trovata` |
| `405` | `metodo_non_consentito` (con l'intestazione `Allow`) |
| `409` | `non_pronto`: il lavoro non è ancora terminato |
| `411` | `lunghezza_richiesta`: serve `Content-Length` |
| `413` | `troppo_grande`, `troppi_file` |
| `415` | `tipo_non_supportato` |
| `422` | `template_non_trovato`, `nessun_documento`, `zip_non_valido`, `front_matter_non_valido`, `conversione_fallita`, `input_non_trovato`, `tempo_scaduto` |
| `500` | `errore_interno`, `interrotto`, `scrittura_fallita`, `uso_errato` |
| `503` | `coda_piena`, `server_occupato` (con `Retry-After`) |

Gli errori di un lavoro fallito compaiono in `GET /lavori/<id>`, per ogni
documento, e come risposta di `GET /lavori/<id>/risultato`. I messaggi mostrano
i percorsi come li ha inviati il client (`immagini/schema.png`), mai quelli
interni al server.

### Sicurezza

Il servizio riceve documenti scritti da altri, quindi li converte in
**modalità protetta** (`--sandbox`). Un template impagina è codice Typst in cui
pandoc incolla i valori del front-matter: senza protezioni, un metadato come
`fontsize: "11pt, fill: red"` finirebbe nel codice così com'è, e un documento
potrebbe leggere file del container. La modalità protetta:

- **rifiuta il Typst grezzo** (```` ```{=typst} ```` e `` `...`{=typst} ``);
- **valida ogni metadato** secondo l'uso che ne fa il template: colori
  esadecimali, lunghezze con unità di misura, testi senza virgolette doppie
  dove finiscono in una stringa. Titoli, autori e altri testi mostrati nel
  documento restano liberi;
- accetta **solo immagini con percorso relativo** che resta dentro la cartella
  del lavoro: niente percorsi assoluti, `..` che risalgono o indirizzi remoti.

Tutto il resto è pensato per limitare il danno di un errore:

- i nomi dei file ricevuti (multipart e ZIP) vengono normalizzati e
  **rifiutati se escono dalla cartella** (`../`, percorsi assoluti, `C:\`);
  gli ZIP con collegamenti simbolici o cifrati sono rifiutati;
- contro le **zip bomb** si contano i byte realmente estratti, non quelli
  dichiarati nell'archivio;
- limiti configurabili su dimensione della richiesta, numero di file, durata
  della conversione, coda e caricamenti contemporanei. Autenticazione e
  dimensione si controllano **prima di ricevere il corpo**;
- il container gira con un **utente non privilegiato**, filesystem in sola
  lettura, nessuna capability e `no-new-privileges`. Alla conversione arriva
  solo un elenco chiuso di variabili d'ambiente, e le chiavi sono salvate come
  impronte.

Cosa **non** è protetto:

- **La rete del container**: il servizio deve ricevere richieste, quindi il
  container ha la rete. Con Typst grezzo disattivato la conversione non la usa.
  Per chiuderla del tutto, collega il container solo a una rete Docker
  `internal: true` condivisa con il reverse proxy.
- **L'isolamento fra client**: i lavori di chiavi diverse girano con lo stesso
  utente di sistema. Ogni chiave vede solo i propri lavori tramite l'API, ma la
  separazione non arriva al livello del sistema operativo.

**HTTPS e accesso da altre macchine.** Il server è quello della libreria
standard di Python e ascolta solo su `127.0.0.1`. Per usarlo da un'altra
macchina mettilo dietro un reverse proxy con HTTPS, per esempio Caddy:

```
pdf.example.it {
    reverse_proxy 127.0.0.1:8080
    request_body {
        max_size 50MB
    }
}
```

oppure nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    client_max_body_size 50m;
    proxy_request_buffering on;   # il server riceve richieste gia' complete
    proxy_read_timeout 60s;
}
```

<!-- --------------------------------------------------------------------- -->

## Codici di uscita

| Codice | Significato | Nel servizio API |
|---|---|---|
| `0` | tutto convertito (o cartella senza file `.md`, con avviso) | `200` sul risultato |
| `1` | uso errato del comando | `500` `uso_errato` |
| `2` | file o cartella di input non trovata | `422` `input_non_trovato` |
| `3` | template non trovato (l'errore elenca quelli disponibili) | `422` `template_non_trovato` |
| `4` | front-matter YAML non valido | `422` `front_matter_non_valido` |
| `5` | errore di composizione del PDF (immagine mancante, errore nel template, contenuto rifiutato da `--sandbox`) | `422` `conversione_fallita` |
| `6` | destinazione non scrivibile | `500` `scrittura_fallita` |

Convertendo una cartella, un documento che fallisce **non interrompe** gli
altri: al termine viene stampato un riepilogo `N convertiti, M falliti` e il
codice di uscita è quello del primo errore incontrato.

<!-- --------------------------------------------------------------------- -->

## Test

```bash
sudo apt install poppler-utils fonts-dejavu-core    # una tantum
docker build -t impagina .
./test/run-tests.sh
```

La suite verifica, sul PDF realmente prodotto: numero e formato delle pagine,
presenza di piè di pagina, numerazione, tabelle, blocchi di codice e note;
incorporamento dei font; sillabazione italiana; indice, copertina e filigrana;
modalità cartella e ricorsiva; tutti i codici di uscita e l'assenza di stack
trace; proprietà dei file prodotti; che una modifica a `theme.yaml` abbia
effetto **senza ricostruire l'immagine**; il caricamento dei template esterni
(precedenza, duplicati, directory inesistenti, template malformati, font
propri), con il template di prova `test/fixtures/templates/minimo`; e le
opzioni `--report` e `--sandbox`.

Il servizio API ha due suite in più:

```bash
docker build --target api -t impagina-api .
./test/run-tests-api.sh      # end-to-end, via HTTP, su container di prova

docker run --rm --entrypoint python3 -v "$PWD/test:/test:ro" \
  impagina-api /test/api-unita.py      # unità: multipart, ZIP, percorsi, chiavi, template
```

La prima avvia due container su porte casuali di `127.0.0.1` e verifica
autenticazione e revoca, conversione con immagini, opzioni, ZIP ricorsivi,
tutti gli errori, gli attacchi (zip-slip, zip bomb, percorsi con `..`, Typst
grezzo, codice nei metadati), l'isolamento fra chiavi, la coda con un solo
lavoro alla volta, il timeout, la scadenza dei risultati e il riavvio. La
seconda prova caso per caso le parti che maneggiano input ostile, compreso il
delimitatore multipart spezzato su ogni possibile confine di lettura.

<!-- --------------------------------------------------------------------- -->

## Dipendenze e versioni

Tutto è incluso nell'immagine e bloccato a una versione precisa, modificabile
con gli `ARG` in cima al `Dockerfile`:

| Componente | Versione | Ruolo |
|---|---|---|
| [pandoc](https://pandoc.org) | 3.11 | Markdown → Typst |
| [Typst](https://typst.app) | 0.15.1 | Typst → PDF |
| [Inter](https://rsms.me/inter/) | 4.1 | font di testo predefinito |
| [JetBrains Mono](https://www.jetbrains.com/lp/mono/) | 2.304 | font monospazio predefinito |
| Debian bookworm-slim + Python 3.11 | — | base e CLI (solo libreria standard) |

Immagine risultante: **~340 MB**.

Per aggiornare, per esempio, Typst:

```bash
docker build --build-arg TYPST_VERSION=0.16.0 -t impagina .
```

<!-- --------------------------------------------------------------------- -->

## Limiti noti

- **Typst è un progetto giovane**: le versioni minori possono introdurre
  modifiche incompatibili. La versione è bloccata nel `Dockerfile`; dopo un
  aggiornamento può servire qualche ritocco a `template.typ`.
- **Testo dentro un logo SVG**: Typst non incorpora i font referenziati da un
  SVG. Se il logo contiene testo, convertilo in tracciati (in Inkscape:
  *Percorso → Da oggetto a tracciato*) oppure usa un PNG ad alta risoluzione.
  Il logo segnaposto incluso è composto solo da forme geometriche.
- **Filigrana e ricerca nel PDF**: essendo ruotata, le sue lettere non vengono
  raggruppate in parole dagli estrattori di testo, quindi cercare "BOZZA" con
  Ctrl+F non la trova. È il comportamento di qualunque filigrana diagonale.
- **Matematica**: le formule `$...$` vengono convertite in matematica Typst e
  funzionano per la notazione comune, ma non per macro LaTeX personalizzate.
- **Font inclusi**: Inter e JetBrains Mono non coprono emoji, CJK o alfabeti
  non latini estesi. Per quelli, aggiungi i file in `templates/<nome>/fonts/`.
- **Font su filesystem condivisi**: Typst mappa in memoria i file dei font, e
  su alcuni filesystem condivisi con la macchina host (virtiofs, 9p, alcune
  condivisioni di rete) la mappatura fallisce in silenzio: i font del template
  risultano "sconosciuti" e Typst ripiega su un font di sistema. Succede solo
  se il repository vive su una condivisione di questo tipo, non su un normale
  disco locale. Se capita, tieni la cartella `templates/` su un filesystem
  locale e indicala con `IMPAGINA_TEMPLATES_DIR`. La suite di test copia da
  sola i template in una cartella temporanea proprio per questo motivo.
- **Percorsi con il wrapper**: `impagina.sh` monta la cartella corrente e, se
  necessario, quelle di input e output. File sparsi su punti molto distanti del
  filesystem vanno indicati con percorsi assoluti.
- **`pdfinfo` segnala `Syntax Error: Suspects object is wrong type (boolean)`**:
  è una divergenza fra poppler e i metadati di accessibilità scritti da Typst
  0.15. Non compromette il PDF, che si apre correttamente nei lettori.
- **Servizio API e Typst grezzo**: in modalità protetta i blocchi
  ```` ```{=typst} ```` sono rifiutati, quindi un documento che li usa (come le
  guide dei template) si converte con la CLI ma non via API, a meno di
  `IMPAGINA_API_TYPST_GREZZO=1`.
- **Servizio API e metadati**: in modalità protetta colori, dimensioni e nomi
  di font nel front-matter devono avere la forma attesa (`1F4E79`, `10.5pt`,
  nessuna virgoletta doppia). Un template personalizzato che usa variabili
  nuove le vede accettate solo con testo semplice (lettere, cifre, spazi e
  `. - _ / %`), finché non vengono classificate in `src/filters/sandbox.lua`.
- **Servizio API e HTTP**: il server è quello della libreria standard di
  Python. Non accetta corpi `chunked` (serve `Content-Length`) e non gestisce
  HTTPS: per esporlo oltre la macchina va messo dietro un reverse proxy.
- **Arresto del servizio**: `docker stop` impiega circa 5 secondi, il tempo
  con cui il server controlla la richiesta di arresto. Una conversione in
  corso viene interrotta e riparte al riavvio.

<!-- --------------------------------------------------------------------- -->

## Licenza

impagina è distribuito con licenza [MIT](LICENSE). I componenti inclusi
mantengono le proprie licenze: le icone Lucide in `templates/company/assets/icons/`
hanno la licenza ISC (`LICENSE.txt` nella stessa cartella), e i font Inter e
JetBrains Mono, scaricati durante la build, la SIL Open Font License 1.1.
