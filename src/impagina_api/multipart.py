"""
Lettore multipart/form-data in streaming.

La libreria standard aveva cgi.FieldStorage, deprecato e rimosso in Python
3.13; in ogni caso caricava tutto in memoria o in file temporanei suoi. Qui
il corpo si legge a blocchi e ogni file va direttamente su disco, cosi' un
caricamento da 50 MB non occupa 50 MB di RAM.

Uso:

    for parte in leggi_parti(flusso, boundary):
        parte.nome, parte.filename       # dal Content-Disposition
        for blocco in parte.blocchi():   # il contenuto, a pezzi
            ...

Il contenuto di una parte va consumato prima di passare alla successiva;
se non lo si fa, il generatore lo scarta da se'.
"""

import email.message
import email.parser
import email.policy

from .errori import ErroreRichiesta

BLOCCO = 64 * 1024
MAX_INTESTAZIONI = 16 * 1024


def _non_valida(messaggio):
    return ErroreRichiesta(400, "richiesta_non_valida",
                           "corpo multipart non valido: %s." % messaggio)


def boundary_da(content_type):
    """Il boundary (bytes) dall'header Content-Type, validato come da RFC 2046."""
    messaggio = email.message.Message()
    messaggio["content-type"] = content_type
    boundary = messaggio.get_param("boundary")
    if not isinstance(boundary, str) or not 1 <= len(boundary) <= 70:
        raise _non_valida("boundary mancante o non valido")
    try:
        return boundary.encode("ascii")
    except UnicodeEncodeError:
        raise _non_valida("boundary non ASCII")


class LettoreLimitato:
    """Legge al massimo `lunghezza` byte: mai oltre il Content-Length."""

    def __init__(self, flusso, lunghezza):
        self.flusso = flusso
        self.restanti = lunghezza

    def read(self, quanti=BLOCCO):
        if self.restanti <= 0:
            return b""
        dati = self.flusso.read(min(quanti, self.restanti))
        if not dati:
            # Il client ha chiuso prima di mandare quanto annunciato.
            raise ErroreRichiesta(400, "richiesta_non_valida",
                                  "il corpo della richiesta e' incompleto.")
        self.restanti -= len(dati)
        return dati

    def scarta(self):
        while self.restanti > 0:
            self.read()


class Parte:
    def __init__(self, lettore, intestazioni):
        self._lettore = lettore
        self.nome = intestazioni.get_param("name", header="content-disposition")
        filename = intestazioni.get_filename()
        # I browser mandano i nomi non ASCII come UTF-8 grezzo: il parser li
        # decodifica con surrogateescape, qui si ricostruisce il testo.
        if filename is not None:
            filename = filename.encode("utf-8", "surrogateescape") \
                               .decode("utf-8", "replace")
        self.filename = filename
        self.tipo = intestazioni.get_content_type()
        self._consumata = False

    def blocchi(self):
        if self._consumata:
            return
        self._consumata = True
        yield from self._lettore.corpo_parte()

    def leggi_tutto(self, massimo):
        """Il contenuto intero, per i campi semplici (le opzioni)."""
        dati = bytearray()
        for blocco in self.blocchi():
            dati += blocco
            if len(dati) > massimo:
                raise _non_valida("il campo '%s' supera %d byte" % (self.nome, massimo))
        return bytes(dati)


class _Lettore:
    def __init__(self, flusso, boundary):
        self.flusso = flusso
        # Ogni delimitatore e' preceduto da CRLF, tranne il primo se il corpo
        # inizia subito con esso: aggiungere un CRLF in testa uniforma i casi.
        self.buf = bytearray(b"\r\n")
        self.delim = b"\r\n--" + boundary
        self.finito_flusso = False

    def _riempi(self):
        if self.finito_flusso:
            return False
        dati = self.flusso.read(BLOCCO)
        if not dati:
            self.finito_flusso = True
            return False
        self.buf += dati
        return True

    def corpo_parte(self):
        """
        Blocchi fino al prossimo delimitatore (escluso). Il delimitatore puo'
        arrivare spezzato fra due letture: per questo gli ultimi len(delim)-1
        byte restano sempre nel buffer finche' non si sa cosa sono.
        """
        riserva = len(self.delim) - 1
        while True:
            pos = self.buf.find(self.delim)
            if pos >= 0:
                if pos:
                    yield bytes(self.buf[:pos])
                del self.buf[:pos + len(self.delim)]
                return
            if len(self.buf) > riserva:
                taglio = len(self.buf) - riserva
                yield bytes(self.buf[:taglio])
                del self.buf[:taglio]
            if not self._riempi():
                raise _non_valida("manca il delimitatore finale")

    def dopo_delimitatore(self):
        """True se segue un'altra parte, False se e' il delimitatore finale."""
        while len(self.buf) < 2 and self._riempi():
            pass
        if self.buf[:2] == b"--":
            return False
        # RFC 2046: spazi ammessi fra il delimitatore e il CRLF.
        while True:
            fine = self.buf.find(b"\r\n")
            if fine >= 0:
                if self.buf[:fine].strip(b" \t"):
                    raise _non_valida("caratteri inattesi dopo il delimitatore")
                del self.buf[:fine + 2]
                return True
            if len(self.buf) > 1024 or not self._riempi():
                raise _non_valida("delimitatore malformato")

    def intestazioni(self):
        while True:
            fine = self.buf.find(b"\r\n\r\n")
            if fine >= 0:
                grezze = bytes(self.buf[:fine + 4])
                del self.buf[:fine + 4]
                return email.parser.BytesParser(policy=email.policy.HTTP) \
                                   .parsebytes(grezze, headersonly=True)
            if len(self.buf) > MAX_INTESTAZIONI:
                raise _non_valida("intestazioni di una parte troppo lunghe")
            if not self._riempi():
                raise _non_valida("intestazioni di una parte incomplete")


def leggi_parti(flusso, boundary, max_parti=1000):
    lettore = _Lettore(flusso, boundary)
    # Il preambolo prima del primo delimitatore si ignora.
    for _ in lettore.corpo_parte():
        pass
    contate = 0
    while lettore.dopo_delimitatore():
        contate += 1
        if contate > max_parti:
            raise ErroreRichiesta(413, "troppi_file",
                                  "la richiesta contiene troppe parti.")
        parte = Parte(lettore, lettore.intestazioni())
        if parte.nome is None:
            raise _non_valida("una parte non ha il nome del campo")
        yield parte
        for _ in parte.blocchi():   # scarta cio' che il chiamante non ha letto
            pass
