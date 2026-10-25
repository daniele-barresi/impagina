# Font del template

Questa cartella e' **vuota di proposito**.

L'immagine Docker include gia' **Inter** e **JetBrains Mono**, che sono i font
predefiniti del template `company`. Per usare i font aziendali:

1. copia qui i file `.ttf` o `.otf` (tutti i tagli che ti servono: Regular,
   Italic, Bold, BoldItalic...);
2. apri `../theme.yaml` e imposta `mainfont` / `codefont` con il **nome della
   famiglia** del font (quello che vedi in un gestore di font, ad es.
   `"Source Sans 3"`), non con il nome del file.

Non serve ricostruire l'immagine Docker: questa cartella viene passata a Typst
con `--font-path` a ogni esecuzione, e i font trovati qui hanno la precedenza
su quelli di sistema.

Verifica rapida che il font sia stato riconosciuto:

```bash
./impagina.sh examples/esempio.md --template company --verbose
```

Se il nome della famiglia e' sbagliato, Typst ripiega silenziosamente su un
font di sistema: controlla il PDF risultante con `pdffonts documento.pdf`.
