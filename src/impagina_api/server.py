"""
Il server HTTP di impagina-api e i suoi endpoint.

  GET    /salute                 stato del servizio (senza autenticazione)
  GET    /openapi.yaml           descrittore OpenAPI (senza autenticazione)
  GET    /template               template disponibili
  POST   /dipendenze             file referenziati da un .md (sincrono)
  POST   /lavori                 nuovo lavoro: multipart oppure ZIP -> 202
  GET    /lavori/<id>            stato del lavoro
  GET    /lavori/<id>/risultato  il PDF, o lo ZIP dei PDF
  DELETE /lavori/<id>            elimina subito il lavoro e i suoi file

http.server della libreria standard non e' pensato per stare esposto su
Internet: il servizio ascolta su 127.0.0.1 (vedi compose.yaml) e, se serve
raggiungerlo da fuori, va messo dietro un reverse proxy con HTTPS.
"""

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, quote, urlsplit

import impagina

from . import __version__
from .archivi import estrai_zip
from .chiavi import RegistroChiavi
from .configurazione import ErroreConfigurazione, carica
from .errori import DA_CODICE_USCITA, ErroreRichiesta, stato_http_di
from .lavori import (COMPLETATO, FALLITO, IN_CODA, IN_CORSO, Coda, Esecutore,
                     Registro, Spazzino, log)
from .multipart import LettoreLimitato, boundary_da, leggi_parti
from .percorsi import Budget, leggibile, percorso_sicuro, scrivi_file_sicuro

DIPENDENZE_LUA = impagina.FILTERS_DIR / "dipendenze.lua"
OPENAPI = Path(__file__).resolve().parent / "openapi.yaml"
TEMPLATE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
CONTROLLO_RE = re.compile(r"[\x00-\x1f\x7f]")
MAX_CAMPO = 4096
MAX_WATERMARK = 100
TIMEOUT_DIPENDENZE = 15
VERI = {"1", "true", "si", "sì", "yes", "on"}
FALSI = {"0", "false", "no", "off"}
TIPI_ZIP = {"application/zip", "application/x-zip-compressed"}
TIPI_MARKDOWN = {"text/markdown", "text/x-markdown", "text/plain"}
# PHP (curl con un array di campi) non puo' ripetere una chiave: gli allegati
# arrivano come allegato[0], allegato[1]... e valgono come "allegato".
ALLEGATO_RE = re.compile(r"^allegato(\[[^\]]*\])?$")


# --------------------------------------------------------------------------
# Opzioni di conversione
# --------------------------------------------------------------------------

def _opzione_non_valida(messaggio, suggerimento=None):
    return ErroreRichiesta(400, "opzione_non_valida", messaggio, suggerimento)


def _booleano(nome, valore):
    testo = valore.strip().lower()
    if testo in VERI:
        return True
    if testo in FALSI:
        return False
    raise _opzione_non_valida("l'opzione '%s' deve essere true o false (trovato: '%s')."
                              % (nome, valore))


def valida_opzioni(campi, modo, cfg):
    """Le opzioni ricevute (form o query string), verificate e tipizzate."""
    ammesse = {"template", "toc", "cover", "watermark", "recursive"}
    sconosciute = sorted(set(campi) - ammesse)
    if sconosciute:
        # Meglio un errore di un refuso ignorato in silenzio.
        raise _opzione_non_valida(
            "opzione sconosciuta: %s." % ", ".join(sconosciute),
            "Opzioni ammesse: %s." % ", ".join(sorted(ammesse)))

    template = campi.get("template", "company").strip() or "company"
    if not TEMPLATE_RE.match(template):
        raise _opzione_non_valida("nome di template non valido: '%s'." % template)
    disponibili = impagina.available_templates(cfg.cartelle_template)
    if template not in disponibili:
        raise ErroreRichiesta(
            422, "template_non_trovato",
            "template '%s' non trovato." % template,
            "Template disponibili: %s" % (", ".join(disponibili) or "nessuno"))

    opzioni = {"template": template, "toc": False, "cover": None,
               "watermark": None, "recursive": False,
               "sandbox": not cfg.typst_grezzo}
    if "toc" in campi:
        opzioni["toc"] = _booleano("toc", campi["toc"])
    if campi.get("cover", "").strip():
        opzioni["cover"] = _booleano("cover", campi["cover"])
    if campi.get("watermark", "").strip():
        watermark = campi["watermark"].strip()
        if len(watermark) > MAX_WATERMARK or CONTROLLO_RE.search(watermark):
            raise _opzione_non_valida(
                "il watermark deve essere un testo di al massimo %d caratteri, "
                "su una riga." % MAX_WATERMARK)
        opzioni["watermark"] = watermark
    if "recursive" in campi:
        if modo != "cartella":
            raise _opzione_non_valida(
                "recursive vale solo per gli archivi ZIP.",
                "Per convertire piu' documenti invia uno ZIP della cartella.")
        opzioni["recursive"] = _booleano("recursive", campi["recursive"])
    return opzioni


# --------------------------------------------------------------------------
# Rappresentazione JSON
# --------------------------------------------------------------------------

def iso(istante):
    if istante is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(istante))


def vista_lavoro(lavoro, coda):
    url = "/lavori/%s" % lavoro.id
    opzioni = {k: v for k, v in lavoro.opzioni.items() if k != "sandbox"}
    vista = {
        "id": lavoro.id,
        "stato": lavoro.stato,
        "esito": lavoro.esito,
        "creato": iso(lavoro.creato),
        "iniziato": iso(lavoro.iniziato),
        "terminato": iso(lavoro.terminato),
        "scade": iso(lavoro.scade),
        "posizione_in_coda": coda.posizione(lavoro.id) if lavoro.stato == IN_CODA else None,
        "opzioni": opzioni,
        "documenti": lavoro.documenti,
        "errore": lavoro.errore,
        "risultato": None,
        "stato_url": url,
    }
    if lavoro.stato == COMPLETATO and lavoro.risultato:
        vista["risultato"] = {"url": url + "/risultato",
                              "tipo": lavoro.risultato["tipo"],
                              "nome": lavoro.risultato["nome"],
                              "byte": lavoro.risultato["byte"]}
    return vista


def content_disposition(nome):
    """Nome del file scaricato: ASCII per i client vecchi, UTF-8 per gli altri."""
    ascii_ = nome.encode("ascii", "replace").decode("ascii")
    ascii_ = ascii_.replace("\\", "_").replace('"', "_")
    return "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (ascii_, quote(nome))


# --------------------------------------------------------------------------
# Server e gestore delle richieste
# --------------------------------------------------------------------------

class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, indirizzo, cfg, chiavi, registro, coda):
        self.cfg = cfg
        self.chiavi = chiavi
        self.registro = registro
        self.coda = coda
        # Caricamenti contemporanei: oltre, 503 invece di accumulare connessioni.
        self.caricamenti = threading.BoundedSemaphore(cfg.caricamenti)
        self.analisi = threading.BoundedSemaphore(2)
        super().__init__(indirizzo, Gestore)


ROTTE = [
    (re.compile(r"^/salute$"), {"GET": "salute"}),
    (re.compile(r"^/openapi\.yaml$"), {"GET": "openapi"}),
    (re.compile(r"^/template$"), {"GET": "template"}),
    (re.compile(r"^/dipendenze$"), {"POST": "dipendenze"}),
    (re.compile(r"^/lavori$"), {"POST": "crea_lavoro"}),
    (re.compile(r"^/lavori/([^/]+)$"), {"GET": "stato_lavoro",
                                        "DELETE": "elimina_lavoro"}),
    (re.compile(r"^/lavori/([^/]+)/risultato$"), {"GET": "risultato"}),
]
SENZA_AUTENTICAZIONE = {"salute", "openapi"}


class Gestore(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 30        # una connessione ferma per 30 s viene chiusa

    def version_string(self):
        return "impagina-api/" + __version__

    # --- instradamento --------------------------------------------------

    def do_GET(self):
        self._gestisci()

    do_POST = do_DELETE = do_PUT = do_PATCH = do_HEAD = do_GET

    def _instrada(self):
        percorso = urlsplit(self.path).path
        for schema, metodi in ROTTE:
            trovato = schema.match(percorso)
            if trovato:
                if self.command not in metodi:
                    raise ErroreRichiesta(
                        405, "metodo_non_consentito",
                        "metodo %s non consentito su %s." % (self.command, percorso),
                        intestazioni={"Allow": ", ".join(sorted(metodi))})
                return metodi[self.command], trovato.groups()
        raise ErroreRichiesta(404, "risorsa_non_trovata",
                              "percorso sconosciuto: %s." % percorso)

    def _preliminari(self):
        """Controlli che non richiedono il corpo: vanno fatti prima di
        riceverlo, cosi' un 401 o un 413 non costano un caricamento."""
        nome, argomenti = self._instrada()
        if nome not in SENZA_AUTENTICAZIONE:
            self._autentica()
        if nome == "crea_lavoro":
            self._lunghezza(self.server.cfg.max_corpo)
        elif nome == "dipendenze":
            self._lunghezza(self.server.cfg.max_md + 64 * 1024)
        return nome, argomenti

    def handle_expect_100(self):
        # curl manda "Expect: 100-continue" per i corpi oltre 1 MB e aspetta
        # il via libera prima di inviarli: se la richiesta va rifiutata, il
        # client lo scopre senza aver caricato nulla.
        self.chiave = None
        self.inizio = time.monotonic()
        try:
            self._preliminari()
        except ErroreRichiesta as errore:
            self._errore(errore)
            return False
        return super().handle_expect_100()

    def _gestisci(self):
        self.close_connection = True
        self.inizio = getattr(self, "inizio", None) or time.monotonic()
        self.chiave = getattr(self, "chiave", None)
        self.corpo = None
        try:
            nome, argomenti = self._preliminari()
            getattr(self, "api_" + nome)(*argomenti)
        except ErroreRichiesta as errore:
            self._scarta_corpo()
            self._errore(errore)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log("errore interno su %s %s:\n%s"
                % (self.command, self.path, traceback.format_exc()))
            self._scarta_corpo()
            self._errore(ErroreRichiesta(500, "errore_interno",
                                         "errore interno del servizio."))

    # --- strumenti --------------------------------------------------------

    def _autentica(self):
        self.chiave = self.server.chiavi.verifica(self.headers.get("Authorization"))
        if self.chiave is None:
            raise ErroreRichiesta(
                401, "non_autorizzato",
                "chiave di accesso mancante o non valida.",
                "Invia l'intestazione 'Authorization: Bearer <token>'.",
                intestazioni={"WWW-Authenticate": 'Bearer realm="impagina"'})

    def _lunghezza(self, massimo):
        if self.headers.get("Transfer-Encoding"):
            raise ErroreRichiesta(411, "lunghezza_richiesta",
                                  "il corpo a blocchi (chunked) non e' supportato.",
                                  "Invia la richiesta con Content-Length.")
        grezza = self.headers.get("Content-Length")
        if grezza is None:
            raise ErroreRichiesta(411, "lunghezza_richiesta",
                                  "manca l'intestazione Content-Length.")
        try:
            lunghezza = int(grezza)
            if lunghezza < 0:
                raise ValueError
        except ValueError:
            raise ErroreRichiesta(400, "richiesta_non_valida",
                                  "Content-Length non valido.")
        if lunghezza > massimo:
            raise ErroreRichiesta(413, "troppo_grande",
                                  "la richiesta supera il limite di %s."
                                  % leggibile(massimo))
        return lunghezza

    def _leggi_corpo(self, lunghezza):
        self.corpo = LettoreLimitato(self.rfile, lunghezza)
        return self.corpo

    def _scarta_corpo(self):
        """
        Legge (e butta) il resto del corpo gia' accettato prima di rispondere
        con un errore: chiudendo la connessione con dati non letti, il kernel
        manderebbe un RST e il client potrebbe non vedere mai la risposta.
        """
        if self.corpo is not None:
            try:
                self.corpo.scarta()
            except (ErroreRichiesta, OSError):
                pass

    def _json(self, stato, dati, intestazioni=None):
        corpo = (json.dumps(dati, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(stato)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        for nome, valore in (intestazioni or {}).items():
            self.send_header(nome, valore)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _errore(self, errore):
        self.close_connection = True
        try:
            self._json(errore.stato_http, errore.corpo(), errore.intestazioni)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # --- log ----------------------------------------------------------------

    def log_request(self, code="-", size="-"):
        durata = time.monotonic() - (getattr(self, "inizio", None) or time.monotonic())
        codice = code.value if hasattr(code, "value") else code
        self.log_message("chiave=%s %s %s %s %.2fs",
                         getattr(self, "chiave", None) or "-", self.command,
                         urlsplit(self.path).path, codice, durata)

    def log_message(self, formato, *argomenti):
        # Mai il token nei log: qui arrivano solo metodo, percorso e nome
        # della chiave. L'indirizzo del client e' quello del proxy o di Docker.
        log(formato % argomenti)

    # --- endpoint -----------------------------------------------------------

    def api_salute(self):
        in_corso = sum(1 for l in self.server.registro.tutti() if l.stato == IN_CORSO)
        self._json(200, {"stato": "ok", "versione": __version__,
                         "worker": self.server.cfg.worker,
                         "in_coda": self.server.coda.lunghezza(),
                         "in_corso": in_corso})

    def api_openapi(self):
        corpo = OPENAPI.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/yaml; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(corpo)

    def api_template(self):
        self._json(200, {"template": impagina.available_templates(
            self.server.cfg.cartelle_template)})

    def api_dipendenze(self):
        cfg = self.server.cfg
        lunghezza = self._lunghezza(cfg.max_md + 64 * 1024)
        tipo = self.headers.get_content_type()
        if tipo not in TIPI_MARKDOWN and tipo != "multipart/form-data":
            raise ErroreRichiesta(
                415, "tipo_non_supportato",
                "tipo di contenuto non supportato: %s." % tipo,
                "Invia il Markdown come text/markdown oppure come campo "
                "'documento' di un multipart/form-data.")
        if not self.server.analisi.acquire(blocking=False):
            raise ErroreRichiesta(503, "server_occupato",
                                  "troppe analisi in corso, riprova fra poco.",
                                  intestazioni={"Retry-After": "5"})
        try:
            corpo = self._leggi_corpo(lunghezza)
            nome, testo, allegati = None, None, set()
            if tipo == "multipart/form-data":
                boundary = boundary_da(self.headers["Content-Type"])
                for parte in leggi_parti(corpo, boundary):
                    if parte.nome == "documento":
                        nome = PurePosixPath(
                            (parte.filename or "").replace("\\", "/")).name or None
                        testo = parte.leggi_tutto(cfg.max_md)
                    elif ALLEGATO_RE.match(parte.nome) and parte.filename:
                        relativo = percorso_sicuro(parte.filename)
                        if relativo is not None:
                            allegati.add(str(relativo))
                corpo.scarta()
                if testo is None:
                    raise ErroreRichiesta(400, "richiesta_non_valida",
                                          "manca il campo 'documento'.")
            else:
                testo = bytearray()
                while True:
                    blocco = corpo.read()
                    if not blocco:
                        break
                    testo += blocco
                testo = bytes(testo)
            if len(testo) > cfg.max_md:
                raise ErroreRichiesta(413, "troppo_grande",
                                      "il documento supera il limite di %s."
                                      % leggibile(cfg.max_md))
            risultato = self._analizza(nome or "documento", testo)
        finally:
            self.server.analisi.release()

        for voce in risultato["file"]:
            voce["stato"] = "allegato" if voce["percorso"] in allegati else "da_allegare"
        risultato["documento"] = nome
        self._json(200, risultato)

    def _analizza(self, nome, testo):
        try:
            esito = subprocess.run(
                ["pandoc", "--from", "markdown", "--to", str(DIPENDENZE_LUA)],
                input=testo, capture_output=True, timeout=TIMEOUT_DIPENDENZE,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
                     "HOME": "/tmp"})
        except subprocess.TimeoutExpired:
            raise ErroreRichiesta(422, "tempo_scaduto",
                                  "l'analisi del documento ha superato %d secondi."
                                  % TIMEOUT_DIPENDENZE)
        if esito.returncode != 0:
            errore = impagina.explain_pandoc_failure(
                nome, esito.stderr.decode("utf-8", "replace"))
            codice, stato = DA_CODICE_USCITA.get(errore.code, ("errore_interno", 500))
            raise ErroreRichiesta(stato, codice, errore.message, errore.hint)
        return json.loads(esito.stdout.decode("utf-8"))

    def api_crea_lavoro(self):
        server = self.server
        cfg = server.cfg
        lunghezza = self._lunghezza(cfg.max_corpo)
        query = dict(parse_qsl(urlsplit(self.path).query, keep_blank_values=True))
        tipo = self.headers.get_content_type()
        if tipo == "multipart/form-data":
            modo = "documento"
            boundary = boundary_da(self.headers["Content-Type"])
        elif tipo in TIPI_ZIP:
            modo = "cartella"
            opzioni = valida_opzioni(query, modo, cfg)  # prima di ricevere il corpo
        else:
            raise ErroreRichiesta(
                415, "tipo_non_supportato",
                "tipo di contenuto non supportato: %s." % tipo,
                "Usa multipart/form-data (documento + allegati) oppure "
                "application/zip (una cartella compressa).")

        if not server.caricamenti.acquire(blocking=False):
            raise ErroreRichiesta(503, "server_occupato",
                                  "troppi caricamenti in corso, riprova fra poco.",
                                  intestazioni={"Retry-After": "10"})
        lavoro = server.registro.nuovo(self.chiave)
        cartella = server.registro.cartella(lavoro.id)
        try:
            corpo = self._leggi_corpo(lunghezza)
            if modo == "documento":
                campi, ingresso = self._ricevi_multipart(corpo, boundary,
                                                         cartella / "sorgente")
                opzioni = valida_opzioni(dict(query, **campi), modo, cfg)
            else:
                self._ricevi_zip(corpo, cartella)
                ingresso = "."
                self._verifica_documenti(cartella / "sorgente", opzioni["recursive"])

            lavoro.opzioni, lavoro.modo, lavoro.ingresso = opzioni, modo, ingresso
            lavoro.stato = IN_CODA
            server.registro.salva(lavoro)
            if not server.coda.inserisci(lavoro.id):
                raise ErroreRichiesta(503, "coda_piena",
                                      "la coda dei lavori e' piena, riprova fra poco.",
                                      intestazioni={"Retry-After": "30"})
        except BaseException:
            server.registro.elimina(lavoro.id)
            raise
        finally:
            server.caricamenti.release()

        url = "/lavori/%s" % lavoro.id
        self._json(202, {"id": lavoro.id, "stato": lavoro.stato,
                         "posizione_in_coda": server.coda.posizione(lavoro.id),
                         "stato_url": url, "risultato_url": url + "/risultato"},
                   {"Location": url, "Retry-After": "2"})

    def _ricevi_multipart(self, corpo, boundary, sorgente):
        cfg = self.server.cfg
        budget = Budget(cfg.max_corpo, cfg.max_file)
        campi, documento = {}, None
        for parte in leggi_parti(corpo, boundary, max_parti=cfg.max_file + 20):
            if parte.nome == "documento":
                if documento is not None:
                    raise ErroreRichiesta(
                        400, "richiesta_non_valida",
                        "un solo campo 'documento' per richiesta.",
                        "Per convertire piu' documenti insieme invia uno ZIP.")
                # Del documento conta solo il nome: finisce nella radice, e le
                # immagini si cercano relative a li'.
                nome = PurePosixPath((parte.filename or "").replace("\\", "/")).name
                relativo = percorso_sicuro(nome) if nome else None
                if relativo is None or not nome.lower().endswith(".md"):
                    raise ErroreRichiesta(
                        400, "richiesta_non_valida",
                        "il campo 'documento' deve contenere un file .md.")
                scrivi_file_sicuro(sorgente, relativo, parte.blocchi(), budget)
                documento = relativo
            elif ALLEGATO_RE.match(parte.nome):
                if not parte.filename:
                    raise ErroreRichiesta(400, "richiesta_non_valida",
                                          "un campo 'allegato' non ha il nome del file.")
                relativo = percorso_sicuro(parte.filename)
                if relativo is not None:
                    scrivi_file_sicuro(sorgente, relativo, parte.blocchi(), budget)
            elif parte.filename is None:
                try:
                    campi[parte.nome] = parte.leggi_tutto(MAX_CAMPO).decode("utf-8")
                except UnicodeDecodeError:
                    raise ErroreRichiesta(400, "richiesta_non_valida",
                                          "il campo '%s' non e' testo UTF-8." % parte.nome)
            else:
                raise ErroreRichiesta(
                    400, "richiesta_non_valida",
                    "campo file sconosciuto: '%s'." % parte.nome,
                    "I file vanno nei campi 'documento' (il .md) e 'allegato' "
                    "(immagini e altri file, con il percorso relativo come nome).")
        corpo.scarta()
        if documento is None:
            raise ErroreRichiesta(400, "richiesta_non_valida",
                                  "manca il campo 'documento' con il file .md.")
        return campi, str(documento)

    def _ricevi_zip(self, corpo, cartella):
        cfg = self.server.cfg
        archivio = cartella / "ingresso.zip"
        with open(archivio, "xb") as uscita:
            while True:
                blocco = corpo.read()
                if not blocco:
                    break
                uscita.write(blocco)
        estrai_zip(archivio, cartella / "sorgente", cfg.max_espanso, cfg.max_file)
        archivio.unlink()

    def _verifica_documenti(self, sorgente, ricorsivo):
        if any(sorgente.glob("**/*.md" if ricorsivo else "*.md")):
            return
        suggerimento = None
        if not ricorsivo and any(sorgente.glob("**/*.md")):
            suggerimento = "I documenti sono nelle sottocartelle: aggiungi recursive=true."
        raise ErroreRichiesta(422, "nessun_documento",
                              "l'archivio non contiene file .md da convertire.",
                              suggerimento)

    def _lavoro(self, id_lavoro):
        lavoro = self.server.registro.trova(id_lavoro, self.chiave)
        if lavoro is None:
            raise ErroreRichiesta(404, "lavoro_non_trovato",
                                  "lavoro inesistente o scaduto.")
        return lavoro

    def api_stato_lavoro(self, id_lavoro):
        lavoro = self._lavoro(id_lavoro)
        intestazioni = ({"Retry-After": "2"}
                        if lavoro.stato in (IN_CODA, IN_CORSO) else None)
        self._json(200, vista_lavoro(lavoro, self.server.coda), intestazioni)

    def api_risultato(self, id_lavoro):
        lavoro = self._lavoro(id_lavoro)
        if lavoro.stato in (IN_CODA, IN_CORSO):
            raise ErroreRichiesta(409, "non_pronto",
                                  "il lavoro non e' ancora terminato.",
                                  intestazioni={"Retry-After": "2"})
        if lavoro.stato == FALLITO:
            errore = lavoro.errore or {}
            codice = errore.get("codice", "errore_interno")
            raise ErroreRichiesta(stato_http_di(codice), codice,
                                  errore.get("messaggio", "conversione fallita."),
                                  errore.get("suggerimento"))
        percorso = self.server.registro.cartella(lavoro.id) / lavoro.risultato["file"]
        try:
            # Aperto prima di rispondere: se lo spazzino lo cancella durante
            # l'invio, il file resta leggibile fino alla chiusura.
            sorgente = open(percorso, "rb")
        except FileNotFoundError:
            raise ErroreRichiesta(404, "lavoro_non_trovato",
                                  "lavoro inesistente o scaduto.")
        with sorgente:
            dimensione = os.fstat(sorgente.fileno()).st_size
            self.send_response(200)
            self.send_header("Content-Type", lavoro.risultato["tipo"])
            self.send_header("Content-Length", str(dimensione))
            self.send_header("Content-Disposition",
                             content_disposition(lavoro.risultato["nome"]))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                blocco = sorgente.read(64 * 1024)
                if not blocco:
                    break
                self.wfile.write(blocco)

    def api_elimina_lavoro(self, id_lavoro):
        lavoro = self._lavoro(id_lavoro)
        if lavoro.stato == IN_CORSO:
            raise ErroreRichiesta(409, "non_pronto",
                                  "il lavoro e' in corso: si potra' eliminare "
                                  "quando sara' terminato.",
                                  intestazioni={"Retry-After": "2"})
        self.server.coda.rimuovi(lavoro.id)
        self.server.registro.elimina(lavoro.id)
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()


# --------------------------------------------------------------------------
# Avvio
# --------------------------------------------------------------------------

def log_template(cfg):
    """
    Scrive nel log i template trovati e i problemi delle loro directory.

    Le directory si rileggono comunque a ogni richiesta (un template aggiunto
    o corretto e' subito disponibile): questo e' il controllo all'avvio, che
    fa emergere una configurazione sbagliata prima della prima conversione.
    """
    scan = impagina.scan_templates(cfg.cartelle_template)
    for nota in list(cfg.note_template) + scan.problems:
        log("attenzione: %s" % nota)
    for nota in scan.overrides:
        log(nota)
    log("directory dei template: %s"
        % ", ".join(str(d.path) for d in cfg.cartelle_template))
    log("template disponibili: %s"
        % (", ".join("%s (%s)" % (nome, cartella.parent)
                     for nome, cartella in scan.templates.items())
           or "nessuno"))


def main():
    try:
        cfg = carica()
        chiavi = RegistroChiavi(cfg.chiavi)
        registro = Registro(cfg.lavori, cfg.ttl)
    except (ErroreConfigurazione, ValueError) as exc:
        print("Errore: %s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print("Errore: cartella dei lavori non utilizzabile: %s (%s)."
              % (cfg.lavori, exc.strerror or exc), file=sys.stderr)
        return 1

    coda = Coda(cfg.coda_max)
    ripresi = registro.ripristina(coda)
    try:
        server = Server((cfg.indirizzo, cfg.porta), cfg, chiavi, registro, coda)
    except OSError as exc:
        print("Errore: impossibile ascoltare su %s:%d (%s)."
              % (cfg.indirizzo, cfg.porta, exc.strerror or exc), file=sys.stderr)
        return 1

    esecutori = [Esecutore(n + 1, cfg, registro, coda) for n in range(cfg.worker)]
    for esecutore in esecutori:
        esecutore.start()
    fermo = threading.Event()
    spazzino = Spazzino(cfg, registro, fermo)
    spazzino.pulisci()
    spazzino.start()

    def spegni(segnale, _frame):
        if fermo.is_set():
            return
        log("arresto in corso (%s)" % signal.Signals(segnale).name)
        fermo.set()
        coda.chiudi()
        for esecutore in esecutori:
            esecutore.ferma()
        # shutdown() attende la fine di serve_forever: va chiamato da un
        # altro thread, non dal gestore del segnale.
        threading.Thread(target=server.shutdown, daemon=True).start()

    # Come PID 1 in un container, Python non ha un gestore predefinito per
    # SIGTERM: senza questo "docker stop" aspetterebbe 10 s e poi SIGKILL.
    signal.signal(signal.SIGTERM, spegni)
    signal.signal(signal.SIGINT, spegni)

    log("impagina-api %s in ascolto su %s:%d — worker=%d, coda=%d, "
        "timeout=%ds, corpo max=%s, ttl=%ds, sandbox=%s%s"
        % (__version__, cfg.indirizzo, cfg.porta, cfg.worker, cfg.coda_max,
           cfg.timeout, leggibile(cfg.max_corpo), cfg.ttl,
           "no" if cfg.typst_grezzo else "si",
           "" if not ripresi else ", 1 lavoro ripreso" if ripresi == 1
           else ", %d lavori ripresi" % ripresi))
    log_template(cfg)
    # poll_interval alto: il ciclo di serve_forever si sveglia solo per
    # controllare la richiesta di arresto, e a riposo non deve farlo spesso.
    server.serve_forever(poll_interval=5)
    for esecutore in esecutori:
        esecutore.join(timeout=10)
    server.server_close()
    log("arrestato")
    return 0
