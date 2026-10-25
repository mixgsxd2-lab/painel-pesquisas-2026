"""Orquestra uma rodada completa do pipeline (disparada por visitas, no máximo 1x por hora).

    python -m pipeline.run
"""
from __future__ import annotations

import logging
import logging.handlers
import threading
import time

import settings
from core import db

log = logging.getLogger("pipeline")
_trava = threading.Lock()


def configurar_log() -> None:
    raiz = logging.getLogger()
    if getattr(raiz, "_painel_configurado", False):
        return
    raiz.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    arq = logging.handlers.RotatingFileHandler(
        settings.DATA_DIR / "logs" / "pipeline.log", maxBytes=5_000_000, backupCount=10, encoding="utf-8"
    )
    arq.setFormatter(fmt)
    tela = logging.StreamHandler()
    tela.setFormatter(fmt)
    raiz.addHandler(arq)
    raiz.addHandler(tela)
    raiz._painel_configurado = True


def _etapa(nome: str, fn, resumo: dict) -> None:
    t0 = time.time()
    try:
        resumo[nome] = fn()
    except Exception as e:
        log.exception("Etapa %s falhou", nome)
        resumo[nome] = {"erro": str(e)[:300]}
    resumo[nome + "_s"] = round(time.time() - t0, 1)


def rodada() -> dict:
    """Uma rodada: candidatos → apuração → sitemap → imagens (pesquisas desativadas)."""
    if settings.DEMO:
        log.info("Modo DEMO: pipeline desativado.")
        return {"demo": True}
    if not _trava.acquire(blocking=False):
        log.info("Rodada anterior ainda em andamento; pulando.")
        return {"pulada": True}
    try:
        from pipeline import apuracao, coletar_candidatos, malha_ibge, og_images, sitemap

        db.init_db()
        resumo: dict = {"inicio": settings.agora().isoformat()}
        _etapa("malha", malha_ibge.atualizar, resumo)
        ultima_cand = db.get_meta("candidatos_atualizados_em")
        if not ultima_cand or settings.agora().isoformat()[:13] != ultima_cand[:13]:
            _etapa("candidatos", coletar_candidatos.coletar, resumo)
        _etapa("apuracao", apuracao.coletar, resumo)
        _etapa("sitemap", sitemap.gerar, resumo)
        _etapa("og_images", og_images.gerar_todas, resumo)
        from core import audiencia

        _etapa("limpeza", audiencia.limpar, resumo)
        resumo["fim"] = settings.agora().isoformat()
        db.set_meta("ultima_rodada", resumo)
        log.info("Rodada concluída: %s", resumo)
        return resumo
    finally:
        _trava.release()


def rodada_apuracao() -> dict:
    """Execução rápida (a cada 2 min) durante a apuração."""
    if settings.DEMO:
        return {"demo": True}
    from pipeline import apuracao

    if not apuracao.em_apuracao():
        return {"ativo": False}
    return apuracao.coletar()


if __name__ == "__main__":
    configurar_log()
    db.init_db()
    print(rodada())
