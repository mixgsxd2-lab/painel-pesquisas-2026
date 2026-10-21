"""Testes das regras críticas (rode com:  python -m unittest discover -s tests -v)."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("DB_PATH", str(Path(tempfile.mkdtemp()) / "teste.db"))
os.environ["RUN_SCHEDULER"] = "0"

from core import db  # noqa: E402
from core.textutil import protocolo_de_slug, regex_registro, registro_fmt, registro_slug  # noqa: E402
from pipeline import extrair, tse_texto, validar  # noqa: E402

APELIDOS = {"13": ["lula"], "22": ["flavio bolsonaro", "bolsonaro"]}


class Registro(unittest.TestCase):
    def test_formatos(self):
        self.assertEqual(registro_fmt("BR087292026"), "BR-08729/2026")
        self.assertEqual(registro_slug("BR087292026"), "BR-08729-2026")
        self.assertEqual(protocolo_de_slug("BR-08729-2026"), "BR087292026")

    def test_achar_na_pagina(self):
        rx = regex_registro("BR087292026")
        for t in ("registrada sob o número BR-08729/2026", "BR 08729/2026", "BR-8729/2026", "br087292026"):
            self.assertTrue(rx.search(t), t)
        self.assertFalse(rx.search("BR-08730/2026"))


class TextoTSE(unittest.TestCase):
    def test_margem_e_confianca(self):
        t = ("O nível de confiança estimado é de 95% e a margem de erro máxima estimada, considerando um modelo "
             "de amostragem aleatório simples, é de aproximadamente 2 (dois) pontos percentuais para mais ou para menos.")
        self.assertEqual(tse_texto.margem_erro(t), 2.0)
        self.assertEqual(tse_texto.nivel_confianca(t), 95.0)

    def test_margem_ignora_lista_de_cotas(self):
        t = ("cálculo da margem de erro e dos intervalos de confiança. gênero: masculino: 47%; feminino: 53%; "
             "16-24: 13%; ... Margem de erro: a margem de erro máxima estimada é de 2,5% para mais ou para menos")
        self.assertEqual(tse_texto.margem_erro(t), 2.5)

    def test_abrangencia(self):
        self.assertEqual(tse_texto.abrangencia("amostra representativa do eleitorado do Estado do Tocantins"), "TO")
        self.assertEqual(tse_texto.abrangencia("pesquisa de abrangência nacional, estratificada pelas grandes regiões"), "BR")
        self.assertIsNone(tse_texto.abrangencia("eleitores das áreas pesquisadas"))


class Extracao(unittest.TestCase):
    def test_bloco_totais(self):
        t = ("A pesquisa mostra Flávio Bolsonaro (PL) com 46% e Lula (PT) com 44% das intenções de voto. "
             "Nenhum/branco/nulo somariam 9% e 1% estaria indeciso.")
        b = extrair.extrair(t, APELIDOS)[0]
        self.assertEqual(b["tipo"], "totais")
        self.assertEqual(b["candidatos"], {"22": 46.0, "13": 44.0})
        self.assertEqual((b["brancos_nulos"], b["indecisos"]), (9.0, 1.0))

    def test_numero_invertido(self):
        t = ("Flávio Bolsonaro tem 46% e Lula, 44%. Ainda, 9% disseram que votarão em branco ou nulo no "
             "segundo turno, outros 1% se disseram indecisos.")
        b = extrair.extrair(t, APELIDOS)[0]
        self.assertEqual((b["brancos_nulos"], b["indecisos"]), (9.0, 1.0))

    def test_validos(self):
        t = "Nos votos válidos, Flávio Bolsonaro tem 51% e Lula 49%."
        b = extrair.extrair(t, APELIDOS)[0]
        self.assertEqual(b["tipo"], "validos")

    def test_sem_tipo_nao_inventa(self):
        t = "Flávio Bolsonaro aparece com 46% e Lula com 40%."
        self.assertIsNone(extrair.extrair(t, APELIDOS)[0]["tipo"])


class Validacao(unittest.TestCase):
    def test_tolerancia(self):
        a = {"candidatos": {"13": 44.0, "22": 46.0}, "brancos_nulos": 9.0, "indecisos": None}
        b = {"candidatos": {"13": 44.5, "22": 45.5}, "brancos_nulos": None, "indecisos": 1.0}
        c = {"candidatos": {"13": 44.6, "22": 46.0}, "brancos_nulos": None, "indecisos": None}
        self.assertTrue(validar.iguais(a, b))
        self.assertFalse(validar.iguais(a, c))

    def test_soma(self):
        self.assertEqual(validar.soma({"candidatos": {"1": 46, "2": 44}, "brancos_nulos": 9, "indecisos": 1}), 100)

    def test_datas(self):
        p = {"data_registro": "2026-10-08 23:51:00", "data_divulgacao": "2026-10-11"}
        self.assertIn("menos de 5 dias", validar.checar_datas(p))
        p = {"data_registro": "2026-10-08 23:51:00", "data_divulgacao": "2026-10-14"}
        self.assertIsNone(validar.checar_datas(p))


class Historico(unittest.TestCase):
    def test_somente_insercao(self):
        db.init_db()
        db.executar("INSERT INTO historico(registrado_em, evento, cargo, chave, valor, fontes) "
                    "VALUES('x','PUBLICACAO','presidente','13',44,'teste')")
        with self.assertRaises(sqlite3.DatabaseError):
            db.executar("UPDATE historico SET valor = 1")
        with self.assertRaises(sqlite3.DatabaseError):
            db.executar("DELETE FROM historico")


if __name__ == "__main__":
    unittest.main()
