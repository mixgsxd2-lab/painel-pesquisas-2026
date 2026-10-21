"""Leitura da API pública de resultados do TSE (resultados.tse.jus.br).

Arquivos usados:  /oficial/ele2026/<cd_eleicao>/dados/<uf>/<uf>-c<cargo:4>-e<cd:6>-u.json
Os códigos das eleições são descobertos em /oficial/comum/config/ele-c.json.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import requests

import settings
from core.textutil import num_br
from pipeline import http

log = logging.getLogger("pipeline.tse_resultados")


@lru_cache(maxsize=1)
def codigos_eleicao() -> dict[str, str]:
    """{'federal_1t','federal_2t','estadual_1t','estadual_2t'} — descobertos no TSE, com fallback."""
    cods = {
        "federal_1t": settings.TSE_COD_FEDERAL_1T,
        "federal_2t": settings.TSE_COD_FEDERAL_2T,
        "estadual_1t": settings.TSE_COD_ESTADUAL_1T,
        "estadual_2t": settings.TSE_COD_ESTADUAL_2T,
    }
    try:
        cfg = http.get(settings.TSE_RESULTADOS_CONFIG, timeout=20).json()
        for pleito in cfg.get("pl", []):
            if pleito.get("c") != f"ele{settings.ANO}":
                continue
            for e in pleito.get("e", []):
                if str(e.get("t")) != "1":
                    continue
                cargos = {c.get("ds", "").lower() for a in e.get("abr", []) for c in a.get("cp", [])}
                if "presidente" in cargos:
                    cods["federal_1t"] = str(e["cd"])
                    if e.get("cdt2"):
                        cods["federal_2t"] = str(e["cdt2"])
                elif "governador" in cargos:
                    cods["estadual_1t"] = str(e["cd"])
                    if e.get("cdt2"):
                        cods["estadual_2t"] = str(e["cdt2"])
    except (requests.RequestException, ValueError, KeyError) as e:
        log.warning("Não foi possível ler ele-c.json (usando códigos padrão): %s", e)
    return cods


def url_arquivo(cod_eleicao: str, abrangencia: str, cargo_tse: int) -> str:
    ab = abrangencia.lower()
    return (
        f"{settings.TSE_RESULTADOS_BASE}/ele{settings.ANO}/{cod_eleicao}/dados/{ab}/"
        f"{ab}-c{cargo_tse:04d}-e{int(cod_eleicao):06d}-u.json"
    )


def baixar(cod_eleicao: str, abrangencia: str, cargo_tse: int) -> dict | None:
    url = url_arquivo(cod_eleicao, abrangencia, cargo_tse)
    try:
        r = http.sessao().get(url, timeout=20)
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, ValueError) as e:
        log.info("Falha ao ler %s: %s", url, e)
        return None


def candidatos_do_arquivo(j: dict) -> list[dict]:
    """Lista plana de candidatos de um arquivo -u.json."""
    out = []
    for c in j.get("carg", []) or []:
        for agr in c.get("agr", []) or []:
            for par in agr.get("par", []) or []:
                for cd in par.get("cand", []) or []:
                    out.append(
                        {
                            "numero": str(cd.get("n", "")),
                            "nome_urna": cd.get("nmu") or cd.get("nm") or "",
                            "nome_completo": cd.get("nm") or "",
                            "partido": par.get("sg") or "",
                            "situacao": (cd.get("st") or "").strip(),
                            "eleito": cd.get("e") == "s",
                            "seq": int(cd.get("seq") or 0) or None,
                            "votos": int(cd.get("vap") or 0),
                            "pct_validos": num_br(cd.get("pvap")),
                        }
                    )
    return out


def resumo_apuracao(j: dict) -> dict:
    """Resumo de um arquivo do 2º turno para o modo Apuração."""
    s = j.get("s") or {}
    v = j.get("v") or {}
    cands = candidatos_do_arquivo(j)
    cands.sort(key=lambda c: (c["seq"] or 99, c["numero"]))
    return {
        "candidatos": [
            {
                "numero": c["numero"],
                "nome": c["nome_urna"],
                "partido": c["partido"],
                "pct": c["pct_validos"],
                "votos": c["votos"],
                "eleito": c["eleito"],
                "seq": c["seq"],
            }
            for c in cands
        ],
        "pst": num_br(s.get("pst")) or 0.0,  # % de seções totalizadas
        "brancos_pct": num_br(v.get("pvb")),
        "nulos_pct": num_br(v.get("ptvn")),
        "totalizacao_final": j.get("tf") == "s",
        "data": j.get("dg") or "",
        "hora": j.get("hg") or "",
    }
