"""
Nomi di file ricevuti dal client resi sicuri.

Il client indica il percorso relativo di ogni allegato (nel filename di una
parte multipart, o nelle voci di uno ZIP): e' cio' che permette al Markdown
di trovare immagini/schema.png. Lo stesso nome, se non controllato, e' anche
il modo classico per scrivere fuori dalla cartella del lavoro (../../x,
/etc/x, C:\\x). Qui passano tutti, sia da multipart sia da ZIP.
"""

import os
import re
from pathlib import Path, PurePosixPath

from .errori import ErroreRichiesta

MAX_COMPONENTE = 255      # byte, il limite dei filesystem comuni
MAX_PERCORSO = 1024       # byte
MAX_PROFONDITA = 16

# File che i sistemi operativi aggiungono agli archivi: si saltano in silenzio.
_SPAZZATURA = {".DS_Store", "Thumbs.db", "desktop.ini"}
_CONTROLLO_RE = re.compile(r"[\x00-\x1f\x7f]")
_UNITA_RE = re.compile(r"^[A-Za-z]:")


def _non_valido(nome, motivo):
    return ErroreRichiesta(
        400, "percorso_non_valido",
        "percorso non valido: '%s' (%s)." % (nome, motivo),
        "Usa percorsi relativi al documento, per esempio immagini/schema.png.")


def percorso_sicuro(nome):
    """
    PurePosixPath relativo e normalizzato, oppure None se il file va saltato
    (spazzatura dei sistemi operativi). Solleva ErroreRichiesta se il nome
    prova a uscire dalla cartella o non e' rappresentabile.
    """
    if nome is None or not nome.strip():
        raise _non_valido(nome or "", "nome vuoto")
    if _CONTROLLO_RE.search(nome):
        raise _non_valido(nome.encode("unicode_escape").decode("ascii"),
                          "caratteri di controllo")
    normale = nome.replace("\\", "/")      # archivi creati su Windows
    if normale.startswith("/") or _UNITA_RE.match(normale):
        raise _non_valido(nome, "percorso assoluto")
    parti = []
    for parte in normale.split("/"):
        if parte in ("", "."):
            continue
        if parte == "..":
            raise _non_valido(nome, "risale di cartella con '..'")
        if len(parte.encode("utf-8", "surrogateescape")) > MAX_COMPONENTE:
            raise _non_valido(nome, "nome troppo lungo")
        parti.append(parte)
    if not parti:
        raise _non_valido(nome, "nome vuoto")
    if len(parti) > MAX_PROFONDITA:
        raise _non_valido(nome, "troppe sottocartelle")
    if len("/".join(parti).encode("utf-8", "surrogateescape")) > MAX_PERCORSO:
        raise _non_valido(nome, "percorso troppo lungo")
    if parti[0] == "__MACOSX" or parti[-1] in _SPAZZATURA \
            or parti[-1].startswith("._"):
        return None
    return PurePosixPath(*parti)


class Budget:
    """Byte e file ancora ammessi per un lavoro."""

    def __init__(self, byte_max, file_max, messaggio_byte=None):
        self.byte_restanti = byte_max
        self.file_restanti = file_max
        self.byte_max = byte_max
        self.file_max = file_max
        self.messaggio_byte = messaggio_byte

    def nuovo_file(self):
        self.file_restanti -= 1
        if self.file_restanti < 0:
            raise ErroreRichiesta(
                413, "troppi_file",
                "troppi file: il limite e' %d per lavoro." % self.file_max)

    def consuma(self, quanti):
        self.byte_restanti -= quanti
        if self.byte_restanti < 0:
            raise ErroreRichiesta(
                413, "troppo_grande",
                self.messaggio_byte or
                "i file superano il limite di %s." % leggibile(self.byte_max))


def leggibile(byte):
    for unita, fattore in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if byte >= fattore:
            return "%g %s" % (round(byte / fattore, 1), unita)
    return "%d byte" % byte


def scrivi_file_sicuro(radice, relativo, blocchi, budget):
    """
    Scrive i blocchi in radice/relativo. Il file non deve esistere gia'
    (O_EXCL: due allegati con lo stesso percorso sono un errore) e non si
    seguono collegamenti simbolici (O_NOFOLLOW). Come difesa in piu' si
    verifica che il percorso risolto resti dentro la radice.
    """
    destinazione = Path(radice, *relativo.parts)
    radice_reale = Path(radice).resolve()
    try:
        destinazione.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except (FileExistsError, NotADirectoryError):
        raise _non_valido(str(relativo), "una cartella del percorso e' gia' un file")
    reale = destinazione.parent.resolve() / destinazione.name
    if radice_reale != reale and radice_reale not in reale.parents:
        raise _non_valido(str(relativo), "esce dalla cartella del lavoro")
    budget.nuovo_file()
    try:
        fd = os.open(destinazione,
                     os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise ErroreRichiesta(400, "percorso_non_valido",
                              "il file '%s' compare due volte." % relativo)
    with os.fdopen(fd, "wb") as uscita:
        for blocco in blocchi:
            budget.consuma(len(blocco))
            uscita.write(blocco)
    return destinazione
