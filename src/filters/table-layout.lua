--[[
  table-layout.lua — impagina

  Pandoc ricava la larghezza delle colonne dalla riga dei trattini del sorgente
  Markdown, in proporzione alla loro lunghezza:

      | Voce | Descrizione |
      |---|---|                        -> 50% e 50%
      |:-----|:--------------------|    -> 20% e 80%

  Quando i trattini sono tutti uguali quelle percentuali non dicono nulla sul
  contenuto: una colonna che contiene "99,20 %" riceve lo stesso spazio di una
  che contiene tre righe di testo, e le parole vi vanno continuamente a capo.
  In quel caso il filtro azzera le larghezze, cosi' pandoc emette "columns: N" e
  la larghezza la decide Typst in base al contenuto.

  Se invece i trattini hanno lunghezze diverse, l'autore sta indicando delle
  proporzioni: vengono lasciate passare intatte. Vale anche per le grid table,
  dove le proporzioni sono quelle del disegno.
--]]

-- Due larghezze si considerano uguali entro un punto percentuale: i valori sono
-- numeri in virgola mobile (tre colonne "uguali" valgono 0.3333... ciascuna).
local TOLLERANZA = 0.01

local function larghezze_uniformi(colspecs)
  local prima = colspecs[1][2]
  if prima == nil then return true end   -- nessuna larghezza: gia' automatiche
  for _, colspec in ipairs(colspecs) do
    local larghezza = colspec[2]
    -- Un misto di colonne con e senza larghezza non e' un'indicazione
    -- attendibile: si torna al dimensionamento automatico.
    if larghezza == nil then return true end
    if math.abs(larghezza - prima) > TOLLERANZA then return false end
  end
  return true
end

function Table(tbl)
  if larghezze_uniformi(tbl.colspecs) then
    for _, colspec in ipairs(tbl.colspecs) do
      colspec[2] = nil   -- ColWidthDefault: la larghezza la decide Typst
    end
  end
  return tbl
end
