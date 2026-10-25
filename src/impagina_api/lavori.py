"""
Lavori, coda, esecutori e pulizia.

Ogni lavoro ha una cartella propria sotto <IMPAGINA_API_LAVORI>/lavori/<id>:

  stato.json       lo stato del lavoro, scritto in modo atomico
  sorgente/        i file ricevuti (Markdown e immagini)
  pdf/             dove impagina.py scrive i PDF
  tmp/             TMPDIR e HOME del sottoprocesso (i .typ intermedi)
  rapporto.json    l'esito scritto da impagina.py --report
  risultato.pdf    oppure risultato.zip, l'unica cosa che resta alla fine

Lo stato vive su disco (non solo in memoria) perche' il container puo'
ripartire: all'avvio i lavori in coda riprendono e i risultati pronti restano
scaricabili fino alla scadenza.

Consumo a riposo: gli esecutori dormono su una Condition senza timeout e non
si svegliano finche' non arriva un lavoro; solo lo spazzino si sveglia, ogni
IMPAGINA_API_PULIZIA_OGNI secondi.
"""

import collections
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .archivi import crea_zip
from .errori import errore_da_uscita

IN_CARICAMENTO = "in_caricamento"
IN_CODA = "in_coda"
IN_CORSO = "in_corso"
COMPLETATO = "completato"
FALLITO = "fallito"

ID_RE = re.compile(r"^[0-9a-f]{32}$")
IMPAGINA = Path(__file__).resolve().parent.parent / "impagina.py"
MAX_LOG = 64 * 1024
TENTATIVI_MAX = 2      # un lavoro interrotto due volte da un crash non riparte


def adesso():
    return time.time()


def log(messaggio):
    print("%s %s" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), messaggio),
          file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Il lavoro
# --------------------------------------------------------------------------

@dataclass
class Lavoro:
    id: str
    chiave: str
    stato: str = IN_CARICAMENTO
    creato: float = field(default_factory=adesso)
    iniziato: float = None
    terminato: float = None
    scade: float = None
    opzioni: dict = field(default_factory=dict)
    modo: str = "documento"          # "documento" (multipart) o "cartella" (ZIP)
    ingresso: str = ""               # relativo a sorgente/: "nota.md" o "."
    tentativi: int = 0
    esito: str = None                # ok | parziale | errore
    documenti: list = field(default_factory=list)
    errore: dict = None
    risultato: dict = None

    @classmethod
    def da_dict(cls, dati):
        nomi = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in dati.items() if k in nomi})


class Registro:
    """I lavori: su disco (la verita') e in memoria (per non rileggere)."""

    def __init__(self, radice, ttl):
        self.radice = Path(radice) / "lavori"
        self.radice.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ttl = ttl
        self._lavori = {}
        self._lock = threading.Lock()

    def cartella(self, id_lavoro):
        return self.radice / id_lavoro

    def nuovo(self, chiave):
        lavoro = Lavoro(id=uuid.uuid4().hex, chiave=chiave)
        cartella = self.cartella(lavoro.id)
        cartella.mkdir(mode=0o700)
        for nome in ("sorgente", "pdf", "tmp"):
            (cartella / nome).mkdir(mode=0o700)
        with self._lock:
            self._lavori[lavoro.id] = lavoro
        self.salva(lavoro)
        return lavoro

    def salva(self, lavoro):
        cartella = self.cartella(lavoro.id)
        provvisorio = cartella / ".stato.json.tmp"
        with self._lock:
            dati = json.dumps(asdict(lavoro), ensure_ascii=False)
        try:
            provvisorio.write_text(dati, encoding="utf-8")
            os.replace(provvisorio, cartella / "stato.json")
        except FileNotFoundError:
            pass    # eliminato nel frattempo (DELETE o scadenza)

    def trova(self, id_lavoro, chiave):
        """Il lavoro, solo se appartiene alla chiave: altrimenti None, cosi'
        un client non puo' nemmeno sapere che il lavoro di un altro esiste."""
        if not ID_RE.match(id_lavoro or ""):
            return None
        with self._lock:
            lavoro = self._lavori.get(id_lavoro)
        if lavoro is None or lavoro.chiave != chiave:
            return None
        return lavoro

    def elimina(self, id_lavoro):
        with self._lock:
            self._lavori.pop(id_lavoro, None)
        shutil.rmtree(self.cartella(id_lavoro), ignore_errors=True)

    def tutti(self):
        with self._lock:
            return list(self._lavori.values())

    def ripristina(self, coda):
        """All'avvio: ricarica i lavori lasciati dall'esecuzione precedente."""
        da_accodare = []
        for cartella in sorted(self.radice.iterdir()):
            if not ID_RE.match(cartella.name):
                continue
            try:
                lavoro = Lavoro.da_dict(json.loads(
                    (cartella / "stato.json").read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                shutil.rmtree(cartella, ignore_errors=True)
                continue
            if lavoro.stato == IN_CARICAMENTO:
                # Caricamento interrotto: il client ha gia' ricevuto un errore.
                shutil.rmtree(cartella, ignore_errors=True)
                continue
            if lavoro.stato == IN_CORSO:
                lavoro.tentativi += 1
                if lavoro.tentativi >= TENTATIVI_MAX:
                    termina_con_errore(lavoro, {
                        "codice": "interrotto",
                        "messaggio": "la conversione e' stata interrotta due "
                                     "volte dal riavvio del servizio.",
                        "suggerimento": "Il documento potrebbe richiedere piu' "
                                        "memoria di quella disponibile."},
                        self.ttl)
                    pulisci_lavorazione(cartella)
                else:
                    pulisci_lavorazione(cartella, tieni_sorgente=True)
                    lavoro.stato = IN_CODA
            with self._lock:
                self._lavori[lavoro.id] = lavoro
            self.salva(lavoro)
            if lavoro.stato == IN_CODA:
                da_accodare.append(lavoro)
        for lavoro in sorted(da_accodare, key=lambda l: l.creato):
            coda.inserisci(lavoro.id, forza=True)
        return len(da_accodare)


def pulisci_lavorazione(cartella, tieni_sorgente=False):
    """Toglie tutto cio' che serviva solo durante la conversione."""
    nomi = ["pdf", "tmp", "rapporto.json", "ingresso.zip"]
    if not tieni_sorgente:
        nomi.append("sorgente")
    for nome in nomi:
        percorso = cartella / nome
        if percorso.is_dir():
            shutil.rmtree(percorso, ignore_errors=True)
        else:
            percorso.unlink(missing_ok=True)
    if tieni_sorgente:
        for nome in ("pdf", "tmp"):
            (cartella / nome).mkdir(mode=0o700, exist_ok=True)


def termina_con_errore(lavoro, errore, ttl):
    lavoro.stato = FALLITO
    lavoro.esito = "errore"
    lavoro.errore = errore
    lavoro.terminato = adesso()
    lavoro.scade = lavoro.terminato + ttl


# --------------------------------------------------------------------------
# La coda
# --------------------------------------------------------------------------

class Coda:
    """
    FIFO di id. Non e' una queue.Queue perche' serve conoscere la posizione
    di un lavoro (per la risposta di GET) e poterlo togliere (per DELETE).
    """

    def __init__(self, massimo):
        self.massimo = massimo
        self._ids = collections.deque()
        self._cond = threading.Condition()
        self._chiusa = False

    def inserisci(self, id_lavoro, forza=False):
        with self._cond:
            if not forza and len(self._ids) >= self.massimo:
                return False
            self._ids.append(id_lavoro)
            self._cond.notify()
            return True

    def prendi(self):
        """Il prossimo id; blocca finche' non c'e'. None alla chiusura."""
        with self._cond:
            while not self._ids and not self._chiusa:
                self._cond.wait()
            if self._chiusa:
                return None
            return self._ids.popleft()

    def rimuovi(self, id_lavoro):
        with self._cond:
            try:
                self._ids.remove(id_lavoro)
                return True
            except ValueError:
                return False

    def posizione(self, id_lavoro):
        """1 = il prossimo a partire."""
        with self._cond:
            try:
                return self._ids.index(id_lavoro) + 1
            except ValueError:
                return None

    def lunghezza(self):
        with self._cond:
            return len(self._ids)

    def chiudi(self):
        with self._cond:
            self._chiusa = True
            self._cond.notify_all()


# --------------------------------------------------------------------------
# Esecuzione di impagina.py
# --------------------------------------------------------------------------

def argomenti(lavoro, cartella):
    """
    argv di impagina.py. Le opzioni con valore vanno sempre nella forma
    --opzione=valore: un watermark come "--templates-dir=/" passato come
    argomento separato verrebbe letto da argparse come un'opzione.
    """
    opzioni = lavoro.opzioni
    sorgente = cartella / "sorgente"
    ingresso = sorgente / lavoro.ingresso if lavoro.ingresso != "." else sorgente
    argv = [sys.executable, str(IMPAGINA),
            "--input=%s" % ingresso,
            "--output=%s/" % (cartella / "pdf"),
            "--template=%s" % opzioni.get("template", "company"),
            "--report=%s" % (cartella / "rapporto.json")]
    if opzioni.get("sandbox", True):
        argv.append("--sandbox")
    if opzioni.get("toc"):
        argv.append("--toc")
    if opzioni.get("cover") is True:
        argv.append("--cover")
    elif opzioni.get("cover") is False:
        argv.append("--no-cover")
    if opzioni.get("watermark"):
        argv.append("--watermark=%s" % opzioni["watermark"])
    if opzioni.get("recursive"):
        argv.append("--recursive")
    return argv


def ambiente(cfg, cartella):
    """
    Ambiente del sottoprocesso: solo le variabili elencate. Nessuna variabile
    IMPAGINA_API_* ne' altro del server arriva alla conversione.
    """
    tmp = str(cartella / "tmp")
    return dict(cfg.variabili_template, **{
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": tmp,
        "TMPDIR": tmp,
        "XDG_CACHE_HOME": tmp + "/.cache",
        # I messaggi mostrano ./immagini/x.png, non i percorsi del server.
        "IMPAGINA_DISPLAY_MAP": "%s/sorgente=.\n%s/pdf=.\n%s=(lavoro)"
                                % (cartella, cartella, cartella),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    })


def _relativo(testo):
    return testo[2:] if testo and testo.startswith("./") else testo


class Esecutore(threading.Thread):
    """Uno per conversione parallela: IMPAGINA_API_WORKER thread in tutto."""

    def __init__(self, numero, cfg, registro, coda):
        super().__init__(name="esecutore-%d" % numero, daemon=True)
        self.cfg = cfg
        self.registro = registro
        self.coda = coda
        self.processo = None
        self.in_chiusura = False

    def run(self):
        while True:
            id_lavoro = self.coda.prendi()
            if id_lavoro is None:
                return
            with self.registro._lock:
                lavoro = self.registro._lavori.get(id_lavoro)
            if lavoro is None or lavoro.stato != IN_CODA:
                continue    # eliminato mentre era in coda
            try:
                self.esegui(lavoro)
            except Exception as exc:   # un bug non deve fermare l'esecutore
                log("lavoro %s: errore interno: %r" % (lavoro.id, exc))
                termina_con_errore(lavoro, {
                    "codice": "errore_interno",
                    "messaggio": "errore interno del servizio.",
                    "suggerimento": None}, self.cfg.ttl)
                pulisci_lavorazione(self.registro.cartella(lavoro.id))
                self.registro.salva(lavoro)

    def ferma(self):
        """Allo spegnimento: interrompe la conversione in corso."""
        self.in_chiusura = True
        processo = self.processo
        if processo is not None and processo.poll() is None:
            try:
                os.killpg(processo.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def esegui(self, lavoro):
        cartella = self.registro.cartella(lavoro.id)
        lavoro.stato = IN_CORSO
        lavoro.iniziato = adesso()
        self.registro.salva(lavoro)

        # start_new_session: pandoc e typst finiscono nello stesso gruppo di
        # processi, cosi' al timeout si ferma tutto e non solo impagina.py.
        self.processo = subprocess.Popen(
            argomenti(lavoro, cartella), cwd=cartella / "sorgente",
            env=ambiente(self.cfg, cartella), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True)
        scaduto = False
        try:
            uscita, _ = self.processo.communicate(timeout=self.cfg.timeout)
        except subprocess.TimeoutExpired:
            scaduto = True
            self._termina_gruppo()
            uscita, _ = self.processo.communicate()
        codice = self.processo.returncode
        self.processo = None

        if self.in_chiusura and not scaduto:
            # Spegnimento ordinato: il lavoro torna in coda senza contare come
            # tentativo fallito, e ripartira' al prossimo avvio.
            pulisci_lavorazione(cartella, tieni_sorgente=True)
            lavoro.stato = IN_CODA
            lavoro.iniziato = None
            self.registro.salva(lavoro)
            return

        durata = adesso() - lavoro.iniziato
        if scaduto:
            termina_con_errore(lavoro, {
                "codice": "tempo_scaduto",
                "messaggio": "la conversione ha superato %d secondi ed e' stata "
                             "interrotta." % self.cfg.timeout,
                "suggerimento": "Dividi il documento o riduci le immagini "
                                "molto grandi."}, self.cfg.ttl)
        else:
            self._raccogli(lavoro, cartella, codice, uscita)

        pulisci_lavorazione(cartella)
        self.registro.salva(lavoro)
        log("lavoro %s chiave=%s template=%s documenti=%d esito=%s %.1fs"
            % (lavoro.id, lavoro.chiave, lavoro.opzioni.get("template"),
               len(lavoro.documenti), lavoro.esito, durata))

    def _termina_gruppo(self):
        for segnale, attesa in ((signal.SIGTERM, 5), (signal.SIGKILL, None)):
            try:
                os.killpg(self.processo.pid, segnale)
            except ProcessLookupError:
                return
            if attesa is None:
                return
            try:
                self.processo.wait(timeout=attesa)
                return
            except subprocess.TimeoutExpired:
                continue

    def _raccogli(self, lavoro, cartella, codice, uscita):
        try:
            rapporto = json.loads((cartella / "rapporto.json")
                                  .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            testo = (uscita or b"")[-MAX_LOG:].decode("utf-8", "replace")
            log("lavoro %s: rapporto mancante, uscita %s:\n%s"
                % (lavoro.id, codice, testo))
            termina_con_errore(lavoro, {
                "codice": "errore_interno",
                "messaggio": "la conversione si e' interrotta in modo inatteso.",
                "suggerimento": None}, self.cfg.ttl)
            return

        for voce in rapporto.get("documenti", []):
            documento = {"sorgente": _relativo(voce.get("sorgente")),
                         "esito": voce.get("esito")}
            if voce.get("esito") == "ok":
                documento["pdf"] = _relativo(voce.get("pdf"))
                documento["avvisi"] = voce.get("avvisi", [])
            else:
                documento["codice_uscita"] = voce.get("codice_uscita")
                documento["errore"] = errore_da_uscita(
                    voce.get("codice_uscita"), voce.get("messaggio"),
                    voce.get("suggerimento"))
            lavoro.documenti.append(documento)

        generali = rapporto.get("errori_generali") or []
        riusciti = [d for d in lavoro.documenti if d["esito"] == "ok"]
        if generali:
            primo = generali[0]
            termina_con_errore(lavoro, errore_da_uscita(
                primo.get("codice_uscita"), primo.get("messaggio"),
                primo.get("suggerimento")), self.cfg.ttl)
            return
        if not lavoro.documenti:
            termina_con_errore(lavoro, {
                "codice": "nessun_documento",
                "messaggio": "nessun file .md da convertire.",
                "suggerimento": "Con uno ZIP che ha i documenti nelle "
                                "sottocartelle usa recursive=true."}, self.cfg.ttl)
            return
        if not riusciti:
            primo = next(d for d in lavoro.documenti if d["esito"] != "ok")
            termina_con_errore(lavoro, primo["errore"], self.cfg.ttl)
            return

        pdf = sorted(p for p in (cartella / "pdf").rglob("*.pdf") if p.is_file())
        if len(pdf) == 1:
            destinazione = cartella / "risultato.pdf"
            os.replace(pdf[0], destinazione)
            tipo, nome = "application/pdf", pdf[0].name
        else:
            destinazione = cartella / "risultato.zip"
            crea_zip([(p, p.relative_to(cartella / "pdf").as_posix()) for p in pdf],
                     destinazione)
            tipo = "application/zip"
            nome = (Path(lavoro.ingresso).stem if lavoro.ingresso != "."
                    else "documenti") + ".zip"
        lavoro.stato = COMPLETATO
        lavoro.esito = "ok" if len(riusciti) == len(lavoro.documenti) else "parziale"
        lavoro.terminato = adesso()
        lavoro.scade = lavoro.terminato + self.cfg.ttl
        lavoro.risultato = {"file": destinazione.name, "tipo": tipo, "nome": nome,
                            "byte": destinazione.stat().st_size}


# --------------------------------------------------------------------------
# Pulizia
# --------------------------------------------------------------------------

class Spazzino(threading.Thread):
    """Elimina i lavori scaduti ogni IMPAGINA_API_PULIZIA_OGNI secondi."""

    def __init__(self, cfg, registro, fermo):
        super().__init__(name="spazzino", daemon=True)
        self.cfg = cfg
        self.registro = registro
        self.fermo = fermo

    def run(self):
        while not self.fermo.wait(self.cfg.pulizia_ogni):
            self.pulisci()

    def pulisci(self):
        ora = adesso()
        for lavoro in self.registro.tutti():
            if lavoro.stato in (COMPLETATO, FALLITO) and lavoro.scade \
                    and lavoro.scade <= ora:
                self.registro.elimina(lavoro.id)
