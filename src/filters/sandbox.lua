--[[
  sandbox.lua — impagina

  Attivo solo con --sandbox, cioe' quando il documento arriva da qualcuno che
  non e' chi gestisce il server (la modalita' API). Il template e' un sorgente
  Typst in cui pandoc incolla i metadati cosi' come sono: un valore come
  fontsize: "11pt, fill: red" finirebbe tale e quale nel codice, e da li' un
  documento potrebbe leggere file del container con read(). Il filtro:

    - verifica ogni metadato in base al contesto in cui il template lo usa
      (colore, lunghezza, stringa, ...), sul testo gia' reso dal writer typst,
      cioe' esattamente quello che finira' nel template;
    - rifiuta il Typst grezzo (```{=typst} e `...`{=typst}), che puo' fare
      qualunque cosa; l'estensione raw_attribute resta attiva di proposito,
      cosi' l'utente riceve questo errore esplicito invece di vedere il
      codice stampato nel PDF;
    - accetta solo immagini con percorso relativo che resta dentro la cartella
      del lavoro (IMPAGINA_SANDBOX_RADICE).

  Deve girare PRIMA di resolve-paths.lua, che rende i percorsi assoluti.
  Ogni errore inizia con "impagina-sandbox:" perche' impagina.py lo riconosca
  e lo traduca in un messaggio per l'utente.

  Ogni variabile usata nei template inclusi deve comparire in CONTESTI (la
  suite di test lo verifica). Per i template personalizzati, impagina.py
  passa in IMPAGINA_SANDBOX_VARIABILI le variabili che il template usa: quelle
  non classificate accettano solo lettere, cifre, spazi e . - _ / %, cioe'
  nulla che in Typst possa chiamare una funzione o chiudere una stringa.
--]]

local CONTESTI = {
  -- rgb("#$x$"): solo cifre esadecimali
  ["accent"] = "colore", ["accent-soft"] = "colore", ["code-bg"] = "colore",
  ["cover-bg"] = "colore", ["cover-bg-2"] = "colore", ["cover-muted"] = "colore",
  ["cover-text"] = "colore", ["muted-color"] = "colore", ["rule-color"] = "colore",
  ["text-color"] = "colore",

  -- size: $x$, margin: (top: $x$ ...): un numero con unita' di misura
  ["codesize"] = "lunghezza", ["doc-icon-size"] = "lunghezza",
  ["fontsize"] = "lunghezza", ["linestretch"] = "lunghezza",
  ["logo-cover-height"] = "lunghezza", ["logo-cover-width"] = "lunghezza",
  ["logo-header-height"] = "lunghezza", ["logo-header-width"] = "lunghezza",
  ["margin-bottom"] = "lunghezza", ["margin-top"] = "lunghezza",
  ["margin-x"] = "lunghezza", ["tablesize"] = "lunghezza",

  ["cover-angle"] = "angolo",
  ["toc-depth"] = "intero",

  -- "$x$": dentro una stringa Typst, dove pandoc non fa escape delle virgolette
  ["codefont"] = "stringa", ["headingfont"] = "stringa", ["mainfont"] = "stringa",
  ["lang"] = "stringa", ["papersize"] = "stringa", ["page-numbering"] = "stringa",
  ["section-numbering"] = "stringa", ["cover-style"] = "stringa",
  ["doc-type"] = "stringa", ["doc-label"] = "stringa",
  ["docdir"] = "stringa", ["iconspath"] = "stringa", ["logopath"] = "stringa",
  ["doc-icon"] = "percorso",

  -- [$x$] o testo a livello di pagina: il writer typst fa gia' l'escape
  ["title"] = "contenuto", ["subtitle"] = "contenuto", ["author"] = "contenuto",
  ["date"] = "contenuto", ["footer-text"] = "contenuto",
  ["cover-info"] = "contenuto", ["watermark"] = "contenuto",
  ["include-before"] = "contenuto", ["include-after"] = "contenuto",
  ["highlighting-definitions"] = "contenuto", ["body"] = "contenuto",

  -- usate solo in $if(x)$: il valore non entra mai nel sorgente
  ["cover"] = "condizione", ["toc"] = "condizione", ["justify"] = "condizione",
  ["table-hyphenate"] = "condizione", ["header-rule"] = "condizione",
  ["footer-rule"] = "condizione", ["doc-hide-label"] = "condizione",
}

local UNITA_LUNGHEZZA = { pt = true, mm = true, cm = true, ["in"] = true,
                          em = true, ["%"] = true }
local UNITA_ANGOLO = { deg = true, rad = true }

local RADICE = os.getenv("IMPAGINA_SANDBOX_RADICE")

local USATE = {}
for nome in (os.getenv("IMPAGINA_SANDBOX_VARIABILI") or ""):gmatch("[^,]+") do
  USATE[nome] = true
end

local function rifiuta(messaggio)
  error("impagina-sandbox: " .. messaggio, 0)
end

-- Il testo che il template ricevera' davvero per questo valore.
local function reso(valore)
  local tipo = pandoc.utils.type(valore)
  if tipo == "string" then
    return valore
  elseif tipo == "Inlines" then
    local testo = pandoc.write(pandoc.Pandoc({ pandoc.Plain(valore) }), "typst")
    return (testo:gsub("%s+$", ""))
  end
  return nil  -- booleani, liste, blocchi: gestiti dal chiamante
end

local function numero_con_unita(testo, unita)
  local numero, suffisso = testo:match("^(%d*%.?%d+)(%%?%a*)$")
  return numero ~= nil and unita[suffisso] == true
end

local VALIDI = {
  colore = function(t)
    return t:match("^%x+$") ~= nil and (#t == 3 or #t == 4 or #t == 6 or #t == 8)
  end,
  lunghezza = function(t) return numero_con_unita(t, UNITA_LUNGHEZZA) end,
  angolo = function(t) return numero_con_unita(t, UNITA_ANGOLO) end,
  intero = function(t) return t:match("^%d+$") ~= nil end,
  stringa = function(t) return not t:find('["\\%c]') end,
  generico = function(t) return t:match("^[%w%s%.%-_/%%]*$") ~= nil end,
}

local SPIEGAZIONI = {
  colore = "un colore esadecimale senza '#', es. 1F4E79",
  lunghezza = "un numero con unita' di misura (pt, mm, cm, in, em, %), es. 10.5pt",
  angolo = "un angolo, es. 315deg",
  intero = "un numero intero",
  stringa = "un testo senza virgolette doppie ne' barre inverse",
  percorso = "un percorso relativo senza virgolette doppie ne' barre inverse",
  generico = "un testo semplice (lettere, cifre, spazi e . - _ / %)",
}

-- Percorso normalizzato (senza . e ..) oppure nil se sale oltre la radice "/".
local function normalizza(percorso)
  local parti = {}
  for parte in percorso:gmatch("[^/]+") do
    if parte == ".." then
      if #parti == 0 then return nil end
      table.remove(parti)
    elseif parte ~= "." then
      table.insert(parti, parte)
    end
  end
  return "/" .. table.concat(parti, "/")
end

local function cartella_documento()
  local file = PANDOC_STATE.input_files[1] or ""
  return file:match("^(.*)/[^/]*$") or "."
end

-- Un riferimento a un file (immagine o doc-icon) e' ammesso solo se relativo
-- e se, risolto rispetto alla cartella del documento, resta nella radice.
local function verifica_riferimento(rif, cosa)
  if rif:find('["\\%c]') then
    rifiuta(string.format("%s '%s': il percorso contiene caratteri non ammessi.", cosa, rif))
  end
  if rif:match("^%a[%w+.%-]*:") then
    rifiuta(string.format("%s '%s': i riferimenti remoti non sono ammessi, "
      .. "allega il file.", cosa, rif))
  end
  if rif:sub(1, 1) == "/" then
    rifiuta(string.format("%s '%s': i percorsi assoluti non sono ammessi, "
      .. "usa un percorso relativo al documento.", cosa, rif))
  end
  local radice = normalizza(RADICE or "/")
  local completo = normalizza(cartella_documento() .. "/" .. rif)
  if completo == nil or (completo ~= radice
      and completo:sub(1, #radice + 1) ~= radice .. "/") then
    rifiuta(string.format("%s '%s': il percorso esce dalla cartella del documento.",
      cosa, rif))
  end
end

function Meta(meta)
  for chiave, valore in pairs(meta) do
    local contesto = CONTESTI[chiave] or (USATE[chiave] and "generico")
    local tipo = pandoc.utils.type(valore)
    if not contesto then
      -- Chiave che il template non usa: pandoc non la incolla da nessuna parte.
    elseif contesto == "contenuto" or contesto == "condizione" then
      -- gia' sicure
    elseif tipo == "boolean" then
      -- un booleano in un contesto di valore produce "true"/"false": innocuo
    else
      local testo = reso(valore)
      local controllo = VALIDI[contesto] or VALIDI.stringa
      if testo == nil or not controllo(testo) then
        rifiuta(string.format("il metadato '%s' deve essere %s (trovato: %s).",
          chiave, SPIEGAZIONI[contesto],
          testo and ("'" .. testo .. "'") or tipo))
      end
      if contesto == "percorso" and testo ~= "" then
        verifica_riferimento(testo, "doc-icon")
      end
    end
  end
end

function Image(el)
  verifica_riferimento(el.src, "l'immagine")
end

local function grezzo(el)
  if el.format == "typst" then
    rifiuta("il documento contiene codice Typst grezzo, non ammesso in questa modalita'.")
  end
end
RawBlock = grezzo
RawInline = grezzo
