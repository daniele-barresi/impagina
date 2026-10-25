"""
Chiavi di accesso nominate.

Il file (di norma /etc/impagina/chiavi.conf) ha una chiave per riga:

  # nome         impronta del token
  nextcloud      sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08

Il file contiene l'impronta SHA-256 del token e non il token: la conversione
gira con lo stesso utente del server e un documento malevolo che riuscisse a
leggere il file non otterrebbe nulla di utilizzabile. I token sono casuali a
256 bit, quindi un sale non servirebbe.

Revocare una chiave significa cancellare o commentare la sua riga: il file
viene riletto quando cambia, senza riavviare il servizio. Il nome della
chiave finisce nei log, il token mai.
"""

import hashlib
import hmac
import re
import sys
import threading

_NOME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_IMPRONTA_RE = re.compile(r"^sha256:([0-9a-f]{64})$")


def impronta(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RegistroChiavi:
    def __init__(self, percorso):
        self.percorso = percorso
        self._lock = threading.Lock()
        self._voci = []          # [(nome, impronta)]
        self._firma = None       # (inode, mtime_ns, size) dell'ultima lettura
        self.ricarica(obbligatorio=True)

    def ricarica(self, obbligatorio=False):
        """Rilegge il file se e' cambiato. All'avvio un file assente o vuoto
        e' un errore: un servizio senza chiavi non deve partire aperto."""
        try:
            info = self.percorso.stat()
        except OSError as exc:
            if obbligatorio:
                raise ValueError("file delle chiavi non leggibile: %s (%s)."
                                 % (self.percorso, exc.strerror or exc))
            # Sparito dopo l'avvio: nessuna chiave valida (si fallisce chiusi).
            with self._lock:
                if self._voci:
                    print("Attenzione: %s non e' piu' leggibile, tutte le "
                          "richieste saranno rifiutate." % self.percorso,
                          file=sys.stderr)
                self._voci, self._firma = [], None
            return

        firma = (info.st_ino, info.st_mtime_ns, info.st_size)
        if firma == self._firma:
            return
        try:
            voci, problemi = self._leggi()
        except OSError as exc:
            if obbligatorio:
                raise ValueError("file delle chiavi non leggibile: %s (%s)."
                                 % (self.percorso, exc.strerror or exc))
            print("Attenzione: %s non leggibile (%s), restano valide le chiavi "
                  "lette in precedenza." % (self.percorso, exc.strerror or exc),
                  file=sys.stderr)
            return
        if obbligatorio and not voci:
            raise ValueError("nessuna chiave valida in %s.%s" % (
                self.percorso, "".join("\n  " + p for p in problemi)))
        for problema in problemi:
            print("Attenzione: %s" % problema, file=sys.stderr)
        with self._lock:
            self._voci, self._firma = voci, firma

    def _leggi(self):
        voci, problemi, nomi = [], [], set()
        testo = self.percorso.read_text(encoding="utf-8", errors="replace")
        for numero, riga in enumerate(testo.splitlines(), start=1):
            riga = riga.split("#", 1)[0].strip()
            if not riga:
                continue
            parti = riga.split()
            if len(parti) != 2 or not _NOME_RE.match(parti[0]) \
                    or not _IMPRONTA_RE.match(parti[1]):
                problemi.append("%s, riga %d: formato atteso 'nome sha256:<64 "
                                "cifre esadecimali>', riga ignorata."
                                % (self.percorso, numero))
                continue
            if parti[0] in nomi:
                problemi.append("%s, riga %d: la chiave '%s' e' ripetuta, "
                                "riga ignorata." % (self.percorso, numero, parti[0]))
                continue
            nomi.add(parti[0])
            voci.append((parti[0], _IMPRONTA_RE.match(parti[1]).group(1)))
        return voci, problemi

    def verifica(self, intestazione):
        """Nome della chiave se l'header Authorization e' valido, altrimenti None."""
        self.ricarica()
        if not intestazione:
            return None
        schema, _, token = intestazione.strip().partition(" ")
        token = token.strip()
        if schema.lower() != "bearer" or not token:
            return None
        cercata = impronta(token)
        with self._lock:
            voci = list(self._voci)
        # Confronto a tempo costante su tutte le voci, senza uscire prima:
        # il tempo di risposta non rivela quale chiave e' andata vicina.
        trovato = None
        for nome, attesa in voci:
            if hmac.compare_digest(cercata, attesa) and trovato is None:
                trovato = nome
        return trovato
