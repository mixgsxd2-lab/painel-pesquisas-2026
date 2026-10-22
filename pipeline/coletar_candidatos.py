"""Descobre automaticamente os candidatos do 2º turno (presidente e governadores).

Fonte: resultados oficiais do 1º turno no TSE (situação "2º turno") e, quando já
publicado, o arquivo do 2º turno (que traz a ordem oficial na urna — campo 'seq').

    python -m pipeline.coletar_candidatos
"""
from __future__ import annotations

import logging
import re

import settings
from core import db, fotos
from core.ufs import UFS
from pipeline import http
from pipeline import tse_resultados as tr

log = logging.getLogger("pipeline.candidatos")


def _vai_ao_2_turno(situacao: str) -> bool:
    s = situacao.lower()
    return "turno" in s and bool(re.search(r"2|segundo", s))


def _ordenar(cands_1t: list[dict], arquivo_2t: dict | None) -> list[dict]:
    """Aplica a ordem da urna do 2º turno (seq), se disponível; senão, ordem do número."""
    seq_2t = {}
    if arquivo_2t:
        for c in tr.candidatos_do_arquivo(arquivo_2t):
            if c["seq"]:
                seq_2t[c["numero"]] = c["seq"]
    if len(seq_2t) >= 2 and all(c["numero"] in seq_2t for c in cands_1t):
        cands_1t.sort(key=lambda c: seq_2t[c["numero"]])
    else:
        cands_1t.sort(key=lambda c: int(c["numero"]) if c["numero"].isdigit() else 999)
    for i, c in enumerate(cands_1t):
        c["ordem"] = i + 1
    return cands_1t


def _salvar(cargo: str, uf: str, cands: list[dict]) -> None:
    agora = settings.agora().isoformat()
    with db.transacao() as c:
        c.execute("DELETE FROM candidatos WHERE cargo = ? AND uf = ?", (cargo, uf))
        for cd in cands:
            c.execute(
                "INSERT INTO candidatos(cargo, uf, numero, nome_urna, nome_completo, partido, ordem, atualizado_em) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (cargo, uf, cd["numero"], cd["nome_urna"], cd["nome_completo"], cd["partido"], cd["ordem"], agora),
            )


def _baixar_fotos(cargo: str, uf: str, cod_eleicao: str, cands: list[dict]) -> None:
    """Baixa a foto oficial de cada candidato no TSE (só se ainda não existir)."""
    fotos.PASTA.mkdir(parents=True, exist_ok=True)
    ab = "br" if uf == "BR" else uf
    for c in cands:
        destino = fotos.PASTA / fotos.nome_arquivo(cargo, uf, c["numero"])
        if destino.exists() or not c.get("sqcand"):
            continue
        try:
            r = http.sessao().get(tr.url_foto(cod_eleicao, ab, c["sqcand"]), timeout=20)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                destino.write_bytes(r.content)
        except Exception as e:  # noqa: BLE001 - foto é opcional
            log.info("Foto de %s indisponível: %s", c["nome_urna"], e)


def coletar() -> dict:
    cods = tr.codigos_eleicao()
    resumo = {"presidente": 0, "governador_ufs": []}

    # Presidente
    j1 = tr.baixar(cods["federal_1t"], "br", 1)
    if j1:
        cands = [c for c in tr.candidatos_do_arquivo(j1) if _vai_ao_2_turno(c["situacao"])]
        if len(cands) == 2:
            j2 = tr.baixar(cods["federal_2t"], "br", 1)
            _salvar("presidente", "BR", _ordenar(cands, j2))
            _baixar_fotos("presidente", "BR", cods["federal_1t"], cands)
            resumo["presidente"] = 2
        else:
            log.warning("Presidente: esperados 2 candidatos no 2º turno, achados %d", len(cands))
    else:
        log.warning("Resultado do 1º turno (presidente) indisponível; mantendo candidatos atuais.")

    # Governadores
    for uf in UFS:
        j1 = tr.baixar(cods["estadual_1t"], uf, 3)
        if not j1:
            continue
        cands = [c for c in tr.candidatos_do_arquivo(j1) if _vai_ao_2_turno(c["situacao"])]
        if len(cands) == 2:
            j2 = tr.baixar(cods["estadual_2t"], uf, 3)
            _salvar("governador", uf, _ordenar(cands, j2))
            _baixar_fotos("governador", uf, cods["estadual_1t"], cands)
            resumo["governador_ufs"].append(uf)
        else:
            # sem 2º turno (ou situação pendente): remove eventuais registros antigos
            db.executar("DELETE FROM candidatos WHERE cargo = 'governador' AND uf = ?", (uf,))

    db.set_meta("candidatos_atualizados_em", settings.agora().isoformat())
    log.info("Candidatos: presidente=%s, governador em %s", resumo["presidente"], resumo["governador_ufs"])
    return resumo


if __name__ == "__main__":
    from pipeline.run import configurar_log

    configurar_log()
    db.init_db()
    print(coletar())
