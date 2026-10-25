"""
impagina_api — il servizio HTTP di impagina.

Il nome usa il trattino basso, a differenza degli altri file del progetto,
perche' un pacchetto Python con il trattino non si puo' importare.

  configurazione  variabili d'ambiente, validate all'avvio
  chiavi          chiavi di accesso nominate (impronte SHA-256)
  errori          errori HTTP e corrispondenza con i codici di uscita
  percorsi        nomi di file ricevuti dal client resi sicuri
  multipart       lettore multipart/form-data in streaming
  archivi         estrazione ZIP sicura e ZIP dei risultati
  lavori          lavori, coda, esecutori e pulizia
  server          il server HTTP e gli endpoint
"""

from impagina import __version__  # una sola versione per CLI e servizio

__all__ = ["__version__"]
