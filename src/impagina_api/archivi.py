"""
Estrazione sicura degli ZIP ricevuti e creazione dello ZIP dei risultati.

zipfile.extractall non e' adatto a un archivio che arriva da fuori:
  - zip-slip: una voce "../../x" o "/etc/x" scrive fuori dalla destinazione
    (qui ogni nome passa da percorso_sicuro);
  - collegamenti simbolici: una voce symlink seguita da un file con lo
    stesso prefisso scrive dove punta il link (qui i symlink si rifiutano);
  - zip bomb: pochi KB che si espandono in GB. La dimensione dichiarata
    nell'archivio puo' mentire, quindi si contano i byte davvero estratti
    e ci si ferma al limite.
"""

import stat
import zipfile
import zlib
from pathlib import PurePosixPath

from .errori import ErroreRichiesta
from .percorsi import Budget, leggibile, percorso_sicuro, scrivi_file_sicuro

BLOCCO = 64 * 1024


def _zip_non_valido(messaggio, suggerimento=None):
    return ErroreRichiesta(422, "zip_non_valido", messaggio, suggerimento)


def _blocchi_verificati(archivio, voce):
    """Contenuto della voce, fermandosi se supera la dimensione dichiarata."""
    letti = 0
    with archivio.open(voce) as sorgente:
        while True:
            blocco = sorgente.read(BLOCCO)
            if not blocco:
                return
            letti += len(blocco)
            if letti > voce.file_size:
                raise ErroreRichiesta(
                    413, "troppo_grande",
                    "l'archivio e' malformato: '%s' e' piu' grande di quanto "
                    "dichiarato." % voce.filename)
            yield blocco


def estrai_zip(percorso_zip, destinazione, max_espanso, max_file):
    """
    Estrae l'archivio in `destinazione`. Se tutte le voci stanno sotto
    un'unica cartella (il caso tipico di "comprimi cartella"), quella cartella
    viene tolta. Restituisce l'elenco dei percorsi relativi estratti.
    """
    try:
        archivio = zipfile.ZipFile(percorso_zip)
    except (zipfile.BadZipFile, OSError):
        raise _zip_non_valido("il corpo non e' un archivio ZIP valido.")

    with archivio:
        voci = []
        visti = set()
        dichiarati = 0
        for voce in archivio.infolist():
            if voce.is_dir():
                continue
            if voce.flag_bits & 0x1:
                raise _zip_non_valido(
                    "l'archivio contiene file cifrati ('%s')." % voce.filename,
                    "Crea l'archivio senza password.")
            if stat.S_ISLNK(voce.external_attr >> 16):
                raise ErroreRichiesta(
                    400, "percorso_non_valido",
                    "l'archivio contiene un collegamento simbolico ('%s')."
                    % voce.filename,
                    "Includi i file veri e propri, non i collegamenti.")
            relativo = percorso_sicuro(voce.filename)
            if relativo is None:
                continue
            if relativo in visti:
                raise ErroreRichiesta(
                    400, "percorso_non_valido",
                    "il file '%s' compare due volte nell'archivio." % relativo)
            visti.add(relativo)
            dichiarati += voce.file_size
            voci.append((voce, relativo))

        if len(voci) > max_file:
            raise ErroreRichiesta(
                413, "troppi_file",
                "l'archivio contiene %d file: il limite e' %d."
                % (len(voci), max_file))
        messaggio = "l'archivio si espande oltre il limite di %s." \
                    % leggibile(max_espanso)
        if dichiarati > max_espanso:
            raise ErroreRichiesta(413, "troppo_grande", messaggio)

        # Un'unica cartella principale si toglie: note.zip con dentro note/...
        # si comporta come se si fosse compressa direttamente la cartella.
        primi = {relativo.parts[0] for _, relativo in voci}
        togli = len(primi) == 1 and all(len(r.parts) > 1 for _, r in voci)

        budget = Budget(max_espanso, max_file, messaggio)
        estratti = []
        for voce, relativo in voci:
            if togli:
                relativo = PurePosixPath(*relativo.parts[1:])
            try:
                scrivi_file_sicuro(destinazione, relativo,
                                   _blocchi_verificati(archivio, voce), budget)
            except (zipfile.BadZipFile, zlib.error, EOFError,
                    NotImplementedError) as exc:
                raise _zip_non_valido("impossibile estrarre '%s' (%s)."
                                      % (voce.filename, exc))
            estratti.append(relativo)
        return estratti


def crea_zip(file, destinazione):
    """
    ZIP dei risultati. I PDF sono gia' compressi: ZIP_STORED evita di
    sprecare CPU per guadagnare pochi byte.
    """
    with zipfile.ZipFile(destinazione, "w", compression=zipfile.ZIP_STORED) as zf:
        for percorso, nome in file:
            zf.write(percorso, nome)
