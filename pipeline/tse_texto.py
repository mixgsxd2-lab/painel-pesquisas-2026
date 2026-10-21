"""Extração de margem de erro, nível de confiança e abrangência a partir de texto livre
(campos DS_PLANO_AMOSTRAL / DS_METODOLOGIA_PESQUISA do TSE ou páginas das fontes)."""
from __future__ import annotations

import re

from core.textutil import normalizar
from core.ufs import UFS

_RE_ANCORA_MARGEM = re.compile(r"margem\s+(?:maxima\s+)?(?:estimada\s+)?de\s+erro|erro\s+amostral|erro\s+maximo")
_RE_NUM_PONTOS = re.compile(
    r"(?:±|\+/-|\+-|\+ ou -)?\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:\([a-z ,]{1,25}\)\s*)?"
    r"(?:pontos?|p\.\s?p\.?|pp\b|%)"
)
_RE_CONF_1 = re.compile(r"confian[c]a[^0-9%]{0,60}?(\d{2}(?:[.,]\d{1,2})?)\s*%")
_RE_CONF_2 = re.compile(r"(\d{2}(?:[.,]\d{1,2})?)\s*%\s*(?:de\s+)?(?:nivel\s+de\s+)?confian")


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def margem_erro(texto: str) -> float | None:
    t = normalizar(texto)
    for anc in _RE_ANCORA_MARGEM.finditer(t):
        janela = t[anc.end(): anc.end() + 260]
        for m in _RE_NUM_PONTOS.finditer(janela):
            antes = janela[max(0, m.start() - 30): m.start()]
            if "confian" in antes or "signific" in antes or "ponder" in antes:
                continue
            previo = re.sub(r"confian[^%;]{0,60}%", "", janela[: m.start()])
            if "%" in previo or ";" in previo:
                break  # entrou numa lista de cotas (ex.: "16-24: 13%;") — não é a margem
            if re.match(r"\s*%?\s*;", janela[m.end():]):
                continue
            v = _f(m.group(1))
            if 0.3 <= v <= 15:
                return round(v, 2)
    return None


def nivel_confianca(texto: str) -> float | None:
    t = normalizar(texto)
    for rx in (_RE_CONF_1, _RE_CONF_2):
        for m in rx.finditer(t):
            v = _f(m.group(1))
            if 80 <= v < 100:
                return round(v, 2)
    return None


_RE_NACIONAL = re.compile(
    r"abrangencia nacional|amostra nacional|ambito nacional|nivel nacional|territorio nacional|"
    r"todo o (?:pais|brasil|territorio)|eleitorado brasileiro|eleitores brasileiros|"
    r"grandes regioes|cinco regioes|27 (?:unidades|ufs|estados)|todas as (?:unidades da federacao|ufs|27)|"
    r"eleitorado nacional|regioes do pais|em todas as regioes|eleitorado do pais|"
    r"eleitorado d[eo] brasil|eleitores d[eo] brasil|representativa do brasil|eleitores de todo"
)
_ANCORAS_UF = (
    r"(?:estado|eleitorado|eleitores|eleitoras|municipios|territorio|capital|interior|"
    r"residentes|domicilio eleitoral|votar|vota|votam|aptos a votar|populacao)"
)


def _rx_uf(sigla: str, nome: str) -> re.Pattern:
    n = re.escape(normalizar(nome))
    neg = r"(?! do sul)" if sigla == "MT" else ""
    return re.compile(rf"{_ANCORAS_UF}\s+(?:d[oae]s?|n[oae]s?|em)\s+(?:estado\s+d[oae]\s+)?{n}\b{neg}")


_RX_UFS = {s: _rx_uf(s, i["nome"]) for s, i in UFS.items()}


def pontuar_ufs(texto: str) -> dict[str, int]:
    t = normalizar(texto)
    pts: dict[str, int] = {}
    for sigla, rx in _RX_UFS.items():
        n = len(rx.findall(t))
        n += 2 * len(re.findall(rf"p0_uf={sigla.lower()}\b", t))
        if n:
            pts[sigla] = n
    return pts


def abrangencia(texto: str) -> str | None:
    """'BR' (nacional), sigla da UF, ou None se não for possível decidir com segurança."""
    t = normalizar(texto)
    nac = len(_RE_NACIONAL.findall(t))
    pts = pontuar_ufs(t)
    if pts:
        ordenado = sorted(pts.items(), key=lambda kv: -kv[1])
        melhor, s = ordenado[0]
        segundo = ordenado[1][1] if len(ordenado) > 1 else 0
        if s > segundo and nac == 0:
            return melhor
        if s >= 3 and s >= 2 * segundo and nac <= 1 and s > 2 * nac:
            return melhor
        return None if nac == 0 else (None if s >= nac else "BR")
    return "BR" if nac else None


def menciona_segundo_turno(texto: str) -> bool:
    t = normalizar(texto)
    return bool(re.search(r"\b(?:2\s?[oº°]|segundo)\s+turno\b", t))
