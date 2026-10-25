// ===========================================================================
// impagina — template "minimo", solo per la suite di verifica
//
// Il piu' piccolo template utile: serve a provare il caricamento dei template
// esterni (IMPAGINA_TEMPLATES_PATH) e l'uso dei font della cartella fonts/.
// Per un template da cui partire guarda templates/company.
// ===========================================================================

#let divider() = line(length: 100%, stroke: 0.5pt)

$if(highlighting-definitions)$
$highlighting-definitions$
$endif$

#set document(title: [$if(title)$$title$$endif$])
#set page(paper: "a4", margin: 2cm)
#set text(font: "$mainfont$", size: 11pt, lang: "it")

#text(size: 8pt)[Template minimo]

$if(title)$
#text(size: 18pt, weight: "bold")[$title$]
$endif$

$body$
