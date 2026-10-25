# Diario delle modifiche

Le modifiche rilevanti di **impagina** sono annotate qui, dalla più recente alla
più vecchia. Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/)
e la numerazione il [versionamento semantico](https://semver.org/lang/it/).

La versione è quella riportata da `impagina --version`, definita in
`src/impagina.py`.

## [Non rilasciato]

Nulla per ora.

## [2.0.0] — 2026-10-25

Primo rilascio pubblico. Le versioni 1.x non sono state pubblicate.
La 2.0 cambia il modo di installare i template che non fanno parte del tool,
mentre l'API HTTP resta compatibile con la 1.x.

### Funzionalità

- **Conversione da Markdown a PDF** con pandoc e Typst dentro un container
  Docker: sull'host serve solo Docker. Accetta un singolo file o una cartella,
  anche in modo ricorsivo, e scrive il PDF in modo atomico, così un client di
  sincronizzazione non ne vede mai uno incompleto.
- **Template `company`**: tema neutro di partenza e modello di riferimento per
  crearne di nuovi. Ha la copertina chiara e usa Inter e JetBrains Mono. La sua
  guida per chi scrive è inclusa, sia in sorgente sia già impaginata.
- **Template esterni**: i template aggiuntivi si caricano da una o più
  directory indicate con `IMPAGINA_TEMPLATES_PATH`, separate da `:`. Le regole
  su nomi duplicati, directory inesistenti e template malformati sono
  documentate. Il servizio API scrive nel log, all'avvio, i template trovati e
  gli eventuali problemi. `theme.yaml` può dichiarare la versione del formato
  (`impagina-format: 1`).
- **Icona del tipo di documento in copertina** (`doc-type`): quattordici
  categorie pronte, ciascuna con la propria etichetta. `doc-label` cambia
  l'etichetta, `doc-hide-label` lascia solo l'icona e `doc-icon` accetta
  un'icona propria. Le icone sono di [Lucide](https://lucide.dev) (licenza
  ISC) e prendono il colore del tema.
- **Precedenza dei valori** su tre livelli: prima il front-matter del
  documento, poi le opzioni della riga di comando, infine il `theme.yaml` del
  template.
- **Tabelle**: la larghezza delle colonne si indica nel Markdown, con la
  lunghezza dei trattini della riga separatrice. Le parole nelle celle non
  vengono sillabate.
- **Servizio API**: un servizio HTTP autenticato e asincrono, con una coda di
  lavori. Riceve un documento con le sue immagini oppure una cartella in uno
  ZIP e restituisce il PDF. Il contratto è descritto da un descrittore
  OpenAPI 3.1. Le chiavi di accesso hanno un nome e si possono revocare.
  `POST /dipendenze` elenca i file da allegare a un documento.
- **Modalità protetta** (`--sandbox`, sempre attiva nel servizio API): blocca
  il Typst grezzo, accetta solo immagini con percorsi relativi e valida i
  metadati.
- **`--report`**: scrive l'esito di ogni documento in JSON, per i programmi
  che usano impagina.
- **Suite di verifica** sul PDF prodotto davvero (`test/run-tests.sh`,
  `test/run-tests-api.sh`) e test di unità (`test/api-unita.py`).

### Novità rispetto alla 1.x

- I template aggiuntivi non sono più inclusi nel tool: si installano come
  template esterni. Chi usava un template che non sia `company` deve montarlo
  da una directory esterna, altrimenti la richiesta fallisce con «template non
  trovato».
- `IMPAGINA_TEMPLATES_PATH` accetta più directory. `IMPAGINA_TEMPLATES` resta
  valido come alias per una sola directory.
- `--templates-dir` si può ripetere. Il wrapper accetta in
  `IMPAGINA_TEMPLATES_DIR` più cartelle separate da `:`.
- Un template malformato viene escluso e il motivo compare nel messaggio di
  errore. Prima veniva ignorato senza spiegazioni, oppure faceva fallire la
  conversione.
- `doc-type` è disponibile anche nel template `company`.
