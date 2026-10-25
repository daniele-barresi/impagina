"""
Configurazione del servizio, letta dalle variabili d'ambiente.

Ogni valore viene validato all'avvio: un errore di configurazione ferma il
servizio con un messaggio chiaro invece di manifestarsi alla prima richiesta.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import impagina

# Variabili che decidono dove cercare i template: il servizio le inoltra tali
# e quali alle conversioni, che quindi vedono gli stessi template di
# GET /template.
VARIABILI_TEMPLATE = ("IMPAGINA_TEMPLATES_PATH", "IMPAGINA_TEMPLATES",
                      "IMPAGINA_BUILTIN_TEMPLATES")


class ErroreConfigurazione(Exception):
    pass


@dataclass(frozen=True)
class Configurazione:
    indirizzo: str
    porta: int
    chiavi: Path
    worker: int
    coda_max: int
    caricamenti: int
    timeout: int
    max_corpo: int
    max_espanso: int
    max_file: int
    max_md: int
    ttl: int
    pulizia_ogni: int
    lavori: Path
    typst_grezzo: bool
    variabili_template: tuple   # coppie (nome, valore) di VARIABILI_TEMPLATE
    cartelle_template: tuple    # impagina.TemplateDir, in ordine di precedenza
    note_template: tuple        # avvisi sulla configurazione, per il log


_DIMENSIONE_RE = re.compile(r"^\s*(\d+)\s*([KMG]?)B?\s*$", re.IGNORECASE)
_MOLTIPLICATORI = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}


def _intero(env, nome, predefinito, minimo, massimo):
    grezzo = env.get(nome, "").strip()
    if not grezzo:
        return predefinito
    try:
        valore = int(grezzo)
    except ValueError:
        valore = None
    if valore is None or not minimo <= valore <= massimo:
        raise ErroreConfigurazione(
            "%s deve essere un intero fra %d e %d (trovato: '%s')."
            % (nome, minimo, massimo, grezzo))
    return valore


def _dimensione(env, nome, predefinito):
    """Accetta 50M, 512K, 1G oppure un numero di byte."""
    grezzo = env.get(nome, "").strip()
    if not grezzo:
        return predefinito
    trovato = _DIMENSIONE_RE.match(grezzo)
    if not trovato or int(trovato.group(1)) == 0:
        raise ErroreConfigurazione(
            "%s deve essere una dimensione come 50M, 512K o 1G (trovato: '%s')."
            % (nome, grezzo))
    return int(trovato.group(1)) * _MOLTIPLICATORI[trovato.group(2).upper()]


def _booleano(env, nome):
    grezzo = env.get(nome, "").strip().lower()
    if grezzo in ("", "0", "no", "false", "off"):
        return False
    if grezzo in ("1", "si", "sì", "yes", "true", "on"):
        return True
    raise ErroreConfigurazione(
        "%s deve essere 1 oppure 0 (trovato: '%s')." % (nome, grezzo))


def carica(env=None):
    env = os.environ if env is None else env
    variabili = {n: env[n] for n in VARIABILI_TEMPLATE if n in env}
    cartelle, note = impagina.template_dirs_from_env(variabili)
    return Configurazione(
        indirizzo=env.get("IMPAGINA_API_INDIRIZZO", "0.0.0.0").strip() or "0.0.0.0",
        porta=_intero(env, "IMPAGINA_API_PORTA", 8080, 1, 65535),
        chiavi=Path(env.get("IMPAGINA_API_CHIAVI", "/etc/impagina/chiavi.conf")),
        worker=_intero(env, "IMPAGINA_API_WORKER", 1, 1, 16),
        coda_max=_intero(env, "IMPAGINA_API_CODA_MAX", 50, 1, 10000),
        caricamenti=_intero(env, "IMPAGINA_API_CARICAMENTI", 4, 1, 64),
        timeout=_intero(env, "IMPAGINA_API_TIMEOUT", 120, 1, 3600),
        max_corpo=_dimensione(env, "IMPAGINA_API_MAX_CORPO", 50 * 1024 ** 2),
        max_espanso=_dimensione(env, "IMPAGINA_API_MAX_ESPANSO", 200 * 1024 ** 2),
        max_file=_intero(env, "IMPAGINA_API_MAX_FILE", 200, 1, 100000),
        max_md=_dimensione(env, "IMPAGINA_API_MAX_MD", 5 * 1024 ** 2),
        ttl=_intero(env, "IMPAGINA_API_TTL", 3600, 1, 30 * 24 * 3600),
        pulizia_ogni=_intero(env, "IMPAGINA_API_PULIZIA_OGNI", 60, 1, 3600),
        lavori=Path(env.get("IMPAGINA_API_LAVORI", "/var/lib/impagina-api")),
        typst_grezzo=_booleano(env, "IMPAGINA_API_TYPST_GREZZO"),
        variabili_template=tuple(sorted(variabili.items())),
        cartelle_template=tuple(cartelle),
        note_template=tuple(note),
    )
