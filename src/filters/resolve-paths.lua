--[[
  resolve-paths.lua — impagina

  Il file .typ intermedio viene generato in una cartella temporanea, non
  accanto al documento Markdown. Typst risolve i percorsi relativi rispetto
  alla posizione del .typ, quindi senza questo filtro un'immagine scritta come
  ![](immagini/schema.png) non verrebbe trovata.

  Il filtro riscrive i percorsi relativi in percorsi assoluti basati sulla
  cartella del file Markdown di origine. URL, percorsi gia' assoluti e data URI
  vengono lasciati intatti.
--]]

local function dirname(path)
  return path:match("^(.*)/[^/]*$") or "."
end

local basedir = "."
if PANDOC_STATE and PANDOC_STATE.input_files and #PANDOC_STATE.input_files > 0 then
  basedir = dirname(PANDOC_STATE.input_files[1])
end

local function is_absolute_or_remote(src)
  return src:match("^/")            -- percorso assoluto
      or src:match("^%a[%w+.%-]*://") -- http://, https://, file://...
      or src:match("^data:")        -- data URI
end

function Image(el)
  if not is_absolute_or_remote(el.src) then
    el.src = basedir .. "/" .. el.src
  end
  return el
end
