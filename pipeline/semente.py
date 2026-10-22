"""Semente de dados: cópia das pesquisas já publicadas, guardada no repositório.

No plano gratuito do Render o disco é temporário. Ao iniciar com o banco vazio, o site
carrega `semente/publicadas.json` e já mostra as pesquisas validadas; a coleta automática
continua e acrescenta as novas por cima.

    python -m pipeline.semente exportar
"""
from __future__ import annotations

import json
import logging
import threading

import settings
from core import db

log = logging.getLogger("pipeline.semente")

ARQUIVO = settings.BASE_DIR / "semente" / "publicadas.json"
_trava = threading.Lock()


def exportar() -> int:
    if settings.DEMO:
        return 0
    with _trava:
        pesq = [dict(r) for r in db.q("SELECT * FROM pesquisas WHERE status != 'SEM_REGISTRO'")]
        if not any(p["status"] == "PUBLICADA" for p in pesq):
            return 0
        for p in pesq:  # todas as registradas; textos longos só nas publicadas
            if p["status"] != "PUBLICADA":
                p["metodologia"] = p["plano_amostral"] = ""
        chaves = {(p["protocolo"], p["cargo"]) for p in pesq if p["status"] == "PUBLICADA"}
        res = [dict(r) for r in db.q("SELECT * FROM resultados") if (r["protocolo"], r["cargo"]) in chaves]
        cands = [dict(r) for r in db.q("SELECT * FROM candidatos")]
        meta = {r["chave"]: r["valor"] for r in db.q(
            "SELECT chave, valor FROM meta WHERE chave = 'dados_atualizados_em' OR chave LIKE 'atualizado:%' "
            "OR chave = 'candidatos_atualizados_em'")}
        ARQUIVO.parent.mkdir(exist_ok=True)
        tmp = ARQUIVO.with_suffix(".tmp")
        tmp.write_text(json.dumps({"pesquisas": pesq, "resultados": res, "candidatos": cands, "meta": meta},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(ARQUIVO)
        return sum(1 for p in pesq if p["status"] == "PUBLICADA")


def _inserir(c, tabela: str, linhas: list[dict]) -> None:
    for ln in linhas:
        cols = list(ln)
        c.execute(f"INSERT OR IGNORE INTO {tabela}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                  [ln[k] for k in cols])


def importar_se_vazio() -> int:
    """Carrega a semente se o banco ainda não tem nenhuma pesquisa publicada."""
    if settings.DEMO or not ARQUIVO.exists():
        return 0
    if db.q1("SELECT 1 FROM pesquisas WHERE status = 'PUBLICADA' LIMIT 1"):
        return 0
    try:
        dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("Semente ilegível: %s", e)
        return 0
    with db.transacao() as c:
        _inserir(c, "candidatos", dados.get("candidatos", []))
        _inserir(c, "pesquisas", dados.get("pesquisas", []))
        _inserir(c, "resultados", dados.get("resultados", []))
        for k, v in (dados.get("meta") or {}).items():
            db.set_meta(k, v, c)
    n = len(dados.get("pesquisas", []))
    log.info("Semente carregada: %d pesquisas publicadas.", n)
    return n


if __name__ == "__main__":
    import sys

    db.init_db()
    print(exportar() if "exportar" in sys.argv else importar_se_vazio())
