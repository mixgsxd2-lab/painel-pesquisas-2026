"""Busca na web por "instituto + número de registro".

Provedores (usa todos os que estiverem configurados, nesta ordem):
  1. Brave Search API      (BRAVE_API_KEY)          — recomendado, tem plano gratuito
  2. SerpAPI / Google      (SERPAPI_KEY)
  3. Google Custom Search  (GOOGLE_CSE_KEY + GOOGLE_CSE_CX)
  4. Bing Notícias (RSS)   (GRATUITO, sem chave — ligado por padrão; ótimo para pesquisas recentes)
  5. DuckDuckGo HTML       (sem chave; desligado por padrão — costuma bloquear servidores)
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs, unquote, urlparse

import requests

import settings
from pipeline import http

log = logging.getLogger("pipeline.busca")

_BLOQUEADOS = (
    "facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com", "youtube.com",
    "linkedin.com", "pinterest.", "kwai", "threads.net", "whatsapp.com", "t.me",
)


def _ok(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    host = p.netloc.lower()
    return not any(b in host for b in _BLOQUEADOS)


def _brave(q: str) -> list[dict]:
    r = http.sessao().get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": q, "count": 10, "country": "BR", "search_lang": "pt-br"},
        headers={"X-Subscription-Token": settings.BRAVE_API_KEY, "Accept": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
    return [
        {"url": i.get("url"), "titulo": i.get("title", "")}
        for i in (r.json().get("web", {}) or {}).get("results", [])
    ]


def _serpapi(q: str) -> list[dict]:
    r = http.sessao().get(
        "https://serpapi.com/search.json",
        params={"engine": "google", "q": q, "hl": "pt-br", "gl": "br", "num": 10, "api_key": settings.SERPAPI_KEY},
        timeout=30,
    )
    r.raise_for_status()
    return [{"url": i.get("link"), "titulo": i.get("title", "")} for i in r.json().get("organic_results", [])]


def _google_cse(q: str) -> list[dict]:
    r = http.sessao().get(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": settings.GOOGLE_CSE_KEY, "cx": settings.GOOGLE_CSE_CX, "q": q, "num": 10, "gl": "br", "lr": "lang_pt"},
        timeout=20,
    )
    r.raise_for_status()
    return [{"url": i.get("link"), "titulo": i.get("title", "")} for i in r.json().get("items", [])]


import threading

_trava_bing = threading.Lock()
_ultimo_bing = [0.0]


def _bing_noticias(q: str) -> list[dict]:
    """Feed RSS público do Bing Notícias. Os links vêm como apiclick.aspx?url=<endereço real>."""
    import time
    import xml.etree.ElementTree as ET

    with _trava_bing:  # no máximo ~1 consulta por segundo, mesmo com várias threads
        espera = _ultimo_bing[0] + 1.0 - time.time()
        if espera > 0:
            time.sleep(espera)
        _ultimo_bing[0] = time.time()
    r = http.sessao().get(
        "https://www.bing.com/news/search",
        params={"q": q, "format": "rss", "setlang": "pt-BR", "cc": "BR", "count": 30},
        timeout=20,
    )
    r.raise_for_status()
    out = []
    try:
        raiz = ET.fromstring(r.content)
    except ET.ParseError as e:
        raise requests.RequestException(f"RSS do Bing inválido: {e}")
    for item in raiz.iter("item"):
        link = (item.findtext("link") or "").strip()
        if "apiclick.aspx" in link:
            link = unquote(parse_qs(urlparse(link).query).get("url", [""])[0])
        out.append({"url": link, "titulo": (item.findtext("title") or "").strip()})
    return out


def _duckduckgo(q: str) -> list[dict]:
    from bs4 import BeautifulSoup

    r = http.sessao().post("https://html.duckduckgo.com/html/", data={"q": q, "kl": "br-pt"}, timeout=20)
    r.raise_for_status()
    if r.status_code == 202 or "result__a" not in r.text:
        # verificação anti-robô: não tentamos contorná-la
        raise requests.RequestException(
            "DuckDuckGo exigiu verificação anti-robô; configure BRAVE_API_KEY, SERPAPI_KEY ou GOOGLE_CSE_*"
        )
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a.result__a"):
        href = a.get("href", "")
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
        out.append({"url": href, "titulo": a.get_text(" ", strip=True)})
    return out


def provedores() -> list:
    p = []
    if settings.BRAVE_API_KEY:
        p.append(("brave", _brave))
    if settings.SERPAPI_KEY:
        p.append(("serpapi", _serpapi))
    if settings.GOOGLE_CSE_KEY and settings.GOOGLE_CSE_CX:
        p.append(("google_cse", _google_cse))
    if settings.BUSCA_BING_NOTICIAS:
        p.append(("bing_noticias", _bing_noticias))
    if settings.BUSCA_DUCKDUCKGO:
        p.append(("duckduckgo", _duckduckgo))
    return p


def buscar(consultas: list[str], limite: int) -> list[dict]:
    """Executa as consultas nos provedores disponíveis; devolve URLs únicas (ordem de relevância)."""
    vistos: set[str] = set()
    out: list[dict] = []
    for nome, fn in provedores():
        for q in consultas:
            try:
                res = fn(q)
            except (requests.RequestException, ValueError) as e:
                log.info("Busca %s falhou (%s): %s", nome, q, e)
                continue
            for item in res:
                u = (item.get("url") or "").split("#")[0]
                if u and _ok(u) and u not in vistos:
                    vistos.add(u)
                    out.append({"url": u, "titulo": item.get("titulo", ""), "provedor": nome})
        if len(out) >= limite:
            break  # provedor principal já trouxe o suficiente
    return out
