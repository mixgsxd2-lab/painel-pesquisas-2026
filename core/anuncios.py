"""Anúncios gerenciados por config/anuncios.json, com regras aplicadas automaticamente:

* rótulo "Publicidade" sempre visível (nos templates);
* PROIBIDO conteúdo político/eleitoral (candidatos, partidos, coligações, campanhas, governos);
* a imagem não pode usar as cores dos candidatos (vermelho/azul da paleta);
* o anúncio só aparece dentro do período (início/fim).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from functools import lru_cache

import settings
from core import candidatos as cand_mod
from core import db
from core.textutil import normalizar

log = logging.getLogger("anuncios")
_handler = logging.FileHandler(settings.DATA_DIR / "logs" / "anuncios.log", encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_handler)

ESPACOS = {
    "banner_pesquisas": "Banner no topo da página Pesquisas",
    "gaveta_mapa": "Card “Patrocinado” na gaveta do mapa",
    "selo_apuracao": "Selo “Apuração apresentada por” no modo Apuração",
}

_TERMOS_POLITICOS = [
    r"candidat", r"partido", r"coligac", r"federacao partidaria", r"eleic", r"eleitor", r"\bvote\b", r"\bvotem?\b",
    r"campanha", r"governo", r"prefeitura", r"governador", r"presidente", r"senador", r"deputad", r"vereador",
    r"\bpt\b", r"\bpl\b", r"\bpsdb\b", r"\bmdb\b", r"\bpsol\b", r"\bpsd\b", r"\bpp\b", r"\bpsb\b", r"\bpdt\b",
    r"uniao brasil", r"republicanos", r"partido novo", r"\bnumero \d{2}\b", r"\btse\b", r"\burnas?\b",
]


def _politico(texto: str) -> str | None:
    t = normalizar(texto)
    for termo in _TERMOS_POLITICOS:
        if re.search(termo, t):
            return termo.replace(r"\b", "")
    nomes = {normalizar(r["nome_urna"]) for r in db.q("SELECT DISTINCT nome_urna FROM candidatos")}
    for n in nomes:
        if n and re.search(rf"\b{re.escape(n)}\b", t):
            return n
    return None


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


@lru_cache(maxsize=64)
def _cores_proibidas_na_imagem(caminho: str, mtime: float, paleta: tuple[str, ...]) -> str | None:
    """Recusa a imagem se > 6% dos pixels estiverem perto das cores dos candidatos
    (ou forem vermelhos/azuis saturados)."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        return None
    try:
        img = Image.open(caminho).convert("RGB")
    except OSError:
        return "imagem ilegível"
    img.thumbnail((120, 120))
    px = list(img.getdata())
    alvos = [_hex_rgb(c) for c in paleta]
    perto = 0
    for r, g, b in px:
        if any((r - ar) ** 2 + (g - ag) ** 2 + (b - ab) ** 2 < 70 ** 2 for ar, ag, ab in alvos):
            perto += 1
            continue
        mx, mn = max(r, g, b), min(r, g, b)
        sat = (mx - mn) / mx if mx else 0
        if sat > 0.55 and mx > 110 and (r == mx and g < 0.45 * r and b < 0.55 * r or b == mx and r < 0.5 * b):
            perto += 1
    frac = perto / max(1, len(px))
    return f"{frac:.0%} da imagem em vermelho/azul" if frac > 0.06 else None


@lru_cache(maxsize=1)
def _ler(mtime: float) -> list[dict]:
    with open(settings.CONFIG_DIR / "anuncios.json", encoding="utf-8") as f:
        return json.load(f).get("anuncios", [])


def _todos() -> list[dict]:
    p = settings.CONFIG_DIR / "anuncios.json"
    try:
        return _ler(p.stat().st_mtime)
    except (OSError, ValueError) as e:
        log.error("anuncios.json inválido: %s", e)
        return []


def verificar(a: dict) -> str | None:
    """Motivo da recusa, ou None se o anúncio está apto."""
    if a.get("espaco") not in ESPACOS:
        return f"espaço desconhecido: {a.get('espaco')}"
    for campo in ("marca", "imagem", "link"):
        if not a.get(campo):
            return f"campo obrigatório ausente: {campo}"
    if not str(a["link"]).startswith(("https://", "http://")):
        return "link inválido"
    termo = _politico(" ".join(str(a.get(k, "")) for k in ("marca", "texto_alternativo", "link", "imagem")))
    if termo:
        return f"conteúdo político/eleitoral detectado ({termo})"
    caminho = settings.STATIC_DIR / a["imagem"]
    if not caminho.exists():
        return f"imagem não encontrada: static/{a['imagem']}"
    cor = _cores_proibidas_na_imagem(str(caminho), caminho.stat().st_mtime, tuple(cand_mod.paleta()))
    if cor:
        return f"imagem usa cores dos candidatos ({cor})"
    return None


_recusas_logadas: set[str] = set()


def ativo(espaco: str) -> dict | None:
    hoje = settings.agora().date()
    for a in _todos():
        if not a.get("ativo") or a.get("espaco") != espaco:
            continue
        try:
            ini = date.fromisoformat(a.get("inicio") or "2000-01-01")
            fim = date.fromisoformat(a.get("fim") or "2100-01-01")
        except ValueError:
            continue
        if not (ini <= hoje <= fim):
            continue
        motivo = verificar(a)
        if motivo:
            chave = f"{a.get('marca')}|{espaco}|{motivo}"
            if chave not in _recusas_logadas:
                _recusas_logadas.add(chave)
                log.warning("Anúncio recusado (%s / %s): %s", a.get("marca"), espaco, motivo)
            continue
        return a
    return None
