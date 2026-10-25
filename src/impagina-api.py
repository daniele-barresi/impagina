#!/usr/bin/env python3
"""
impagina-api — servizio HTTP che converte Markdown in PDF con impagina.

Riceve i documenti, li mette in coda e li converte uno alla volta (o N alla
volta, se configurato) eseguendo impagina.py come sottoprocesso. Si avvia di
norma dentro il container impagina-api: vedi compose.yaml e il README.

Usa solo la libreria standard, come impagina.py.
"""

import sys
from pathlib import Path

# Il pacchetto impagina_api e impagina.py vivono nella stessa cartella.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from impagina_api.server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
