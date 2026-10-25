"""Gera as imagens de pré-visualização (Open Graph / Twitter Card): PNG 1200x630 com o mapa
do estado/cargo e o título.

Por regra do site, as imagens NÃO trazem percentuais nem cores de candidatos — um número
de pesquisa nunca circula sem os dados obrigatórios do registro.

    python -m pipeline.og_images
"""
from __future__ import annotations

import logging
import re

import settings
from core import geo
from core.ufs import UFS, nome_uf
from pipeline import http

log = logging.getLogger("pipeline.og")

PASTA = settings.DATA_DIR / "og"
FONTES = settings.DATA_DIR / "fonts"
L, A = 1200, 630
VERSAO = "apuracao-1"  # mude para forçar a regeração de todas as imagens


def _baixar_fonte(peso: int) -> str | None:
    destino = FONTES / f"Inter-{peso}.ttf"
    if destino.exists():
        return str(destino)
    try:
        css = http.sessao().get(
            f"https://fonts.googleapis.com/css2?family=Inter:wght@{peso}",
            headers={"User-Agent": "Mozilla/4.0"},  # pede TTF em vez de WOFF2
            timeout=20,
        ).text
        m = re.search(r"url\((https://[^)]+\.ttf)\)", css)
        if not m:
            return None
        destino.write_bytes(http.get(m.group(1), timeout=30).content)
        return str(destino)
    except Exception as e:
        log.info("Fonte Inter indisponível (%s); usando a padrão.", e)
        return None


def _fonte(peso: int, tamanho: int):
    from PIL import ImageFont

    caminho = _baixar_fonte(peso)
    if caminho:
        try:
            return ImageFont.truetype(caminho, tamanho)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=tamanho)
    except TypeError:  # Pillow antigo
        return ImageFont.load_default()


def _fundo():
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("RGB", (L, A), (7, 8, 13))
    camada = Image.new("RGB", (L, A), (7, 8, 13))
    d = ImageDraw.Draw(camada)
    d.ellipse((-200, -260, 700, 520), fill=(28, 36, 92))
    d.ellipse((600, 180, 1500, 900), fill=(64, 36, 110))
    d.ellipse((300, 380, 900, 900), fill=(30, 32, 44))
    camada = camada.filter(ImageFilter.GaussianBlur(140))
    return Image.blend(img, camada, 0.85)


def _desenhar_mapa(img, destaque: str | None):
    from PIL import ImageDraw

    caixa_l, caixa_a = 520, 520
    est = geo.projetado(caixa_l, caixa_a, 6)
    if not est:
        return
    ox, oy = L - caixa_l - 50, (A - caixa_a) // 2
    d = ImageDraw.Draw(img, "RGBA")
    for uf, e in est.items():
        sel = destaque in (uf, "BR")
        cor = (167, 139, 250, 235) if sel else (255, 255, 255, 34)
        borda = (230, 222, 255, 255) if sel else (255, 255, 255, 90)
        for poly in e["poligonos"]:
            anel = [(x + ox, y + oy) for x, y in poly[0]]
            if len(anel) >= 3:
                d.polygon(anel, fill=cor, outline=borda)


def _quebrar(texto: str, fonte, largura: int, draw) -> list[str]:
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = (atual + " " + palavra).strip()
        if draw.textlength(teste, font=fonte) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def gerar(nome: str, titulo: str, subtitulo: str, destaque: str | None) -> None:
    from PIL import ImageDraw

    img = _fundo()
    _desenhar_mapa(img, destaque)
    d = ImageDraw.Draw(img, "RGBA")
    f_marca = _fonte(600, 26)
    f_tit = _fonte(800, 60)
    f_sub = _fonte(500, 28)
    d.rounded_rectangle((60, 60, 92, 92), radius=9, fill=(167, 139, 250, 255))
    d.text((106, 60), settings.SITE_NOME, font=f_marca, fill=(245, 247, 250))
    y = 150
    for linha in _quebrar(titulo, f_tit, 600, d)[:4]:
        d.text((60, y), linha, font=f_tit, fill=(245, 247, 250))
        y += 72
    y += 16
    for linha in _quebrar(subtitulo, f_sub, 600, d)[:3]:
        d.text((60, y), linha, font=f_sub, fill=(255, 255, 255, 160))
        y += 38
    d.text((60, A - 70), "Resultados oficiais do TSE · 2º turno · 25/10/2026",
           font=_fonte(500, 22), fill=(255, 255, 255, 140))
    img.save(PASTA / f"{nome}.png", "PNG", optimize=True)


def alvos() -> list[tuple[str, str, str, str | None]]:
    out = [
        ("home", "Apuração do 2º turno 2026", "Presidente e governadores — resultados oficiais do TSE", "BR"),
        ("presidente", "Apuração para presidente — 2º turno 2026", "Resultados oficiais do TSE", "BR"),
        ("governador", "Apuração para governador — 2º turno 2026", "Estados com 2º turno, resultados oficiais do TSE", None),
        ("geral", settings.SITE_NOME, "Apuração do 2º turno com resultados oficiais do TSE", None),
    ]
    for uf in UFS:
        nome = nome_uf(uf)
        out.append((f"presidente-{uf.lower()}", f"Apuração para presidente em {nome} ({uf})",
                    "2º turno 2026 — resultados oficiais do TSE", uf))
        out.append((f"governador-{uf.lower()}", f"Apuração para governador — {nome} ({uf})",
                    "2º turno 2026 — resultados oficiais do TSE", uf))
    return out


def gerar_todas(forcar: bool = False) -> int:
    if not geo.disponivel():
        return 0
    marca = PASTA / f".versao-{VERSAO}"
    if marca.exists() and not forcar:
        faltando = [a for a in alvos() if not (PASTA / f"{a[0]}.png").exists()]
    else:
        faltando = alvos()
    for nome, tit, sub, dest in faltando:
        try:
            gerar(nome, tit, sub, dest)
        except Exception:
            log.exception("Falha ao gerar imagem %s", nome)
    marca.touch()
    if faltando:
        log.info("Imagens de compartilhamento geradas: %d", len(faltando))
    return len(faltando)


if __name__ == "__main__":
    from pipeline.run import configurar_log

    configurar_log()
    print(gerar_todas(forcar=True))
