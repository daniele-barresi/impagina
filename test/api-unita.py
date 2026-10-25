#!/usr/bin/env python3
"""
Test di unita' del servizio API: le parti che maneggiano input ostile
(nomi di file, multipart, ZIP, chiavi) e che conviene provare caso per caso,
senza passare da HTTP.

Si eseguono dentro l'immagine, dove c'e' il pacchetto:

  docker run --rm --entrypoint python3 -v "$PWD/test:/test:ro" \\
      impagina-api /test/api-unita.py

Solo libreria standard (unittest), come il resto del progetto.
"""

import io
import os
import re
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, os.environ.get("IMPAGINA_SRC", "/opt/impagina"))

from impagina_api import archivi, chiavi, configurazione, multipart, percorsi  # noqa: E402
from impagina_api.errori import ErroreRichiesta  # noqa: E402


class PercorsiSicuri(unittest.TestCase):
    def rifiuta(self, nome):
        with self.assertRaises(ErroreRichiesta) as ctx:
            percorsi.percorso_sicuro(nome)
        self.assertEqual(ctx.exception.codice, "percorso_non_valido")

    def test_percorsi_normali(self):
        self.assertEqual(percorsi.percorso_sicuro("immagini/a.png"),
                         PurePosixPath("immagini/a.png"))
        self.assertEqual(percorsi.percorso_sicuro("./a//b/./c.svg"),
                         PurePosixPath("a/b/c.svg"))
        self.assertEqual(percorsi.percorso_sicuro("immagini\\a.png"),
                         PurePosixPath("immagini/a.png"))
        self.assertEqual(percorsi.percorso_sicuro("città/perché.png"),
                         PurePosixPath("città/perché.png"))

    def test_percorsi_ostili(self):
        for nome in ["../a", "a/../../b", "a/..", "/etc/passwd", "\\etc\\x",
                     "C:\\x", "c:x", "", "   ", ".", "a\x00b", "a\nb",
                     "/".join(["d"] * 17), "x" * 256]:
            with self.subTest(nome=nome):
                self.rifiuta(nome)

    def test_spazzatura_saltata(self):
        for nome in ["__MACOSX/a.png", "a/.DS_Store", "a/._x.png", "Thumbs.db"]:
            self.assertIsNone(percorsi.percorso_sicuro(nome))

    def test_scrittura_esclusiva_e_budget(self):
        with tempfile.TemporaryDirectory() as radice:
            budget = percorsi.Budget(10, 2)
            percorsi.scrivi_file_sicuro(radice, PurePosixPath("a/b.txt"), [b"12345"], budget)
            with self.assertRaises(ErroreRichiesta):   # stesso percorso due volte
                percorsi.scrivi_file_sicuro(radice, PurePosixPath("a/b.txt"), [b"1"], budget)
            with self.assertRaises(ErroreRichiesta) as ctx:   # oltre i byte
                percorsi.scrivi_file_sicuro(radice, PurePosixPath("c.txt"),
                                            [b"123456"], percorsi.Budget(5, 5))
            self.assertEqual(ctx.exception.codice, "troppo_grande")
            with self.assertRaises(ErroreRichiesta) as ctx:   # oltre i file
                limitato = percorsi.Budget(100, 1)
                percorsi.scrivi_file_sicuro(radice, PurePosixPath("d1"), [b""], limitato)
                percorsi.scrivi_file_sicuro(radice, PurePosixPath("d2"), [b""], limitato)
            self.assertEqual(ctx.exception.codice, "troppi_file")

    def test_non_segue_symlink(self):
        with tempfile.TemporaryDirectory() as radice, \
                tempfile.TemporaryDirectory() as fuori:
            os.symlink(fuori, os.path.join(radice, "link"))
            with self.assertRaises(ErroreRichiesta):
                percorsi.scrivi_file_sicuro(radice, PurePosixPath("link/x"),
                                            [b"x"], percorsi.Budget(10, 10))
            self.assertEqual(os.listdir(fuori), [])


def corpo_multipart(parti, boundary=b"XyZ-confine"):
    """parti: [(nome, filename|None, contenuto bytes)]"""
    righe = [b"preambolo da ignorare\r\n"]
    for nome, filename, contenuto in parti:
        disp = b'form-data; name="%s"' % nome.encode()
        if filename is not None:
            disp += b'; filename="%s"' % filename.encode("utf-8")
        righe.append(b"--" + boundary + b"\r\nContent-Disposition: " + disp
                     + b"\r\nContent-Type: application/octet-stream\r\n\r\n"
                     + contenuto + b"\r\n")
    righe.append(b"--" + boundary + b"--\r\nepilogo")
    return b"".join(righe), boundary


class FlussoLento(io.RawIOBase):
    """Restituisce al massimo `passo` byte per lettura: simula la rete."""

    def __init__(self, dati, passo):
        self.dati, self.passo, self.pos = dati, passo, 0

    def read(self, n=-1):
        n = self.passo if n < 0 else min(n, self.passo)
        blocco = self.dati[self.pos:self.pos + n]
        self.pos += len(blocco)
        return blocco


def leggi(corpo, boundary, passo=65536):
    risultato = []
    flusso = multipart.LettoreLimitato(FlussoLento(corpo, passo), len(corpo))
    for parte in multipart.leggi_parti(flusso, boundary):
        risultato.append((parte.nome, parte.filename, b"".join(parte.blocchi())))
    return risultato


class Multipart(unittest.TestCase):
    PARTI = [("template", None, b"company"),
             ("documento", "nota.md", b"# Titolo\r\n\r\ntesto --XyZ quasi\r\n"),
             ("allegato", "immagini/a.bin", bytes(range(256)) * 50)]

    def test_boundary(self):
        self.assertEqual(multipart.boundary_da('multipart/form-data; boundary="a b"'), b"a b")
        self.assertEqual(multipart.boundary_da("multipart/form-data; boundary=xyz"), b"xyz")
        for errato in ["multipart/form-data", "multipart/form-data; boundary=" + "x" * 71]:
            with self.assertRaises(ErroreRichiesta):
                multipart.boundary_da(errato)

    def test_delimitatore_a_cavallo_dei_blocchi(self):
        # L'insidia classica: il delimitatore spezzato fra due letture.
        # Con tutti i passi da 1 a 60 byte ogni offset viene toccato.
        corpo, boundary = corpo_multipart(self.PARTI)
        for passo in list(range(1, 61)) + [4096, 65536]:
            with self.subTest(passo=passo):
                self.assertEqual(leggi(corpo, boundary, passo), self.PARTI)

    def test_nomi_file(self):
        corpo = (b'--b\r\nContent-Disposition: form-data; name="allegato"; '
                 b"filename*=UTF-8''citt%C3%A0.png\r\n\r\nx\r\n"
                 b'--b\r\nContent-Disposition: form-data; name="allegato"; '
                 b'filename="perch\xc3\xa9 \\"s\\".png"\r\n\r\ny\r\n--b--\r\n')
        nomi = [f for _, f, _ in leggi(corpo, b"b")]
        self.assertEqual(nomi, ["città.png", 'perché "s".png'])

    def test_corpi_malformati(self):
        corpo, boundary = corpo_multipart(self.PARTI)
        for troncato in [corpo[:len(corpo) // 2], corpo.replace(b"--XyZ-confine--", b"")]:
            with self.subTest(lunghezza=len(troncato)):
                with self.assertRaises(ErroreRichiesta):
                    leggi(troncato, boundary)
        senza_nome = b"--b\r\nContent-Disposition: form-data\r\n\r\nx\r\n--b--\r\n"
        with self.assertRaises(ErroreRichiesta):
            leggi(senza_nome, b"b")
        intestazioni_infinite = b"--b\r\n" + b"X: " + b"y" * 20000
        with self.assertRaises(ErroreRichiesta):
            leggi(intestazioni_infinite, b"b")

    def test_campo_troppo_lungo(self):
        corpo, boundary = corpo_multipart([("toc", None, b"x" * 5000)])
        flusso = multipart.LettoreLimitato(io.BytesIO(corpo), len(corpo))
        with self.assertRaises(ErroreRichiesta):
            for parte in multipart.leggi_parti(flusso, boundary):
                parte.leggi_tutto(4096)

    def test_parte_non_letta_viene_scartata(self):
        corpo, boundary = corpo_multipart(self.PARTI)
        flusso = multipart.LettoreLimitato(io.BytesIO(corpo), len(corpo))
        nomi = [p.nome for p in multipart.leggi_parti(flusso, boundary)]
        self.assertEqual(nomi, ["template", "documento", "allegato"])

    def test_non_legge_oltre_content_length(self):
        corpo, boundary = corpo_multipart(self.PARTI)
        sorgente = io.BytesIO(corpo + b"DATI DELLA RICHIESTA SUCCESSIVA")
        flusso = multipart.LettoreLimitato(sorgente, len(corpo))
        list(multipart.leggi_parti(flusso, boundary))
        self.assertEqual(sorgente.read(), b"DATI DELLA RICHIESTA SUCCESSIVA")


class Archivi(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def zip_(self, voci, nome="a.zip"):
        percorso = self.base / nome
        with zipfile.ZipFile(percorso, "w", zipfile.ZIP_DEFLATED) as zf:
            for voce, contenuto in voci:
                zf.writestr(voce, contenuto)
        return percorso

    def estrai(self, percorso, max_espanso=10 ** 6, max_file=50):
        destinazione = self.base / "out"
        destinazione.mkdir(exist_ok=True)
        return archivi.estrai_zip(percorso, destinazione, max_espanso, max_file)

    def test_cartella_principale_tolta(self):
        z = self.zip_([("note/a.md", "x"), ("note/img/b.png", "y"), ("__MACOSX/._a", "z")])
        self.assertEqual(sorted(map(str, self.estrai(z))), ["a.md", "img/b.png"])
        self.assertTrue((self.base / "out/img/b.png").is_file())

    def test_piu_cartelle_restano(self):
        z = self.zip_([("uno/a.md", "x"), ("due/b.md", "y")])
        self.assertEqual(sorted(map(str, self.estrai(z))), ["due/b.md", "uno/a.md"])

    def test_zip_slip(self):
        for voce in ["../fuori.md", "/assoluto.md", "a/../../fuori.md"]:
            with self.subTest(voce=voce):
                z = self.zip_([(voce, "x")], nome="slip.zip")
                with self.assertRaises(ErroreRichiesta):
                    self.estrai(z)
        self.assertFalse((self.base / "fuori.md").exists())

    def test_symlink(self):
        percorso = self.base / "link.zip"
        with zipfile.ZipFile(percorso, "w") as zf:
            info = zipfile.ZipInfo("link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
        with self.assertRaises(ErroreRichiesta) as ctx:
            self.estrai(percorso)
        self.assertEqual(ctx.exception.codice, "percorso_non_valido")

    def test_zip_bomb(self):
        z = self.zip_([("zeri.md", b"\0" * 2 * 10 ** 6)])
        self.assertLess(z.stat().st_size, 10 ** 5)
        with self.assertRaises(ErroreRichiesta) as ctx:
            self.estrai(z, max_espanso=10 ** 6)
        self.assertEqual(ctx.exception.codice, "troppo_grande")

    def test_dimensione_dichiarata_falsa(self):
        # L'intestazione dichiara 10 byte, ma il contenuto e' molto piu' grande.
        z = self.zip_([("finto.md", b"a" * 50000)])
        dati = bytearray(z.read_bytes())
        for trovato in re.finditer(rb"PK\x01\x02|PK\x03\x04", bytes(dati)):
            campo = trovato.start() + (24 if dati[trovato.start() + 2] == 1 else 22)
            dati[campo:campo + 4] = (10).to_bytes(4, "little")
        z.write_bytes(bytes(dati))
        with self.assertRaises(ErroreRichiesta):
            self.estrai(z)

    def test_troppi_file_e_non_zip(self):
        z = self.zip_([("f%d.md" % i, "x") for i in range(6)])
        with self.assertRaises(ErroreRichiesta) as ctx:
            self.estrai(z, max_file=5)
        self.assertEqual(ctx.exception.codice, "troppi_file")
        falso = self.base / "falso.zip"
        falso.write_bytes(b"non sono uno zip")
        with self.assertRaises(ErroreRichiesta) as ctx:
            self.estrai(falso)
        self.assertEqual(ctx.exception.codice, "zip_non_valido")


class Chiavi(unittest.TestCase):
    def test_verifica_e_revoca(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d, "chiavi.conf")
            file.write_text("# commento\nnextcloud sha256:%s\naltra sha256:%s\n"
                            % (chiavi.impronta("imp_a"), chiavi.impronta("imp_b")))
            registro = chiavi.RegistroChiavi(file)
            self.assertEqual(registro.verifica("Bearer imp_a"), "nextcloud")
            self.assertEqual(registro.verifica("bearer  imp_b "), "altra")
            for errata in [None, "", "Bearer", "Bearer imp_c", "Basic imp_a", "imp_a"]:
                self.assertIsNone(registro.verifica(errata))
            file.write_text("# nextcloud revocata\naltra sha256:%s\n"
                            % chiavi.impronta("imp_b"))
            os.utime(file, ns=(0, 10 ** 18))   # mtime diverso anche se nello stesso istante
            self.assertIsNone(registro.verifica("Bearer imp_a"))
            self.assertEqual(registro.verifica("Bearer imp_b"), "altra")

    def test_file_vuoto_o_assente(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                chiavi.RegistroChiavi(Path(d, "manca.conf"))
            vuoto = Path(d, "vuoto.conf")
            vuoto.write_text("# nessuna chiave\nrotta sha256:xyz\n")
            with self.assertRaises(ValueError):
                chiavi.RegistroChiavi(vuoto)


class Configurazione(unittest.TestCase):
    def test_predefiniti_e_dimensioni(self):
        cfg = configurazione.carica({"IMPAGINA_API_MAX_CORPO": "2M"})
        self.assertEqual(cfg.worker, 1)
        self.assertEqual(cfg.max_corpo, 2 * 1024 ** 2)
        self.assertFalse(cfg.typst_grezzo)

    def test_valori_errati(self):
        for nome, valore in [("IMPAGINA_API_WORKER", "0"), ("IMPAGINA_API_WORKER", "x"),
                             ("IMPAGINA_API_MAX_CORPO", "tanto"),
                             ("IMPAGINA_API_TYPST_GREZZO", "forse")]:
            with self.subTest(nome=nome, valore=valore):
                with self.assertRaises(configurazione.ErroreConfigurazione):
                    configurazione.carica({nome: valore})


class VariabiliDeiTemplate(unittest.TestCase):
    """Ogni variabile dei template inclusi deve essere classificata in
    sandbox.lua: un template nuovo non puo' aprire un buco in silenzio."""

    def test_tutte_classificate(self):
        import impagina
        radice = Path(impagina.__file__).resolve().parent
        classificate = set(re.findall(r'\["([a-z0-9-]+)"\]\s*=',
                                      (radice / "filters/sandbox.lua").read_text()))
        cartelle = [Path(os.environ.get("IMPAGINA_BUILTIN_TEMPLATES",
                                        radice / "templates"))]
        trovati = [t for c in cartelle for t in sorted(c.glob("*/template.typ"))]
        self.assertTrue(trovati, "nessun template trovato in %s" % cartelle)
        for cartella in cartelle:
            for template in sorted(cartella.glob("*/template.typ")):
                with self.subTest(template=template.parent.name):
                    mancanti = set(impagina.template_variables(template)) - classificate
                    self.assertEqual(mancanti, set(),
                                     "variabili non classificate in sandbox.lua")


class CartelleDeiTemplate(unittest.TestCase):
    """Da dove si caricano i template: precedenza, duplicati, errori."""

    def setUp(self):
        import impagina
        self.impagina = impagina
        self._tmp = tempfile.TemporaryDirectory()
        self.radice = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def template(self, cartella, nome, tema=None, typ=True):
        t = self.radice / cartella / nome
        t.mkdir(parents=True)
        if typ:
            (t / "template.typ").write_text("$body$\n", encoding="utf-8")
        if tema is not None:
            (t / "theme.yaml").write_text(tema, encoding="utf-8")
        return t

    def cartelle(self, env):
        dirs, note = self.impagina.template_dirs_from_env(env)
        return [str(d.path) for d in dirs], note

    def test_variabili_d_ambiente(self):
        incluso = "/opt/impagina/templates"
        self.assertEqual(self.cartelle({}), (["/templates", incluso], []))
        self.assertEqual(self.cartelle({"IMPAGINA_TEMPLATES": "/x"}),
                         (["/x", incluso], []))
        self.assertEqual(self.cartelle({"IMPAGINA_TEMPLATES_PATH": "/a::/b"}),
                         (["/a", "/b", incluso], []))
        dirs, note = self.cartelle({"IMPAGINA_TEMPLATES_PATH": "/a",
                                    "IMPAGINA_TEMPLATES": "/x"})
        self.assertEqual(dirs, ["/a", incluso])
        self.assertEqual(len(note), 1)
        self.assertIn("IMPAGINA_TEMPLATES ignorata", note[0])
        # Vuota: nessuna directory esterna, solo i template inclusi.
        self.assertEqual(self.cartelle({"IMPAGINA_TEMPLATES_PATH": ""}),
                         ([incluso], []))

    def test_ordine_e_duplicati(self):
        imp = self.impagina
        self.template("a", "zeta")
        self.template("a", "alfa")
        self.template("b", "alfa")
        self.template("b", "beta")
        self.template("incl", "alfa")
        dirs = [imp.TemplateDir(self.radice / "a"), imp.TemplateDir(self.radice / "b"),
                imp.TemplateDir(self.radice / "incl", builtin=True)]
        scan = imp.scan_templates(dirs)
        self.assertEqual(list(scan.templates), ["alfa", "zeta", "beta"])
        self.assertEqual(scan.templates["alfa"], self.radice / "a" / "alfa")
        self.assertEqual(len(scan.problems), 1)
        self.assertIn("template 'alfa' in %s ignorato" % (self.radice / "b"),
                      scan.problems[0])
        # Sostituire un template incluso e' voluto: solo informativo.
        self.assertEqual(len(scan.overrides), 1)

    def test_directory_inesistente(self):
        imp = self.impagina
        self.template("a", "alfa")
        assente = self.radice / "assente"
        scan = imp.scan_templates([imp.TemplateDir(assente), imp.TemplateDir(self.radice / "a")])
        self.assertEqual(list(scan.templates), ["alfa"])
        self.assertEqual(scan.problems,
                         ["directory dei template inesistente: %s" % assente])
        # Il /templates predefinito puo' non essere montato: nessun avviso.
        scan = imp.scan_templates([imp.TemplateDir(assente, explicit=False)])
        self.assertEqual(scan.problems, [])

    def test_template_malformati(self):
        imp = self.impagina
        self.template("a", "formato", tema="impagina-format: 2\n")
        self.template("a", "nonnumero", tema='impagina-format: "uno"\n')
        self.template("a", "senzalogo", tema="logo: assets/logo.svg\n")
        self.template("a", "senzatyp", tema="accent: 000000\n", typ=False)
        self.template("a", "illeggibile", tema=None)
        (self.radice / "a" / "illeggibile" / "template.typ").write_bytes(b"\xff\xfe\x00")
        self.template("a", "buono", tema="impagina-format: 1 # commento\n")
        self.template("a", ".nascosto")
        (self.radice / "a" / "vuota").mkdir()
        scan = imp.scan_templates([imp.TemplateDir(self.radice / "a")])
        self.assertEqual(list(scan.templates), ["buono"])
        self.assertEqual(sorted(scan.invalid),
                         ["formato", "illeggibile", "nonnumero", "senzalogo", "senzatyp"])
        self.assertIn("formato '2' non supportato", scan.invalid["formato"])
        self.assertIn("logo non trovato", scan.invalid["senzalogo"])
        self.assertEqual(scan.invalid["senzatyp"], "manca template.typ")
        self.assertEqual(len(scan.problems), 5)
        with self.assertRaises(imp.ImpaginaError) as ctx:
            imp.resolve_template("formato", [imp.TemplateDir(self.radice / "a")])
        self.assertEqual(ctx.exception.code, imp.EXIT_TEMPLATE_NOT_FOUND)
        self.assertIn("non valido", ctx.exception.message)

    def test_un_template_malformato_lascia_il_posto_al_successivo(self):
        imp = self.impagina
        self.template("a", "company", tema="impagina-format: 9\n")
        self.template("incl", "company")
        scan = imp.scan_templates([imp.TemplateDir(self.radice / "a"),
                                   imp.TemplateDir(self.radice / "incl", builtin=True)])
        self.assertEqual(scan.templates["company"], self.radice / "incl" / "company")
        self.assertEqual(scan.invalid, {})
        self.assertEqual(len(scan.problems), 2)

    def test_configurazione_del_servizio(self):
        cfg = configurazione.carica({"IMPAGINA_TEMPLATES_PATH": "/a:/b",
                                     "IMPAGINA_API_WORKER": "2"})
        self.assertEqual([str(d.path) for d in cfg.cartelle_template],
                         ["/a", "/b", "/opt/impagina/templates"])
        # Alle conversioni arrivano solo le variabili dei template impostate.
        self.assertEqual(cfg.variabili_template, (("IMPAGINA_TEMPLATES_PATH", "/a:/b"),))


if __name__ == "__main__":
    unittest.main(verbosity=2)
