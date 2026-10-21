"""Utilidades de texto, números e formatação pt-BR."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from urllib.parse import urlparse

from settings import TZ


def sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def normalizar(s: str) -> str:
    """minúsculas, sem acento, espaços colapsados."""
    s = sem_acento(s).lower()
    s = s.replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def num_br(s: str | None) -> float | None:
    """'2,53' -> 2.53 ; '1.200' -> 1200 ; '' -> None"""
    if s is None:
        return None
    s = str(s).strip()
    if not s or s.upper() == "#NULO#":
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# ---- Registro TSE ------------------------------------------------------------
_RE_PROTOCOLO = re.compile(r"^([A-Z]{2})(\d{5})(\d{4})$")


def registro_fmt(protocolo: str) -> str:
    """'BR034362026' -> 'BR-03436/2026'."""
    m = _RE_PROTOCOLO.match((protocolo or "").upper())
    if not m:
        return protocolo
    return f"{m.group(1)}-{m.group(2)}/{m.group(3)}"


def registro_slug(protocolo: str) -> str:
    """'BR034362026' -> 'BR-03436-2026' (seguro para URL)."""
    return registro_fmt(protocolo).replace("/", "-")


def protocolo_de_slug(slug: str) -> str | None:
    s = re.sub(r"[^A-Za-z0-9]", "", slug or "").upper()
    return s if _RE_PROTOCOLO.match(s) else None


def regex_registro(protocolo: str) -> re.Pattern | None:
    """Regex tolerante para achar o registro numa página: BR-03436/2026, BR 03436/2026,
    BR034362026, BR-3436/2026, nº 03436/2026 (com BR por perto)."""
    m = _RE_PROTOCOLO.match((protocolo or "").upper())
    if not m:
        return None
    uf, num, ano = m.groups()
    num_sem_zero = num.lstrip("0") or "0"
    return re.compile(
        rf"{uf}[\s\-‐-―_.:/]*(?:n[º°o.]*\s*)?0*{num_sem_zero}[\s\-‐-―_.:/]*{ano}",
        re.IGNORECASE,
    )


# ---- Datas ---------------------------------------------------------------------
def parse_data(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_datahora(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip()[:19], fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=TZ)
    except ValueError:
        return None


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def data_br(d) -> str:
    if isinstance(d, str):
        d = parse_data(d)
    if not d:
        return "—"
    return d.strftime("%d/%m/%Y")


def data_curta(d) -> str:
    if isinstance(d, str):
        d = parse_data(d)
    if not d:
        return "—"
    return d.strftime("%d/%m")


def datahora_br(dt) -> str:
    if isinstance(dt, str):
        dt = parse_datahora(dt)
    if not dt:
        return "—"
    dt = dt.astimezone(TZ)
    return f"{dt:%d/%m} às {dt:%H:%M}"


def pct(v, casas: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v:.{casas}f}".replace(".", ",") + "%"


_CONECTIVOS = {"de", "da", "do", "dos", "das", "e", "di", "du"}


def nome_proprio(s: str) -> str:
    """'CADU DE LULA' -> 'Cadu de Lula' ; 'DR. FURLAN' -> 'Dr. Furlan'."""
    out = []
    for i, p in enumerate((s or "").lower().split()):
        out.append(p if (i > 0 and p in _CONECTIVOS) else p[:1].upper() + p[1:])
    return " ".join(out)


def dec(v) -> str:
    """3.0 -> '3' ; 2.53 -> '2,53' ; 95.55 -> '95,55'."""
    if v is None:
        return "—"
    s = f"{float(v):.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def num(v, casas: int = 0) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def dominio(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


_SUFIXOS_2 = {
    "com.br", "org.br", "gov.br", "jus.br", "net.br", "edu.br", "leg.br", "mp.br",
    "art.br", "blog.br", "inf.br", "jor.br", "tv.br", "co.uk", "com.ar", "com.pt",
}


def dominio_raiz(url_ou_host: str) -> str:
    """Domínio registrável aproximado: g1.globo.com -> globo.com ; x.uol.com.br -> uol.com.br."""
    host = dominio(url_ou_host) if "/" in url_ou_host else url_ou_host.lower()
    partes = host.split(".")
    if len(partes) >= 3 and ".".join(partes[-2:]) in _SUFIXOS_2:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:])


def nome_instituto(fantasia: str, razao: str) -> str:
    f = (fantasia or "").strip()
    if f and f.upper() != "#NULO#":
        nome = f
    else:
        nome = razao or ""
        nome = re.sub(
            r"\b(LTDA\.?|EIRELI|S/?A|S\.A\.|ME|EPP|SOCIEDADE SIMPLES|SS)\b\.?", "", nome, flags=re.I
        )
        nome = re.sub(r"\s+-\s*$", "", nome).strip(" .,-")
    # Capitalização amigável, preservando siglas curtas
    if nome.isupper():
        palavras = []
        for p in nome.split():
            if len(p) <= 3 and p not in {"DE", "DA", "DO", "DOS", "DAS", "E"}:
                palavras.append(p)
            elif p in {"DE", "DA", "DO", "DOS", "DAS", "E"}:
                palavras.append(p.lower())
            else:
                palavras.append(p.capitalize())
        nome = " ".join(palavras)
    return nome.strip()


def chave_instituto(cnpj: str, nome: str) -> str:
    """Identificador estável do instituto (raiz do CNPJ, senão nome normalizado)."""
    c = re.sub(r"\D", "", cnpj or "")
    if len(c) >= 8:
        return c[:8]
    return normalizar(nome)
