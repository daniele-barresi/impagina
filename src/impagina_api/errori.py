"""
Errori restituiti ai client e corrispondenza con i codici di uscita di
impagina.py.

Ogni errore ha un codice stabile (in italiano, senza spazi) che un client
puo' confrontare, un messaggio per le persone e un eventuale suggerimento.
Il corpo JSON e' sempre:

  {"errore": {"codice": "...", "messaggio": "...", "suggerimento": "..."}}
"""


class ErroreRichiesta(Exception):
    """Errore atteso, da restituire al client cosi' com'e'."""

    def __init__(self, stato_http, codice, messaggio, suggerimento=None,
                 intestazioni=None):
        super().__init__(messaggio)
        self.stato_http = stato_http
        self.codice = codice
        self.messaggio = messaggio
        self.suggerimento = suggerimento
        self.intestazioni = intestazioni or {}

    def corpo(self):
        return {"errore": {"codice": self.codice,
                           "messaggio": self.messaggio,
                           "suggerimento": self.suggerimento}}


# Codici di uscita di impagina.py (vedi src/impagina.py) -> (codice, HTTP).
# 1 e 6 sono colpa del server (argomenti costruiti male, disco): 500.
# Gli altri dipendono dal documento: 422, "entita' non elaborabile".
DA_CODICE_USCITA = {
    1: ("uso_errato", 500),
    2: ("input_non_trovato", 422),
    3: ("template_non_trovato", 422),
    4: ("front_matter_non_valido", 422),
    5: ("conversione_fallita", 422),
    6: ("scrittura_fallita", 500),
}

# Errori del lavoro che non vengono da un codice di uscita.
STATO_HTTP = {
    "tempo_scaduto": 422,
    "nessun_documento": 422,
    "interrotto": 500,
    "errore_interno": 500,
}


def errore_da_uscita(codice_uscita, messaggio, suggerimento=None):
    """Voce 'errore' (dict) per un documento o un lavoro fallito."""
    codice, _ = DA_CODICE_USCITA.get(codice_uscita, ("errore_interno", 500))
    return {"codice": codice, "messaggio": messaggio,
            "suggerimento": suggerimento}


def stato_http_di(codice):
    for nome, stato in DA_CODICE_USCITA.values():
        if nome == codice:
            return stato
    return STATO_HTTP.get(codice, 500)
