---
title: Guida al template Company
subtitle: Come scrivere documenti aziendali con impagina
author:
  - Acme S.r.l.
date: 15 settembre 2026
doc-type: manuale
footer-text: "Acme S.r.l. — Guida al template"
toc: true
toc-depth: 2
---

# Prima di cominciare

Questa guida è rivolta a chi **scrive** i documenti, non a chi manutiene il
tool. Serve a rispondere a due domande: come si configura un documento nel suo
front-matter, e come si scrive il testo perché venga impaginato bene.

Il flusso è sempre lo stesso: si scrive un file Markdown, lo si converte e ne
esce un PDF impaginato — copertina con il logo, titoli blu, intestazione e piè
di pagina su ogni pagina.

```bash
./impagina.sh relazione.md
```

`company` è il template predefinito: non serve indicarlo. Il PDF viene creato
accanto al sorgente, `relazione.pdf`. Tutto il resto — se c'è la copertina, se
c'è l'indice, che cosa scrivere nel piè di pagina — si decide **dentro il file
Markdown**, nel front-matter.

Questa guida è essa stessa un documento prodotto con il template: quello che
vedi in queste pagine è esattamente ciò che otterrai.

> `company` è il template neutro di partenza: colori, logo e dati sono quelli
> di un'azienda di esempio. Se la tua organizzazione ne ha uno personalizzato,
> usa quello — le regole di scrittura descritte qui valgono comunque.

# Il front-matter

Il front-matter è il blocco fra due righe di `---` in cima al file. Contiene i
dati del documento, uno per riga, nella forma `chiave: valore`.

```markdown
---
title: Relazione trimestrale sulla continuità operativa
subtitle: Analisi dei sistemi e piano di intervento
author:
  - Daniele Barresi
date: 1 settembre 2026
footer-text: "Acme S.r.l. — Documento riservato · Rev. 3"
toc: true
---

# Primo capitolo

Il testo del documento comincia qui.
```

Deve stare all'inizio del file, senza righe vuote prima. I valori che
contengono i due punti vanno fra virgolette: `footer-text: "Rev. 2: bozza"`.

## Le chiavi essenziali

| Chiave | Effetto |
|:-----------------|:--------------------------------------------------------|
| `title` | titolo del documento: campeggia in copertina e si ripete, piccolo, nell'intestazione di ogni pagina |
| `subtitle` | sottotitolo, sotto il titolo di copertina |
| `author` | uno o più autori, in basso a sinistra sulla copertina |
| `date` | data, in basso a destra sulla copertina. È testo libero: scrivila come vuoi che appaia |
| `footer-text` | testo del piè di pagina. Se omesso resta quello del template |

Gli autori si elencano uno per riga, ciascuno preceduto da un trattino:

```markdown
author:
  - Daniele Barresi
  - Anna Rossi
```

## Indice, copertina, filigrana

| Chiave | Valori | Effetto |
|:---------------|:-------------|:-----------------------------------------|
| `toc` | `true` / `false` | indice con i numeri di pagina, dopo la copertina |
| `toc-depth` | da 1 a 3 | fino a che livello di titoli scendere nell'indice |
| `cover` | `true` / `false` | con `false` il documento parte senza copertina: titolo e logo aprono la prima pagina |
| `watermark` | testo libero | filigrana diagonale su ogni pagina, per esempio `BOZZA` |

Per un documento breve — una nota di due pagine, un verbale — conviene
`cover: false`: la copertina intera sarebbe sproporzionata.

```markdown
---
title: Verbale della riunione del 12 settembre
cover: false
watermark: BOZZA
---
```

## Il tipo di documento

`doc-type` mette in copertina, accanto al filetto colorato, l'icona del tipo di
documento con la sua etichetta. Serve a far capire al primo sguardo che cosa si
ha in mano.

```markdown
doc-type: offerta-economica
```

Le categorie disponibili:

| `doc-type` | Etichetta stampata |
|:----------------------------|:---------------------------------------|
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

Se scrivi una categoria che non esiste la conversione si ferma e ti elenca
quelle valide: è voluto, così non ti ritrovi un PDF senza icona senza capire
perché.

Tre chiavi accompagnano `doc-type`:

| Chiave | Effetto |
|:------------------|:-------------------------------------------------------|
| `doc-label` | sostituisce l'etichetta predefinita: `doc-label: "Analisi preliminare"` |
| `doc-hide-label` | con `true` resta la sola icona, senza scritta |
| `doc-icon` | percorso di un'icona tua, relativo al documento; ha la precedenza su `doc-type` |

Per `doc-icon` va bene un SVG o un PNG. Se l'SVG è disegnato con
`stroke="currentColor"` — come quelli di [Lucide](https://lucide.dev) — viene
tinto automaticamente del colore del tema.

```markdown
doc-icon: icone/certificazione.svg
doc-label: "Certificazione ISO"
```

# Scrivere il testo

Da qui in avanti si tratta di Markdown normale. Questa sezione mostra come
ciascun elemento viene reso dal template.

## Titoli

I titoli si aprono con uno o più `#`. Il livello 1 apre una sezione e porta un
filetto sotto di sé; i livelli inferiori scalano di dimensione.

```markdown
# Titolo di primo livello
## Titolo di secondo livello
### Titolo di terzo livello
#### Titolo di quarto livello
```

Non saltare i livelli: un `###` deve stare sotto un `##`, altrimenti l'indice
risulta incoerente. Il titolo del documento **non** si scrive come `#` in cima
al testo: quello è `title` nel front-matter.

## Enfasi e testo

| Si scrive | Si ottiene |
|:-------------------------|:-----------------------------|
| `*corsivo*` | *corsivo* |
| `**grassetto**` | **grassetto** |
| `***grassetto corsivo***` | ***grassetto corsivo*** |
| `~~barrato~~` | ~~barrato~~ |
| `` `codice` `` | `codice` |

Il testo del corpo è giustificato e sillabato in italiano: le parole lunghe
vengono spezzate correttamente a fine riga, senza spaziature irregolari.

Per andare a capo dentro lo stesso paragrafo si lasciano **due spazi** a fine
riga. Per separare due paragrafi basta una riga vuota.

## Elenchi

Elenco puntato, con un trattino e uno spazio:

```markdown
- Preparazione dell'ambiente
- Migrazione dei dati
  - Prima ondata: archivi storici
  - Seconda ondata: dati operativi
- Collaudo
```

- Preparazione dell'ambiente
- Migrazione dei dati
  - Prima ondata: archivi storici
  - Seconda ondata: dati operativi
- Collaudo

Elenco numerato, con `1.`, `2.`, `3.`. I numeri li rifà comunque il
programma, quindi va bene anche scrivere sempre `1.`:

1. Inventario delle dipendenze
2. Definizione degli ambienti
3. Automazione della configurazione

Le sottovoci vanno **indentate di due spazi** rispetto alla voce che le
contiene. Un elenco deve essere preceduto da una riga vuota, altrimenti viene
letto come continuazione del paragrafo.

Per un glossario o un elenco di definizioni si usa il termine su una riga e la
definizione sulla successiva, preceduta da due punti e tre spazi:

```markdown
RTO
:   Recovery Time Objective, il tempo massimo di indisponibilità accettabile.

RPO
:   Recovery Point Objective, la quantità massima di dati che si accetta di
    perdere in caso di ripristino.
```

RTO
:   Recovery Time Objective, il tempo massimo di indisponibilità accettabile.

RPO
:   Recovery Point Objective, la quantità massima di dati che si accetta di
    perdere in caso di ripristino.

## Tabelle

Le tabelle si scrivono con le barre verticali. La riga di trattini separa
l'intestazione dal corpo e serve anche per due altre cose: l'allineamento e la
larghezza delle colonne.

```markdown
| Indicatore                | Attuale | Obiettivo | Verifica         |
|:--------------------------|--------:|----------:|:-----------------|
| Disponibilità mensile     | 99,20 % |   99,90 % | Monitoraggio     |
| Tempo di ripristino (RTO) |  90 min |    15 min | Prova semestrale |
```

| Indicatore                | Attuale | Obiettivo | Verifica         |
|:--------------------------|--------:|----------:|:-----------------|
| Disponibilità mensile     | 99,20 % |   99,90 % | Monitoraggio     |
| Tempo di ripristino (RTO) |  90 min |    15 min | Prova semestrale |

**Allineamento** — i due punti nella riga dei trattini decidono come si allinea
la colonna: `:---` a sinistra, `---:` a destra, `:---:` al centro. I numeri
stanno bene a destra, il testo a sinistra. Senza i due punti il contenuto
finisce centrato, che per i testi lunghi si legge male: mettili sempre.

**Larghezza delle colonne** — conta la lunghezza dei trattini:

- trattini **tutti uguali** (`|---|---|`): la larghezza la decide il contenuto,
  una colonna di numeri resta stretta e una di testo si allarga;
- trattini di **lunghezze diverse**: vengono rispettate quelle proporzioni.

Quindi incolonnare la tabella nel sorgente, come nell'esempio qui sopra, è già
un modo per dimensionarla. Il testo nelle tabelle è più piccolo di quello del
corpo e le parole non vengono mai spezzate a fine riga.

Se una tabella è così affollata che una parola risulta più larga della propria
colonna, quella parola sborda dal bordo: in quel caso — e solo in quello —
aggiungi `table-hyphenate: true` al front-matter di quel documento.

## Citazioni

Una riga che comincia con `>` diventa un blocco citazione, in corsivo con un
filetto a sinistra. Va bene per mettere in evidenza un impegno o una
conclusione.

```markdown
> Il tempo di ripristino medio è sceso da 47 a 18 minuti rispetto al
> trimestre precedente.
```

> Il tempo di ripristino medio è sceso da 47 a 18 minuti rispetto al
> trimestre precedente.

## Codice e comandi

Per il codice si usano tre apici inversi, con il nome del linguaggio subito
dopo i primi tre: la sintassi viene colorata automaticamente.

````markdown
```python
def verifica_nodo(nodo: str, soglia_ms: int = 250) -> bool:
    inizio = time.monotonic()
    risposta = requests.get(f"https://{nodo}/health", timeout=2.0)
    return risposta.status_code == 200
```
````

```python
def verifica_nodo(nodo: str, soglia_ms: int = 250) -> bool:
    inizio = time.monotonic()
    risposta = requests.get(f"https://{nodo}/health", timeout=2.0)
    return risposta.status_code == 200
```

Funzionano `python`, `yaml`, `json`, `bash`, `sql`, `xml` e le altre decine di
linguaggi noti. Senza indicare il linguaggio il blocco resta monospaziato ma
non colorato — va bene per l'output di un comando.

## Immagini

```markdown
![Flusso di replica fra la sede operativa e l'ambiente di destinazione](immagini/schema.svg)
```

Il testo fra parentesi quadre diventa la **didascalia** sotto l'immagine,
numerata automaticamente (*Figura 1*, *Figura 2*...). Lasciandolo vuoto —
`![](immagini/schema.svg)` — l'immagine compare senza didascalia.

Il percorso è relativo alla cartella del documento. Vanno bene SVG, PNG e JPG;
per schemi e diagrammi preferisci l'SVG, che resta nitido a qualsiasi
ingrandimento e in stampa.

## Note a piè di pagina

```markdown
I dettagli operativi sono nel repository di progetto[^1].

[^1]: Repository `acme/continuita-operativa`, cartella `docs/`.
```

I dettagli operativi sono nel repository di progetto[^1].

[^1]: Repository `acme/continuita-operativa`, cartella `docs/`.

Il riferimento `[^1]` può stare ovunque nel testo e la nota compare in fondo
alla pagina giusta. L'etichetta può essere anche una parola: `[^nota-tecnica]`.

## Collegamenti

| Si scrive | Risultato |
|:-------------------------------------|:---------------------------|
| `<https://example.com>` | l'indirizzo, cliccabile |
| `[il nostro sito](https://example.com)` | [il nostro sito](https://example.com) |
| `[scrivici](mailto:info@example.com)` | [scrivici](mailto:info@example.com) |

I collegamenti restano cliccabili nel PDF.

## Separatori e interruzioni di pagina

Tre trattini su una riga isolata creano un separatore orizzontale centrato,
utile per staccare due parti di un capitolo:

```markdown
---
```

Per mandare il testo seguente **in una pagina nuova** si usa un blocco speciale:

````markdown
```{=typst}
#pagebreak()
```
````

È l'unico frammento non-Markdown di questa guida: serve perché il Markdown, di
suo, non prevede le interruzioni di pagina. Usalo con parsimonia — prima di
ogni capitolo principale, per esempio.

# Dalla riga di comando

Quasi tutto si governa dal front-matter. Restano al comando solo le cose che
riguardano *quali* file convertire e *con quale* template:

```bash
# un documento, col template predefinito
./impagina.sh relazione.md

# scegliendo dove salvare il PDF
./impagina.sh relazione.md -o consegne/relazione-q3.pdf

# una cartella intera, sottocartelle comprese
./impagina.sh documenti/ --recursive

# con un template diverso
./impagina.sh offerta.md --template relazioni
```

Le opzioni `--toc`, `--cover` / `--no-cover` e `--watermark` esistono anche qui,
ma hanno lo stesso effetto delle chiavi del front-matter; e **il front-matter
vince sempre sulla riga di comando**. Servono per una singola esecuzione — per
esempio marcare come bozza un documento che di norma non lo è — senza toccare
il file:

```bash
./impagina.sh relazione.md --watermark "BOZZA"
```

# Impostazioni ereditate dal template

Le chiavi seguenti hanno già un valore adatto ai documenti aziendali e non
vanno toccate se non serve. Si possono comunque sovrascrivere nel front-matter
di un singolo documento, e valgono solo per quello.

| Chiave | Valore predefinito | Effetto |
|:---------------|:----------|:---------------------------------------------|
| `fontsize` | `10.5pt` | corpo del testo |
| `tablesize` | `0.85em` | testo nelle tabelle, relativo al corpo |
| `justify` | `true` | testo giustificato |
| `lang` | `it` | lingua, da cui dipende la sillabazione |
| `papersize` | `a4` | formato della pagina |
| `page-numbering` | `1 / 1` | numerazione: produce `3 / 12` |

Per un documento da leggere a schermo, per esempio, può avere senso
`justify: false`.

# Un documento completo

Questo è lo scheletro di una relazione, da copiare e adattare:

```markdown
---
title: Relazione trimestrale sulla continuità operativa
subtitle: Analisi dei sistemi e piano di intervento
author:
  - Daniele Barresi
date: 15 settembre 2026
doc-type: relazione
footer-text: "Acme S.r.l. — Documento riservato · Rev. 3"
toc: true
---

# Sintesi per la direzione

Due paragrafi che dicono com'è andato il trimestre e che cosa si propone.

> Il tempo di ripristino medio è sceso da 47 a 18 minuti.

# Indicatori principali

| Indicatore              | Obiettivo | Rilevato |
|:------------------------|----------:|---------:|
| Disponibilità           |   99,50 % |  99,82 % |
| Tempo di ripristino     |    30 min |   18 min |

# Interventi previsti

1. Completare la copertura dei test automatici entro dicembre
2. Rivedere la procedura di gestione degli incidenti di sicurezza
3. Estendere la replica geografica al secondo datacenter

# Dettaglio tecnico

## Procedura di failover

Il controllo di integrità viene eseguito ogni trenta secondi.
```

# Per approfondire

La sintassi accettata è quella di **Pandoc Markdown**, che comprende il
Markdown classico più le estensioni usate in questa guida — tabelle, note a piè
di pagina, elenchi di definizioni.

- **Guida ufficiale Pandoc Markdown** —
  <https://pandoc.org/MANUAL.html#pandocs-markdown>
  Il riferimento completo. I capitoli utili a chi scrive sono *Tables*,
  *Footnotes*, *Definition lists* e *Inline formatting*.
- **CommonMark in dieci minuti** — <https://commonmark.org/help/>
  Un ripasso veloce delle basi, con esempi affiancati. Non copre tabelle e note,
  che sono estensioni di Pandoc.
- **Tutorial interattivo CommonMark** — <https://commonmark.org/help/tutorial/>
  Dieci minuti di esercizi per prendere confidenza con la sintassi.

Una cosa da tenere a mente leggendo quelle pagine: l'HTML scritto dentro il
Markdown **non** funziona, perché la destinazione non è una pagina web ma un
PDF. Tutto il resto della sintassi descritta lì si comporta come documentato.
