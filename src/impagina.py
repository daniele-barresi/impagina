#!/usr/bin/env python3
"""
impagina — converte Markdown in PDF applicando un template.

Pipeline: pandoc trasforma il Markdown in un sorgente Typst usando il
template scelto, poi typst compila quel sorgente in PDF.

Usa solo la libreria standard: nessuna dipendenza da installare.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

__version__ = "2.0.0"

# Codici di uscita (documentati nel README e verificati da test/run-tests.sh)
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_INPUT_NOT_FOUND = 2
EXIT_TEMPLATE_NOT_FOUND = 3
EXIT_BAD_FRONTMATTER = 4
EXIT_RENDER_FAILED = 5
EXIT_NOT_WRITABLE = 6

# Versioni del formato dei template (chiave impagina-format di theme.yaml)
# che questa versione sa impaginare. Un theme.yaml senza la chiave vale 1.
TEMPLATE_FORMATS = (1,)
FILTERS_DIR = Path(__file__).resolve().parent / "filters"
FILTER_PATHS = [
    FILTERS_DIR / "resolve-paths.lua",   # immagini relative -> percorsi assoluti
    FILTERS_DIR / "table-layout.lua",    # larghezze di colonna decise dal contenuto
]
# Solo con --sandbox, e sempre per primo: deve vedere i percorsi delle
# immagini cosi' come sono scritti, prima che resolve-paths.lua li renda
# assoluti.
SANDBOX_FILTER = FILTERS_DIR / "sandbox.lua"
SANDBOX_MARKER = "impagina-sandbox: "
SYSTEM_FONT_DIR = "/usr/share/fonts"


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def _load_display_map():
    """
    Mappa percorso-nel-container -> percorso-sull-host.

    Il wrapper impagina.sh la popola con i volumi che ha montato, cosi' i
    messaggi mostrano il percorso che l'utente ha effettivamente digitato
    invece di /data/... Senza la variabile la mappa e' vuota e i percorsi
    restano quelli del container.
    """
    entries = []
    for line in os.environ.get("IMPAGINA_DISPLAY_MAP", "").splitlines():
        if "=" in line:
            container, host = line.split("=", 1)
            if container and host:
                entries.append((container.rstrip("/"), host.rstrip("/")))
    # I prefissi piu' lunghi vanno provati per primi.
    return sorted(entries, key=lambda pair: -len(pair[0]))


DISPLAY_MAP = _load_display_map()


def shown(path):
    text = str(path)
    for container, host in DISPLAY_MAP:
        if text == container:
            return host
        if text.startswith(container + "/"):
            return host + text[len(container):]
    return text


def shown_text(text):
    """Come shown(), ma sostituisce i percorsi ovunque compaiano in un testo
    (per esempio dentro un messaggio d'errore di typst)."""
    for container, host in DISPLAY_MAP:
        text = text.replace(container + "/", host + "/")
    return text


def err(message):
    print("Errore: " + message, file=sys.stderr)


def warn(message):
    print("Attenzione: " + message, file=sys.stderr)


def info(message):
    print(message)


class ImpaginaError(Exception):
    """Errore atteso e gia' spiegato all'utente: mai uno stack trace."""

    def __init__(self, message, code=EXIT_RENDER_FAILED, hint=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint


# --------------------------------------------------------------------------
# Template
# --------------------------------------------------------------------------

class TemplateDir:
    """
    Una directory in cui cercare i template.

    explicit: indicata dall'utente (variabile d'ambiente o --templates-dir),
    quindi se manca e' un errore di configurazione da segnalare; il
    predefinito /templates invece puo' legittimamente non essere montato.
    builtin: la directory dei template inclusi nell'immagine.
    """

    def __init__(self, path, explicit=True, builtin=False):
        self.path = Path(path)
        self.explicit = explicit
        self.builtin = builtin

    def __repr__(self):
        return "TemplateDir(%r)" % str(self.path)


def template_dirs_from_env(env=None):
    """
    Directory dei template in ordine di precedenza, piu' gli avvisi sulla
    configurazione.

    Prima le directory esterne, poi quella dei template inclusi:
      IMPAGINA_TEMPLATES_PATH     una o piu' directory separate da ':'
      IMPAGINA_TEMPLATES          una sola directory (nome storico, alias)
      altrimenti                  /templates
      IMPAGINA_BUILTIN_TEMPLATES  template inclusi (/opt/impagina/templates)
    """
    env = os.environ if env is None else env
    notes = []
    if env.get("IMPAGINA_TEMPLATES_PATH") is not None:
        external = [TemplateDir(p) for p in
                    env["IMPAGINA_TEMPLATES_PATH"].split(":") if p.strip()]
        if env.get("IMPAGINA_TEMPLATES"):
            notes.append("IMPAGINA_TEMPLATES ignorata: e' impostata anche "
                         "IMPAGINA_TEMPLATES_PATH, che ha la precedenza.")
    elif env.get("IMPAGINA_TEMPLATES"):
        external = [TemplateDir(env["IMPAGINA_TEMPLATES"])]
    else:
        external = [TemplateDir("/templates", explicit=False)]
    builtin = TemplateDir(env.get("IMPAGINA_BUILTIN_TEMPLATES")
                          or "/opt/impagina/templates", builtin=True)
    return external + [builtin], notes


def check_template(directory):
    """Motivo per cui il template non e' utilizzabile, oppure None."""
    try:
        directory.joinpath("template.typ").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return "template.typ illeggibile (%s)" % (getattr(exc, "strerror", None) or exc)
    theme_file = directory / "theme.yaml"
    if not theme_file.exists():
        return None
    try:
        theme_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return "theme.yaml illeggibile (%s)" % (getattr(exc, "strerror", None) or exc)

    fmt = read_theme_scalar(theme_file, "impagina-format")
    if fmt is not None:
        try:
            supported = int(fmt) in TEMPLATE_FORMATS
        except ValueError:
            supported = False
        if not supported:
            return ("formato '%s' non supportato: questa versione di impagina "
                    "(%s) gestisce impagina-format %s"
                    % (fmt, __version__, ", ".join(map(str, TEMPLATE_FORMATS))))

    logo = read_theme_scalar(theme_file, "logo")
    if logo and not (directory / logo).is_file():
        return "logo non trovato: %s (chiave 'logo' di theme.yaml)" % logo
    return None


class TemplateScan:
    """
    Esito della ricerca dei template.

    templates: nome -> cartella, in ordine di precedenza (quello che elenca
    GET /template). invalid: nome -> motivo, per i template malformati che non
    sono stati sostituiti da uno valido con lo stesso nome. problems: avvisi
    da mostrare (CLI) o scrivere nel log (API). overrides: template esterni
    che prendono il posto di uno incluso, comportamento voluto e quindi solo
    informativo.
    """

    def __init__(self):
        self.templates = {}
        self.invalid = {}
        self.problems = []
        self.overrides = []


def scan_templates(search_dirs):
    """
    Cerca i template nelle directory indicate, nell'ordine.

    Un template e' una sottocartella con template.typ. Regole:
      - nome duplicato: vince la prima directory, le altre copie sono
        ignorate con un avviso (sostituire un template incluso e' invece
        voluto e non genera avvisi);
      - directory esplicita inesistente o illeggibile: avviso, si prosegue;
      - template malformato (template.typ o theme.yaml illeggibili, formato
        non supportato, logo mancante, theme.yaml senza template.typ):
        errore ed esclusione; se una directory successiva ha un template
        valido con lo stesso nome, si usa quello.
    Le sottocartelle che iniziano con '.' sono ignorate.
    """
    scan = TemplateScan()
    origin = {}
    for tdir in search_dirs:
        if not isinstance(tdir, TemplateDir):
            tdir = TemplateDir(tdir)
        try:
            entries = sorted(e for e in tdir.path.iterdir()
                             if e.is_dir() and not e.name.startswith("."))
        except FileNotFoundError:
            if tdir.explicit:
                scan.problems.append("directory dei template inesistente: %s"
                                     % shown(tdir.path))
            continue
        except OSError as exc:
            scan.problems.append("directory dei template illeggibile: %s (%s)"
                                 % (shown(tdir.path), exc.strerror or exc))
            continue

        for entry in entries:
            name = entry.name
            if not (entry / "template.typ").is_file():
                if (entry / "theme.yaml").is_file():
                    reason = "manca template.typ"
                else:
                    continue   # non e' un template: una cartella qualsiasi
            else:
                reason = check_template(entry)

            if name in scan.templates:
                if tdir.builtin:
                    scan.overrides.append(
                        "template '%s' di %s al posto di quello incluso"
                        % (name, shown(origin[name])))
                elif reason is None:
                    scan.problems.append(
                        "template '%s' in %s ignorato: ha la precedenza "
                        "quello in %s" % (name, shown(tdir.path),
                                          shown(origin[name])))
                continue
            if reason is not None:
                scan.problems.append("template '%s' in %s non valido, escluso: "
                                     "%s" % (name, shown(tdir.path), reason))
                scan.invalid.setdefault(name, reason)
                continue
            if name in scan.invalid:
                scan.problems.append("template '%s': si usa quello in %s"
                                     % (name, shown(tdir.path)))
                del scan.invalid[name]
            scan.templates[name] = entry
            origin[name] = tdir.path
    return scan


def available_templates(search_dirs):
    """Nomi dei template utilizzabili, senza duplicati, in ordine di precedenza."""
    return list(scan_templates(search_dirs).templates)


def resolve_template(name, search_dirs, scan=None):
    """Cartella del template richiesto. La prima directory vince."""
    scan = scan or scan_templates(search_dirs)
    if name in scan.templates:
        return scan.templates[name]

    lista = ", ".join(scan.templates) if scan.templates else "nessuno"
    if name in scan.invalid:
        raise ImpaginaError(
            "template '%s' non valido: %s." % (name, scan.invalid[name]),
            EXIT_TEMPLATE_NOT_FOUND,
            hint="Template disponibili: %s" % lista,
        )
    searched = ", ".join(shown(d.path if isinstance(d, TemplateDir) else d)
                         for d in search_dirs)
    raise ImpaginaError(
        "template '%s' non trovato (cercato in: %s)." % (name, searched),
        EXIT_TEMPLATE_NOT_FOUND,
        hint="Template disponibili: %s" % lista,
    )


_SCALAR_RE = re.compile(r'^([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$')


def read_theme_scalar(theme_file, key):
    """
    Legge una singola chiave scalare di primo livello da theme.yaml.

    Serve solo per 'logo', che va convertito in percorso assoluto prima di
    passarlo a Typst. Tutto il resto del file lo interpreta pandoc, quindi
    qui basta una lettura riga per riga invece di un parser YAML completo
    (evita una dipendenza esterna nell'immagine).
    """
    if not theme_file.is_file():
        return None
    for raw_line in theme_file.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line[0] in " \t#":
            continue
        match = _SCALAR_RE.match(raw_line)
        if match and match.group(1) == key:
            value = match.group(2)
            value = value.split(" #")[0].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value or None
    return None


_TEMPLATE_VAR_RE = re.compile(r"\$(?:if\(|for\()?([A-Za-z][A-Za-z0-9_-]*)\)?\$")


def template_variables(template_file):
    """
    Nomi delle variabili pandoc usate da un template (commenti esclusi).

    Servono a sandbox.lua: una variabile che il filtro non conosce, ma che il
    template usa, viene accettata solo con valori innocui.
    """
    names = set()
    for line in template_file.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("//"):
            continue
        names.update(_TEMPLATE_VAR_RE.findall(line))
    return sorted(names - {"if", "for", "else", "endif", "endfor", "sep"})


# --------------------------------------------------------------------------
# Metadati passati a pandoc
# --------------------------------------------------------------------------

def yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % text


def write_cli_overrides(path, args):
    """
    Scrive i valori passati da riga di comando in un file di metadati.

    pandoc unisce i --metadata-file nell'ordine indicato (l'ultimo vince) e
    lascia comunque la precedenza al front-matter del documento. Questo file
    viene passato DOPO theme.yaml, ottenendo la precedenza voluta:
    front-matter > flag CLI > theme.yaml.
    """
    lines = ["# generato da impagina: override da riga di comando"]
    if args.toc:
        lines.append("toc: true")
    if args.cover is not None:
        lines.append("cover: %s" % yaml_scalar(args.cover))
    if args.watermark:
        lines.append("watermark: %s" % yaml_scalar(args.watermark))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Esecuzione dei comandi esterni
# --------------------------------------------------------------------------

def run(command, verbose, env=None):
    if verbose:
        info("  $ " + " ".join(str(part) for part in command))
    return subprocess.run(
        [str(part) for part in command],
        capture_output=True,
        text=True,
        env=env,
    )


def explain_pandoc_failure(source, stderr):
    """Traduce gli errori di pandoc in messaggi comprensibili."""
    if "YAML parse exception" in stderr or "while parsing a" in stderr:
        line = ""
        match = re.search(r"line (\d+)", stderr)
        if match:
            line = " (riga %s)" % match.group(1)
        return ImpaginaError(
            "%s: front-matter YAML non valido%s." % (source, line),
            EXIT_BAD_FRONTMATTER,
            hint="Controlla il blocco fra '---' in cima al file: "
                 "indentazione con spazi, due punti seguiti da uno spazio, "
                 "virgolette bilanciate.",
        )
    first = next((l for l in stderr.splitlines() if l.strip()), "errore sconosciuto")
    return ImpaginaError(
        "%s: pandoc non e' riuscito a leggere il documento.\n  %s" % (source, first),
        EXIT_RENDER_FAILED,
    )


def explain_sandbox_failure(source, stderr):
    """Traduce il rifiuto di sandbox.lua: il messaggio e' gia' in italiano."""
    for line in stderr.splitlines():
        if SANDBOX_MARKER in line:
            detail = line.split(SANDBOX_MARKER, 1)[1].strip()
            break
    else:
        detail = "contenuto non ammesso."
    return ImpaginaError(
        "%s: %s" % (source, shown_text(detail)),
        EXIT_RENDER_FAILED,
        hint="In modalita' protetta (--sandbox, usata dal servizio API) il "
             "documento puo' usare solo file allegati con percorsi relativi, "
             "metadati con valori semplici e nessun codice Typst grezzo.",
    )


def explain_typst_failure(source, stderr):
    """Traduce gli errori di typst, che referenziano il .typ intermedio."""
    hint = None
    if "file not found" in stderr:
        missing = re.search(r"file not found \(searched at ([^)]+)\)", stderr)
        target = missing.group(1) if missing else "un file referenziato"
        hint = ("Immagine o file non trovato: %s. Verifica il percorso "
                "nel Markdown e che la cartella sia montata nel container."
                % shown_text(target))
    elif "unknown font family" in stderr or "unknown variable" in stderr:
        hint = ("Controlla i valori di theme.yaml: un nome di font o una "
                "variabile del template non esiste.")

    details = []
    for line in stderr.splitlines():
        stripped = line.strip()
        if stripped.startswith("error:"):
            details.append("  " + stripped)
        elif stripped.startswith("┌─") and hint is None:
            # Rimanda al .typ intermedio: utile solo quando l'errore riguarda
            # il template e non abbiamo una spiegazione piu' precisa.
            details.append("  " + stripped)
        if len(details) >= 4:
            break
    body = shown_text("\n".join(details) if details
                       else "  " + stderr.strip().splitlines()[0])
    return ImpaginaError(
        "%s: la compilazione del PDF e' fallita.\n%s" % (source, body),
        EXIT_RENDER_FAILED,
        hint=hint,
    )


# --------------------------------------------------------------------------
# Conversione di un singolo documento
# --------------------------------------------------------------------------

def convert(md_file, pdf_file, template_dir, args, workdir):
    label = shown(md_file)
    theme_file = template_dir / "theme.yaml"
    typ_file = workdir / (md_file.stem + ".typ")
    overrides = workdir / "cli-overrides.yaml"
    write_cli_overrides(overrides, args)

    pandoc_cmd = [
        "pandoc", md_file,
        "--from", "markdown",
        "--to", "typst",
        # Pandoc ricava la larghezza delle colonne dalla riga dei trattini, ma
        # solo per le tabelle piu' larghe di --columns: con il valore
        # predefinito (72) gli stessi trattini contano su una tabella lunga e
        # vengono ignorati su una corta. Abbassando la soglia il comportamento
        # e' lo stesso per tutte; --wrap=none evita che il .typ intermedio vada
        # a capo, cosa che a colonne=1 lo renderebbe illeggibile.
        "--columns", "1",
        "--wrap", "none",
        "--template", template_dir / "template.typ",
        "--output", typ_file,
    ]
    filters = ([SANDBOX_FILTER] if args.sandbox else []) + FILTER_PATHS
    for lua_filter in filters:
        pandoc_cmd += ["--lua-filter", lua_filter]

    if theme_file.is_file():
        pandoc_cmd += ["--metadata-file", theme_file]
    pandoc_cmd += ["--metadata-file", overrides]

    # Il logo va passato come percorso assoluto: il .typ intermedio vive in una
    # cartella temporanea e non potrebbe risolvere un percorso relativo al
    # template. --metadata (a differenza di --metadata-file) non interpreta il
    # valore come Markdown, quindi il percorso arriva a Typst intatto.
    logo = read_theme_scalar(theme_file, "logo")
    if logo:
        logo_path = (template_dir / logo).resolve()
        if not logo_path.is_file():
            raise ImpaginaError(
                "logo non trovato: %s (indicato come 'logo: %s' in %s)."
                % (logo_path, logo, theme_file),
                EXIT_RENDER_FAILED,
                hint="Correggi la chiave 'logo' in theme.yaml oppure aggiungi il file.",
            )
        pandoc_cmd += ["--metadata", "logopath=%s" % logo_path]

    # L'icona del tipo di documento: il template compone il percorso a partire
    # dalla cartella delle icone incluse (doc-type) oppure da quella del
    # Markdown (doc-icon con percorso relativo). Entrambe vanno passate come
    # percorsi assoluti, perche' il .typ intermedio vive in una cartella
    # temporanea e non potrebbe risolvere nulla di relativo.
    icons_dir = template_dir / "assets" / "icons"
    if icons_dir.is_dir():
        pandoc_cmd += ["--metadata", "iconspath=%s" % icons_dir]
    pandoc_cmd += ["--metadata", "docdir=%s" % md_file.resolve().parent]

    pandoc_env = None
    if args.sandbox:
        source = Path(args.input).resolve()
        pandoc_env = dict(os.environ)
        pandoc_env["IMPAGINA_SANDBOX_RADICE"] = str(
            source if source.is_dir() else source.parent)
        pandoc_env["IMPAGINA_SANDBOX_VARIABILI"] = ",".join(
            template_variables(template_dir / "template.typ"))

    result = run(pandoc_cmd, args.verbose, env=pandoc_env)
    if result.returncode != 0:
        if SANDBOX_MARKER in result.stderr:
            raise explain_sandbox_failure(label, result.stderr)
        raise explain_pandoc_failure(label, result.stderr)

    typst_cmd = [
        "typst", "compile",
        "--root", "/",
        "--font-path", SYSTEM_FONT_DIR,
    ]
    fonts_dir = template_dir / "fonts"
    if fonts_dir.is_dir():
        typst_cmd += ["--font-path", fonts_dir]
    typst_cmd += [typ_file, workdir / "out.pdf"]

    result = run(typst_cmd, args.verbose)
    if result.returncode != 0:
        raise explain_typst_failure(label, result.stderr)
    warnings = [shown_text(line.strip()) for line in result.stderr.splitlines()
                if "warning:" in line]
    for warning in warnings:
        warn(warning)

    # Scrittura atomica: il PDF appare nella destinazione gia' completo.
    # Senza questo, il client Nextcloud puo' sincronizzare un file parziale.
    try:
        pdf_file.parent.mkdir(parents=True, exist_ok=True)
        staged = pdf_file.parent / ("." + pdf_file.name + ".impagina-tmp")
        shutil.copyfile(workdir / "out.pdf", staged)
        os.replace(staged, pdf_file)
    except OSError as exc:
        raise ImpaginaError(
            "impossibile scrivere %s (%s)."
            % (shown(pdf_file), exc.strerror or exc),
            EXIT_NOT_WRITABLE,
            hint="Controlla i permessi della cartella e che sia montata in "
                 "scrittura nel container.",
        )
    return warnings


# --------------------------------------------------------------------------
# Individuazione dei file e orchestrazione
# --------------------------------------------------------------------------

def collect_jobs(args):
    """Coppie (file markdown, pdf di destinazione)."""
    source = Path(args.input)
    if not source.exists():
        raise ImpaginaError(
            "file o cartella non trovata: %s" % shown(source),
            EXIT_INPUT_NOT_FOUND,
            hint="Dentro il container i percorsi partono da /data, che "
                 "corrisponde alla cartella montata dall'host.",
        )

    if source.is_file():
        if args.output:
            target = Path(args.output)
            if target.is_dir() or args.output.endswith("/"):
                target = target / (source.stem + ".pdf")
        else:
            target = source.with_suffix(".pdf")
        return [(source, target)]

    pattern = "**/*.md" if args.recursive else "*.md"
    md_files = sorted(p for p in source.glob(pattern) if p.is_file())
    out_root = Path(args.output) if args.output else source
    return [(md, out_root / md.relative_to(source).with_suffix(".pdf"))
            for md in md_files]


def build_parser():
    parser = argparse.ArgumentParser(
        prog="impagina",
        description="Converte documenti Markdown in PDF applicando un template.",
        epilog="Esempi:\n"
               "  impagina --input /data/nota.md --template company\n"
               "  impagina --input /data/note --output /data/pdf "
               "--template company --recursive --toc\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, metavar="PERCORSO",
                        help="file .md oppure cartella da convertire")
    parser.add_argument("--output", "-o", metavar="PERCORSO",
                        help="file .pdf di destinazione, oppure cartella di "
                             "destinazione (default: accanto al sorgente)")
    parser.add_argument("--template", "-t", default="company", metavar="NOME",
                        help="template da applicare (default: company)")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="converte anche le sottocartelle, replicando "
                             "la struttura nella destinazione")
    parser.add_argument("--toc", action="store_true",
                        help="genera l'indice del documento")
    parser.add_argument("--cover", dest="cover", action="store_true", default=None,
                        help="forza la copertina in prima pagina")
    parser.add_argument("--no-cover", dest="cover", action="store_false",
                        help="disattiva la copertina")
    parser.add_argument("--watermark", metavar="TESTO",
                        help='filigrana diagonale su ogni pagina (es. "BOZZA")')
    parser.add_argument("--templates-dir", metavar="PERCORSO",
                        action="append",
                        help="cartella dei template; ripetibile, la prima "
                             "vince. Sostituisce l'elenco predefinito "
                             "(IMPAGINA_TEMPLATES_PATH, poi i template inclusi "
                             "nell'immagine)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="mostra i comandi pandoc e typst eseguiti")
    integration = parser.add_argument_group(
        "integrazione", "opzioni pensate per i programmi che usano impagina "
                        "(per esempio il servizio API)")
    integration.add_argument("--sandbox", action="store_true",
                             help="modalita' protetta per documenti di terzi: "
                                  "niente Typst grezzo, solo immagini relative "
                                  "dentro la cartella di input, metadati "
                                  "validati")
    integration.add_argument("--report", metavar="PERCORSO",
                             help="scrive l'esito di ogni documento in JSON")
    parser.add_argument("--version", action="version",
                        version="impagina %s" % __version__)
    return parser


def error_entry(exc):
    return {"codice_uscita": exc.code, "messaggio": exc.message,
            "suggerimento": exc.hint}


def write_report(path, code, general_errors, documents):
    """
    Esito della conversione in JSON, per chi usa impagina da un programma.

    Contiene gli stessi messaggi stampati su stderr, ma gia' separati per
    documento e senza doverli interpretare. Scrittura atomica, come per i PDF.
    """
    report = {
        "versione": __version__,
        "codice_uscita": code,
        "errori_generali": general_errors,
        "documenti": documents,
    }
    target = Path(path)
    staged = target.parent / ("." + target.name + ".impagina-tmp")
    try:
        staged.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        os.replace(staged, target)
    except OSError as exc:
        err("impossibile scrivere il rapporto %s (%s)."
            % (shown(target), exc.strerror or exc))


def main(argv=None):
    args = build_parser().parse_args(argv)
    code, general_errors, documents = run_jobs(args)
    if args.report:
        write_report(args.report, code, general_errors, documents)
    return code


def run_jobs(args):
    """Esegue le conversioni. Restituisce (codice, errori generali, documenti)."""
    if args.templates_dir:
        search_dirs, notes = [TemplateDir(d) for d in args.templates_dir], []
    else:
        search_dirs, notes = template_dirs_from_env()
    scan = scan_templates(search_dirs)
    for message in notes + scan.problems:
        warn(message)
    if args.verbose:
        for message in scan.overrides:
            info(message)

    try:
        template_dir = resolve_template(args.template, search_dirs, scan)
        jobs = collect_jobs(args)
    except ImpaginaError as exc:
        err(exc.message)
        if exc.hint:
            print("  " + exc.hint, file=sys.stderr)
        return exc.code, [error_entry(exc)], []

    if not jobs:
        warn("nessun file .md trovato in %s%s"
             % (shown(args.input), "" if args.recursive else
                " (usa --recursive per le sottocartelle)"))
        return EXIT_OK, [], []

    converted, failures, documents = 0, [], []
    workdir = Path(tempfile.mkdtemp(prefix="impagina-"))
    try:
        for md_file, pdf_file in jobs:
            try:
                warnings = convert(md_file, pdf_file, template_dir, args, workdir)
                converted += 1
                info("%s  ->  %s" % (shown(md_file), shown(pdf_file)))
                documents.append({"sorgente": shown(md_file),
                                  "pdf": shown(pdf_file),
                                  "esito": "ok", "avvisi": warnings})
            except ImpaginaError as exc:
                # In modalita' cartella un documento rotto non ferma gli altri.
                err(exc.message)
                if exc.hint:
                    print("  " + exc.hint, file=sys.stderr)
                failures.append((md_file, exc.code))
                documents.append(dict({"sorgente": shown(md_file),
                                       "esito": "errore"}, **error_entry(exc)))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if len(jobs) > 1:
        info("\n%d convertiti, %d falliti." % (converted, len(failures)))
    if failures:
        return failures[0][1], [], documents
    return EXIT_OK, [], documents


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        err("interrotto.")
        sys.exit(EXIT_USAGE)
    except BrokenPipeError:
        sys.exit(EXIT_OK)
