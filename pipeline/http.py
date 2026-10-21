"""Cliente HTTP do robô: User-Agent identificado, robots.txt, cache e extração de texto."""
from __future__ import annotations

import io
import logging
import re
import time
import urllib.robotparser
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests

import settings
from core import db

log = logging.getLogger("pipeline.http")

MAX_BYTES = 8 * 1024 * 1024
CACHE_HORAS = 6

_sessao: requests.Session | None = None
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_ultimo_acesso: dict[str, float] = {}


def sessao() -> requests.Session:
    global _sessao
    if _sessao is None:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": settings.USER_AGENT,
                "Accept-Language": "pt-BR,pt;q=0.9",
            }
        )
        _sessao = s
    return _sessao


def get(url: str, timeout: float = 30, **kw) -> requests.Response:
    r = sessao().get(url, timeout=timeout, **kw)
    r.raise_for_status()
    return r


def baixar_arquivo(url: str, destino, timeout: float = 180) -> int:
    """Baixa um arquivo grande em streaming. Retorna o tamanho em bytes."""
    tam = 0
    with sessao().get(url, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for parte in r.iter_content(chunk_size=1 << 16):
                f.write(parte)
                tam += len(parte)
    return tam


def _robots_permite(url: str) -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = sessao().get(base + "/robots.txt", timeout=10)
            if r.status_code >= 400:
                _robots[base] = None  # sem robots.txt = permitido
            else:
                rp.parse(r.text.splitlines())
                _robots[base] = rp
        except requests.RequestException:
            _robots[base] = None
    rp = _robots[base]
    return True if rp is None else rp.can_fetch(settings.USER_AGENT, url)


def _respeitar_intervalo(url: str, segundos: float = 2.0) -> None:
    host = urlparse(url).netloc
    espera = _ultimo_acesso.get(host, 0) + segundos - time.time()
    if espera > 0:
        time.sleep(espera)
    _ultimo_acesso[host] = time.time()


def html_para_texto(html: str) -> tuple[str, str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    titulo = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form", "nav", "footer", "aside"]):
        tag.decompose()
    # tabelas: separa células para não grudar números
    for td in soup.find_all(["td", "th"]):
        td.append(" | ")
    for br in soup.find_all(["br", "p", "li", "tr", "h1", "h2", "h3", "h4", "div"]):
        br.append("\n")
    texto = soup.get_text(" ")
    texto = re.sub(r"[ \t ]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n", texto)
    return titulo, texto.strip()


def pdf_para_texto(conteudo: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        return ""
    try:
        leitor = PdfReader(io.BytesIO(conteudo))
        partes = []
        for i, pag in enumerate(leitor.pages):
            if i >= 40:
                break
            partes.append(pag.extract_text() or "")
        return "\n".join(partes)
    except Exception as e:  # PDFs malformados são comuns
        log.info("PDF ilegível: %s", e)
        return ""


def pagina_texto(url: str) -> tuple[str, str] | None:
    """(titulo, texto) da página, usando cache de 6h. None se não foi possível obter."""
    limite = (datetime.now() - timedelta(hours=CACHE_HORAS)).isoformat()
    cache = db.q1("SELECT * FROM paginas_cache WHERE url = ? AND baixada_em > ?", (url, limite))
    if cache:
        if cache["status"] != 200:
            return None
        return cache["titulo"] or "", cache["texto"] or ""

    titulo, texto, status = "", "", 0
    try:
        if not _robots_permite(url):
            log.info("robots.txt não permite: %s", url)
            status = 999
        else:
            _respeitar_intervalo(url)
            with sessao().get(url, timeout=25, stream=True, allow_redirects=True) as r:
                status = r.status_code
                if status == 200:
                    dados = b""
                    for parte in r.iter_content(1 << 16):
                        dados += parte
                        if len(dados) > MAX_BYTES:
                            break
                    tipo = (r.headers.get("Content-Type") or "").lower()
                    if "pdf" in tipo or url.lower().endswith(".pdf") or dados[:5] == b"%PDF-":
                        texto = pdf_para_texto(dados)
                        titulo = url.rsplit("/", 1)[-1]
                    else:
                        html = dados.decode(r.encoding or "utf-8", errors="replace")
                        titulo, texto = html_para_texto(html)
    except requests.RequestException as e:
        log.info("Falha ao baixar %s: %s", url, e)
        status = -1

    db.executar(
        "INSERT INTO paginas_cache(url, baixada_em, status, titulo, texto) VALUES(?,?,?,?,?) "
        "ON CONFLICT(url) DO UPDATE SET baixada_em=excluded.baixada_em, status=excluded.status, "
        "titulo=excluded.titulo, texto=excluded.texto",
        (url, datetime.now().isoformat(), status, titulo, texto[:400_000]),
    )
    if status != 200 or not texto:
        return None
    return titulo, texto


def limpar_cache_antigo(dias: int = 3) -> None:
    limite = (datetime.now() - timedelta(days=dias)).isoformat()
    db.executar("DELETE FROM paginas_cache WHERE baixada_em < ?", (limite,))
