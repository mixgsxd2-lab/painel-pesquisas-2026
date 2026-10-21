"""Modo Apuração — a partir de 25/10/2026 às 17h (Brasília) consome os resultados oficiais
do 2º turno divulgados pelo TSE (resultados.tse.jus.br).

    python -m pipeline.apuracao
"""
from __future__ import annotations

import logging

import settings
from core import candidatos as cand_mod
from core import db
from core.ufs import UFS
from pipeline import tse_resultados as tr

log = logging.getLogger("pipeline.apuracao")


def em_apuracao() -> bool:
    return settings.agora() >= settings.INICIO_APURACAO


def _salvar(cargo: str, uf: str, resumo: dict, agora: str) -> bool:
    ant = db.q1("SELECT pst, atualizado_tse FROM apuracao WHERE cargo = ? AND uf = ?", (cargo, uf))
    carimbo = f"{resumo['data']} {resumo['hora']}".strip()
    if ant and ant["atualizado_tse"] == carimbo:
        return False
    with db.transacao() as c:
        c.execute(
            "INSERT INTO apuracao(cargo, uf, dados, pst, atualizado_tse, obtido_em) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(cargo, uf) DO UPDATE SET dados=excluded.dados, pst=excluded.pst, "
            "atualizado_tse=excluded.atualizado_tse, obtido_em=excluded.obtido_em",
            (cargo, uf, db.jdumps(resumo), resumo["pst"], carimbo, agora),
        )
        if resumo["pst"] and (not ant or ant["pst"] != resumo["pst"]):
            fonte = f"Resultados: TSE ({carimbo}; {resumo['pst']:.2f}% das seções totalizadas)"
            for cd in resumo["candidatos"]:
                c.execute(
                    "INSERT INTO historico(registrado_em, evento, cargo, uf, tipo, chave, rotulo, valor, fontes) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (agora, "APURACAO", cargo, uf, "validos", cd["numero"], cd["nome"], cd["pct"], fonte),
                )
        db.set_meta("dados_atualizados_em", agora, c)
    return True


def coletar(forcar: bool = False) -> dict:
    if not (forcar or em_apuracao()):
        return {"ativo": False}
    cods = tr.codigos_eleicao()
    agora = settings.agora().isoformat()
    alterados = 0
    alvos = [("presidente", "BR", cods["federal_2t"], 1)]
    alvos += [("presidente", uf, cods["federal_2t"], 1) for uf in UFS]
    alvos += [("governador", uf, cods["estadual_2t"], 3) for uf in cand_mod.ufs_com_2_turno_governador()]
    for cargo, uf, cod, cargo_tse in alvos:
        j = tr.baixar(cod, uf, cargo_tse)
        if not j:
            continue
        resumo = tr.resumo_apuracao(j)
        if _salvar(cargo, uf, resumo, agora):
            alterados += 1
    log.info("Apuração: %d arquivos atualizados", alterados)
    return {"ativo": True, "atualizados": alterados}


if __name__ == "__main__":
    import sys

    from pipeline.run import configurar_log

    configurar_log()
    db.init_db()
    print(coletar(forcar="--forcar" in sys.argv))
