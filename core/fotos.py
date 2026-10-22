"""Fotos oficiais dos candidatos (divulgadas pelo TSE em resultados.tse.jus.br).

As fotos ficam em static/fotos/<cargo>-<uf>-<numero>.jpeg e vão junto no repositório,
então aparecem mesmo em hospedagem com disco temporário.
"""
from __future__ import annotations

import settings

PASTA = settings.STATIC_DIR / "fotos"


def nome_arquivo(cargo: str, uf: str, numero: str) -> str:
    return f"{cargo}-{uf.lower()}-{numero}.jpeg"


def url(cargo: str, uf: str, numero: str) -> str | None:
    nome = nome_arquivo(cargo, uf, numero)
    return f"/static/fotos/{nome}" if (PASTA / nome).exists() else None
