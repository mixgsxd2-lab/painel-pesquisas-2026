"""Baixa a malha das UFs (GeoJSON) da API de malhas do IBGE e anota a sigla de cada estado.

    python -m pipeline.malha_ibge
"""
from __future__ import annotations

import json
import logging
import time

import settings
from core.ufs import IBGE_PARA_UF, nome_uf
from pipeline import http

log = logging.getLogger("pipeline.malha")

ARQUIVO = settings.DATA_DIR / "geo" / "br_uf.json"


def atualizar(forcar: bool = False) -> bool:
    if ARQUIVO.exists() and not forcar and time.time() - ARQUIVO.stat().st_mtime < 7 * 86400:
        return False
    try:
        gj = http.get(settings.IBGE_MALHA_URL, timeout=60).json()
    except Exception as e:
        log.warning("Malha do IBGE indisponível: %s", e)
        return False
    feats = []
    for f in gj.get("features", []):
        cod = str(f.get("properties", {}).get("codarea", ""))
        uf = IBGE_PARA_UF.get(cod)
        if not uf:
            continue
        geom = f["geometry"]
        # arredonda coordenadas (4 casas ≈ 11 m) para um arquivo menor
        def arred(c):
            return [arred(x) for x in c] if isinstance(c[0], list) else [round(c[0], 4), round(c[1], 4)]
        feats.append({
            "type": "Feature",
            "properties": {"uf": uf, "nome": nome_uf(uf), "codarea": cod},
            "geometry": {"type": geom["type"], "coordinates": arred(geom["coordinates"])},
        })
    if len(feats) != 27:
        log.warning("Malha do IBGE incompleta (%d UFs); mantendo a anterior.", len(feats))
        return False
    tmp = ARQUIVO.with_suffix(".tmp")
    tmp.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")), encoding="utf-8")
    tmp.replace(ARQUIVO)
    log.info("Malha do IBGE atualizada (%d UFs).", len(feats))
    return True


if __name__ == "__main__":
    from pipeline.run import configurar_log

    configurar_log()
    print(atualizar(forcar=True))
