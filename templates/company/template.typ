// ===========================================================================
// impagina — template "company"
//
// Questo file e' un TEMPLATE PANDOC che produce un sorgente Typst.
//   $variabile$        viene sostituita da pandoc
//   $if(x)$ ... $endif$  blocco condizionale
// Tutto il resto e' normale codice Typst.
//
// I valori arrivano da (in ordine di precedenza crescente):
//   theme.yaml  ->  flag della CLI  ->  front-matter del documento .md
//
// Per un semplice cambio di colori, font o logo NON serve toccare questo
// file: basta theme.yaml.
// ===========================================================================

// --- Elementi richiesti dal writer typst di pandoc -------------------------
// pandoc emette #divider() per le righe orizzontali (--- nel Markdown).
// Ridefinito qui come filetto centrato e discreto: quello predefinito e' una
// riga nera a tutta larghezza, troppo pesante in un documento aziendale.
#let divider() = block(above: 1.6em, below: 1.6em, width: 100%,
  align(center, line(length: 32%, stroke: 0.8pt + rgb("#$rule-color$"))))

#set terms(hanging-indent: 1.5em)

$if(highlighting-definitions)$
$highlighting-definitions$
$endif$

// --- Palette (da theme.yaml, esadecimale senza '#') ------------------------
#let accent     = rgb("#$accent$")
#let accentSoft = rgb("#$accent-soft$")
#let bodyColor  = rgb("#$text-color$")
#let mutedColor = rgb("#$muted-color$")
#let codeBg     = rgb("#$code-bg$")
#let ruleColor  = rgb("#$rule-color$")

// --- Font ------------------------------------------------------------------
// Il secondo elemento di ogni lista e' un ripiego: se il font indicato in
// theme.yaml non e' installato, Typst usa quello invece di fallire.
#let textFont = ("$mainfont$", "Inter")
#let codeFont = ("$codefont$", "JetBrains Mono")
// Se theme.yaml non definisce headingfont, i titoli usano il font del testo.
#let headingFont = ($if(headingfont)$"$headingfont$", $endif$"$mainfont$", "Inter")

// --- Logo ------------------------------------------------------------------
// logopath e' il percorso assoluto risolto dalla CLI a partire da theme.yaml.
$if(logopath)$
#let logoAt(h) = image("$logopath$", height: h)
$else$
#let logoAt(h) = none
$endif$

// --- Icona del tipo di documento -------------------------------------------
// Le icone sono file SVG di Lucide (licenza ISC) in assets/icons/, disegnati
// con stroke="currentColor": sostituendo quella parola con un colore vero si
// ottiene un'icona tinta come il tema, cosa che image() da sola non permette.
#let iconaDoc(percorso, colore, dim) = if percorso.ends-with(".svg") {
  image(bytes(read(percorso).replace("currentColor", colore.to-hex())),
        format: "svg", width: dim)
} else {
  // Un'icona in PNG o JPG non si puo' ricolorare: si inserisce com'e'.
  image(percorso, width: dim)
}

// Categorie predefinite: chiave di doc-type -> (file in assets/icons, etichetta).
#let catalogoDoc = (
  "documento-tecnico":         ("file-code",              "Documento tecnico"),
  "analisi":                   ("chart-no-axes-combined", "Analisi"),
  "proposta":                  ("lightbulb",              "Proposta progettuale"),
  "offerta-economica":         ("receipt-euro",           "Offerta economica"),
  "offerta-tecnico-economica": ("scroll-text",            "Offerta tecnico-economica"),
  "stato-avanzamento":         ("chart-gantt",            "Stato di avanzamento"),
  "piano-progetto":            ("calendar-range",         "Piano di progetto"),
  "specifiche":                ("list-checks",            "Specifiche e requisiti"),
  "collaudo":                  ("clipboard-check",        "Verbale di collaudo"),
  "manuale":                   ("book-open",              "Manuale"),
  "verbale":                   ("file-pen",               "Verbale di riunione"),
  "contratto":                 ("file-check",             "Contratto"),
  "sicurezza":                 ("shield-check",           "Audit di sicurezza"),
  "relazione":                 ("file-text",              "Relazione"),
)

#let docType  = "$doc-type$"
#let docIcon  = "$doc-icon$"
#let docLabel = "$doc-label$"
#let voce     = if docType == "" { none } else if docType in catalogoDoc {
  catalogoDoc.at(docType)
} else {
  // Meglio un errore leggibile che un'icona che sparisce senza spiegazione.
  panic("doc-type sconosciuto: \"" + docType + "\". Categorie disponibili: "
        + catalogoDoc.keys().join(", "))
}

// doc-icon (percorso libero) ha la precedenza sulla categoria. Un percorso
// relativo si intende a partire dalla cartella del documento Markdown, perche'
// il .typ intermedio vive altrove; iconspath e docdir arrivano dalla CLI.
#let iconaPercorso = if docIcon != "" {
  if docIcon.starts-with("/") { docIcon } else { "$docdir$/" + docIcon }
} else if voce != none {
  "$iconspath$/" + voce.at(0) + ".svg"
} else {
  none
}

// L'etichetta viene dalla categoria; doc-label la sostituisce e
// doc-hide-label: true la toglie lasciando la sola icona.
#let iconaEtichetta = $if(doc-hide-label)$none$else$if docLabel != "" {
  docLabel
} else if voce != none {
  voce.at(1)
} else {
  none
}$endif$

#let bloccoTipoDocumento = if iconaPercorso != none {
  grid(
    columns: (auto, auto),
    column-gutter: 0.26cm,
    align: (left + horizon, left + horizon),
    iconaDoc(iconaPercorso, accent, $if(doc-icon-size)$$doc-icon-size$$else$0.53cm$endif$),
    if iconaEtichetta != none {
      text(font: headingFont, size: 8pt, weight: 600, fill: accent,
           tracking: 0.09em)[#upper(iconaEtichetta)]
    } else { none },
  )
} else { none }

// --- Filigrana -------------------------------------------------------------
$if(watermark)$
#let watermarkLayer = align(center + horizon,
  rotate(-30deg,
    text(size: 88pt, weight: 800, fill: accent.lighten(80%))[$watermark$]
  )
)
$else$
#let watermarkLayer = none
$endif$

// --- Intestazione ----------------------------------------------------------
#let primaPaginaConIntestazione = $if(cover)$1$else$2$endif$
#let headerBlock = context {
  // Senza copertina la prima pagina porta gia' il blocco titolo: l'intestazione
  // ripeterebbe la stessa informazione due volte.
  if here().page() < primaPaginaConIntestazione {
    none
  } else {
    block(width: 100%, {
      grid(
        columns: (1fr, auto),
        align: (left + horizon, right + horizon),
        text(size: 8pt, fill: mutedColor)[$if(title)$$title$$endif$],
        logoAt($logo-header-height$),
      )
      $if(header-rule)$
      v(-3pt)
      line(length: 100%, stroke: 0.5pt + ruleColor)
      $endif$
    })
  }
}

// --- Pie' di pagina --------------------------------------------------------
#let footerBlock = context {
  block(width: 100%, {
    $if(footer-rule)$
    line(length: 100%, stroke: 0.5pt + ruleColor)
    v(-3pt)
    $endif$
    grid(
      columns: (1fr, auto),
      align: (left + horizon, right + horizon),
      text(size: 8pt, fill: mutedColor)[$if(footer-text)$$footer-text$$endif$],
      text(size: 8pt, fill: mutedColor)[
        #counter(page).display("$page-numbering$", both: true)
      ],
    )
  })
}

// --- Impostazioni di pagina e di testo -------------------------------------
// Titolo come contenuto e non come stringa: pandoc fa l'escape del markup
// ma non delle virgolette, quindi "$title$" si romperebbe con un titolo come
// Il "progetto" alfa.
#set document(
  title: $if(title)$[$title$]$else$none$endif$,
)

#set page(
  paper: "$papersize$",
  margin: (top: $margin-top$, bottom: $margin-bottom$, x: $margin-x$),
  header: headerBlock,
  header-ascent: 40%,
  footer: footerBlock,
  footer-descent: 35%,
  background: watermarkLayer,
)

#set text(
  font: textFont,
  size: $fontsize$,
  fill: bodyColor,
  lang: "$lang$",
  hyphenate: true,
)

#set par(
  justify: $if(justify)$true$else$false$endif$,
  leading: $linestretch$,
  spacing: 1.05em,
)

$if(section-numbering)$
#set heading(numbering: "$section-numbering$")
$endif$

// --- Titoli ----------------------------------------------------------------
#show heading: set block(above: 1.5em, below: 0.75em)
#show heading: set par(justify: false)
#show heading: set text(font: headingFont, fill: accent, weight: 700)

#show heading.where(level: 1): it => block(width: 100%, breakable: false, {
  text(size: 1.55em, it)
  v(-0.5em)
  line(length: 100%, stroke: 0.8pt + accent.lighten(55%))
})
#show heading.where(level: 2): set text(size: 1.22em)
#show heading.where(level: 3): set text(size: 1.05em)
#show heading.where(level: 4): set text(size: 1em, style: "italic")

// --- Codice ----------------------------------------------------------------
// L'evidenziazione della sintassi e' nativa di Typst: non serve nessuna
// libreria, basta che il blocco Markdown indichi il linguaggio (```python).
#show raw.where(block: true): it => block(
  width: 100%,
  fill: codeBg,
  inset: (x: 10pt, y: 9pt),
  radius: (right: 3pt),
  stroke: (left: 2.5pt + accent, rest: 0.5pt + ruleColor),
  breakable: true,
  text(font: codeFont, size: $codesize$, it),
)

#show raw.where(block: false): it => box(
  fill: codeBg,
  inset: (x: 0.35em),
  outset: (y: 0.3em),
  radius: 2pt,
  // Il colore va imposto: dentro l'intestazione di una tabella il testo e'
  // bianco, e senza questo il codice inline sparirebbe sul proprio sfondo chiaro.
  text(font: codeFont, size: 0.9em, fill: bodyColor, it),
)

// --- Tabelle ---------------------------------------------------------------
// table.header e' emesso da pandoc e Typst lo ripete automaticamente su ogni
// pagina quando la tabella e' piu' lunga di una facciata.
#set table(
  inset: (x: 7pt, y: 6pt),
  stroke: (x, y) => (bottom: 0.4pt + ruleColor),
  fill: (x, y) => if y == 0 { accentSoft },
)
// Le tabelle hanno un corpo piu' piccolo del testo (tablesize) e parole sempre
// intere: la sillabazione spezza i termini in colonne gia' strette, e la
// giustificazione vi aprirebbe spazi vistosi.
#show table: it => {
  set text(size: $if(tablesize)$$tablesize$$else$1em$endif$,
           hyphenate: $if(table-hyphenate)$true$else$false$endif$)
  set par(justify: false)
  it
}

#show table.cell.where(y: 0): set text(weight: 600, fill: accent)

// --- Citazioni, link, figure -----------------------------------------------
#show quote.where(block: true): it => block(
  width: 100%,
  inset: (left: 12pt, y: 6pt),
  stroke: (left: 2.5pt + accent.lighten(45%)),
  text(fill: mutedColor, style: "italic", it.body),
)

#show link: set text(fill: accent)

#show figure.caption: set text(size: 8.6pt, fill: mutedColor)
#show figure: set block(above: 1.3em, below: 1.3em)

// ===========================================================================
// Copertina
// ===========================================================================
$if(cover)$
#page(
  header: none,
  footer: none,
  numbering: none,
  margin: (top: 4.2cm, bottom: 3cm, x: $margin-x$),
)[
  #logoAt($logo-cover-height$)

  #v(2.2cm)
  // Il filetto e, alla sua destra sulla stessa linea, icona ed etichetta del
  // tipo di documento (doc-type). Senza icona resta il solo filetto.
  #if bloccoTipoDocumento != none {
    grid(
      columns: (28%, auto),
      column-gutter: 0.5cm,
      align: (left + horizon, left + horizon),
      line(length: 100%, stroke: 3pt + accent),
      bloccoTipoDocumento,
    )
  } else {
    line(length: 28%, stroke: 3pt + accent)
  }
  #v(0.5cm)

  #set par(justify: false)
  #text(size: 30pt, weight: 700, fill: accent, hyphenate: false)[
    $if(title)$$title$$else$Documento$endif$
  ]

  $if(subtitle)$
  #v(0.35cm)
  #text(size: 15pt, fill: mutedColor, hyphenate: false)[$subtitle$]
  $endif$

  #v(1fr)

  #grid(
    columns: (1fr, auto),
    align: (left + bottom, right + bottom),
    text(size: 10pt, fill: bodyColor)[
      $if(author)$$for(author)$$author$$sep$ \ $endfor$$endif$
    ],
    text(size: 10pt, fill: mutedColor)[$if(date)$$date$$endif$],
  )
  #v(0.3cm)
  #line(length: 100%, stroke: 0.5pt + ruleColor)
  #v(-2pt)
  #text(size: 8pt, fill: mutedColor)[$if(footer-text)$$footer-text$$endif$]
]
// La copertina non e' numerata: il conteggio riparte dal contenuto.
#counter(page).update(1)
$else$
// Senza copertina il titolo apre la prima pagina.
$if(title)$
#block(width: 100%, below: 1.4em)[
  #set par(justify: false)
  #grid(
    columns: (1fr, auto),
    column-gutter: 12pt,
    align: (left + horizon, right + horizon),
    text(size: 21pt, weight: 700, fill: accent, hyphenate: false)[$title$],
    logoAt($logo-cover-height$ * 0.45),
  )
  $if(subtitle)$
  #v(0.15cm)
  #text(size: 12pt, fill: mutedColor)[$subtitle$]
  $endif$
  #v(0.2cm)
  #line(length: 100%, stroke: 1.5pt + accent)
  $if(author)$
  #v(-4pt)
  #text(size: 9pt, fill: mutedColor)[$for(author)$$author$$sep$, $endfor$$if(date)$ · $date$$endif$]
  $endif$
]
$endif$
$endif$

// ===========================================================================
// Indice
// ===========================================================================
$if(toc)$
#block(breakable: false)[
  #text(size: 1.3em, weight: 700, fill: accent)[Indice]
  #v(0.3em)
  #line(length: 100%, stroke: 0.8pt + accent.lighten(55%))
]
#v(0.6em)
#show outline.entry.where(level: 1): set text(weight: 600)
#outline(title: none, depth: $if(toc-depth)$$toc-depth$$else$3$endif$, indent: auto)
#pagebreak()
$endif$

$for(include-before)$
$include-before$
$endfor$

// ===========================================================================
// Corpo del documento
// ===========================================================================
$body$

$for(include-after)$
$include-after$
$endfor$
