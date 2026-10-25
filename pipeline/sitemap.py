"""Gera data/sitemap.xml a cada rodada do pipeline, com <lastmod> correto por página."""
from __future__ import annotations

from xml.sax.saxutils import escape

import settings
from core import db
from core.textutil import parse_datahora
from core.ufs import UFS

ARQUIVO = settings.DATA_DIR / ("sitemap-demo.xml" if settings.DEMO else "sitemap.xml")
LANCAMENTO = "2026-10-21T00:00:00-03:00"


def _iso(v: str | None) -> str:
    dt = parse_datahora(v) if v else None
    return dt.isoformat(timespec="seconds") if dt else LANCAMENTO


def gerar() -> int:
    glob = db.get_meta("dados_atualizados_em") or db.get_meta("tse_coletado_em")
    urls: list[tuple[str, str, str]] = [
        ("/", _iso(glob), "1.0"),
        ("/presidente", _iso(db.get_meta("atualizado:presidente:BR") or glob), "0.9"),
        ("/governador", _iso(glob), "0.9"),
        ("/contato", LANCAMENTO, "0.3"),
        ("/anuncie", LANCAMENTO, "0.3"),
    ]
    for uf in UFS:
        for cargo in ("presidente", "governador"):
            urls.append((f"/{cargo}/{uf.lower()}", _iso(db.get_meta(f"atualizado:{cargo}:{uf}")), "0.8"))

    linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for caminho, lastmod, prio in urls:
        linhas.append(
            f"  <url><loc>{escape(settings.SITE_URL + caminho)}</loc><lastmod>{lastmod}</lastmod>"
            f"<priority>{prio}</priority></url>"
        )
    linhas.append("</urlset>")
    tmp = ARQUIVO.with_suffix(".tmp")
    tmp.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    tmp.replace(ARQUIVO)
    return len(urls)
