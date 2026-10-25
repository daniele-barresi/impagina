--[[
  dipendenze.lua — impagina

  Writer personalizzato di pandoc (si usa con -t dipendenze.lua, non come
  filtro): invece di un documento produce, in JSON, l'elenco dei file che il
  Markdown referenzia. Serve al servizio API (POST /dipendenze) perche' chi
  invia un documento sappia quali immagini allegare, senza dover interpretare
  il Markdown per conto suo.

  Un writer e non un filtro perche' qui l'uscita e' il JSON stesso: un filtro
  dovrebbe comunque produrre un documento in qualche formato.

  Uscita:
    { "file":      [ {"percorso": "immagini/a.svg", "tipo": "immagine"} ],
      "ignorati":  [ {"riferimento": "...", "stato": "remoto|esterno", "motivo": "..."} ],
      "typst_grezzo": false }

  I percorsi sono normalizzati (senza ./ e ..) e senza duplicati: sono gli
  stessi che il client dovra' usare come nome dei file allegati.
--]]

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
  return table.concat(parti, "/")
end

function Writer(doc, opts)
  local file, ignorati, visti = {}, {}, {}
  local typst_grezzo = false

  local function aggiungi(rif, tipo)
    if rif == nil or rif == "" or rif:match("^data:") then
      return
    end
    local voce
    if rif:match("^%a[%w+.%-]*:") then
      voce = { riferimento = rif, stato = "remoto",
               motivo = "Typst non scarica file remoti: scaricalo e allegalo." }
    elseif rif:sub(1, 1) == "/" then
      voce = { riferimento = rif, stato = "esterno",
               motivo = "Percorso assoluto: usa un percorso relativo al documento." }
    else
      local percorso = normalizza(rif)
      if percorso == nil or percorso == "" then
        voce = { riferimento = rif, stato = "esterno",
                 motivo = "Il percorso esce dalla cartella del documento." }
      elseif not visti[percorso] then
        visti[percorso] = true
        table.insert(file, { percorso = percorso, tipo = tipo })
      end
    end
    if voce and not visti[rif] then
      visti[rif] = true
      table.insert(ignorati, voce)
    end
  end

  local function grezzo(el)
    if el.format == "typst" then typst_grezzo = true end
  end

  doc:walk({
    Image = function(el) aggiungi(el.src, "immagine") end,
    RawBlock = grezzo,
    RawInline = grezzo,
  })

  local icona = doc.meta["doc-icon"]
  if icona ~= nil then
    aggiungi(pandoc.utils.stringify(icona), "doc-icon")
  end

  return pandoc.json.encode({
    file = #file > 0 and file or pandoc.List({}),
    ignorati = #ignorati > 0 and ignorati or pandoc.List({}),
    typst_grezzo = typst_grezzo,
  }) .. "\n"
end
