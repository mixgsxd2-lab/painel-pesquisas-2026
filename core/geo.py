"""Malha dos estados: leitura do GeoJSON do IBGE, projeção e caminhos SVG (mapa 2D)."""
from __future__ import annotations

import json
import math
from functools import lru_cache

import settings

BAIXADO = settings.DATA_DIR / "geo" / "br_uf.json"
# cópia guardada no repositório: o mapa funciona mesmo com disco vazio (Render gratuito) ou IBGE fora do ar
RESERVA = settings.CONFIG_DIR / "br_uf.json"


def arquivo():
    return BAIXADO if BAIXADO.exists() else RESERVA


LAT0 = -15.0
COS0 = math.cos(math.radians(LAT0))


def disponivel() -> bool:
    return arquivo().exists()


@lru_cache(maxsize=2)
def _carregar(mtime: float, caminho: str = "") -> dict:
    return json.loads(arquivo().read_text(encoding="utf-8"))


def _chave() -> tuple[float, str]:
    a = arquivo()
    return a.stat().st_mtime, str(a)


def geojson() -> dict | None:
    if not disponivel():
        return None
    return _carregar(*_chave())


def _poligonos(geom: dict) -> list[list[list[list[float]]]]:
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def _proj(lon: float, lat: float) -> tuple[float, float]:
    return lon * COS0, lat


@lru_cache(maxsize=4)
def _projetado(mtime: float, caminho: str, largura: int, altura: int, margem: int):
    gj = _carregar(mtime, caminho)
    pts = [
        _proj(*c)
        for f in gj["features"]
        for poly in _poligonos(f["geometry"])
        for anel in poly
        for c in anel
    ]
    minx = min(p[0] for p in pts)
    maxx = max(p[0] for p in pts)
    miny = min(p[1] for p in pts)
    maxy = max(p[1] for p in pts)
    esc = min((largura - 2 * margem) / (maxx - minx), (altura - 2 * margem) / (maxy - miny))
    ox = (largura - (maxx - minx) * esc) / 2
    oy = (altura - (maxy - miny) * esc) / 2

    def tx(lon, lat):
        x, y = _proj(lon, lat)
        return ox + (x - minx) * esc, oy + (maxy - y) * esc

    estados = {}
    for f in gj["features"]:
        uf = f["properties"]["uf"]
        polys = []
        for poly in _poligonos(f["geometry"]):
            polys.append([[tx(lon, lat) for lon, lat in anel] for anel in poly])
        xs = [p[0] for poly in polys for p in poly[0]]
        ys = [p[1] for poly in polys for p in poly[0]]
        estados[uf] = {
            "poligonos": polys,
            "centro": ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2),
            "bbox": (min(xs), min(ys), max(xs), max(ys)),
        }
    return estados


def projetado(largura: int = 1000, altura: int = 1000, margem: int = 10) -> dict:
    if not disponivel():
        return {}
    return _projetado(*_chave(), largura, altura, margem)


def caminhos_svg(largura: int = 1000, altura: int = 1000) -> dict[str, str]:
    """{UF: 'M..Z M..Z'} para o mapa 2D (renderizado no servidor)."""
    out = {}
    for uf, e in projetado(largura, altura).items():
        partes = []
        for poly in e["poligonos"]:
            for anel in poly:
                if len(anel) < 3:
                    continue
                d = "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in anel) + "Z"
                partes.append(d)
        out[uf] = "".join(partes)
    return out
