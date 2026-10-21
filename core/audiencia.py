"""Audiência ao vivo (visitas hoje, visitas totais, pico simultâneo) sem guardar IP:
o visitante é identificado por um hash diário salgado de IP + navegador."""
from __future__ import annotations

import hashlib
import re
import time

import settings
from core import db

_BOTS = re.compile(r"bot|crawl|spider|slurp|preview|facebookexternalhit|whatsapp|curl|wget|python|monitor|lighthouse", re.I)


def eh_robo(user_agent: str) -> bool:
    return not user_agent or bool(_BOTS.search(user_agent))


def _hash(ip: str, ua: str, dia: str) -> str:
    return hashlib.sha256(f"{settings.SECRET_KEY}|{dia}|{ip}|{ua}".encode()).hexdigest()[:20]


def registrar(ip: str, ua: str) -> None:
    if eh_robo(ua):
        return
    dia = settings.agora().date().isoformat()
    h = _hash(ip, ua, dia)
    c = db.conn()
    novo = c.execute("INSERT OR IGNORE INTO audiencia_vistos(dia, hash) VALUES(?, ?)", (dia, h)).rowcount
    c.execute(
        "INSERT INTO audiencia_dia(dia, visitantes, paginas) VALUES(?, ?, 1) "
        "ON CONFLICT(dia) DO UPDATE SET visitantes = visitantes + ?, paginas = paginas + 1",
        (dia, novo, novo),
    )
    c.commit()


def presenca(sid: str) -> None:
    sid = re.sub(r"[^a-zA-Z0-9]", "", sid or "")[:40]
    if not sid:
        return
    agora = time.time()
    c = db.conn()
    c.execute(
        "INSERT INTO presenca(sid, ultimo) VALUES(?, ?) ON CONFLICT(sid) DO UPDATE SET ultimo = excluded.ultimo",
        (sid, agora),
    )
    c.execute("DELETE FROM presenca WHERE ultimo < ?", (agora - 600,))
    online = c.execute("SELECT COUNT(*) FROM presenca WHERE ultimo > ?", (agora - 75,)).fetchone()[0]
    pico = int(db.get_meta("pico_simultaneo", "0") or 0)
    if online > pico:
        db.set_meta("pico_simultaneo", str(online), c)
        db.set_meta("pico_simultaneo_em", settings.agora().isoformat(), c)
    c.commit()


def numeros() -> dict:
    dia = settings.agora().date().isoformat()
    hoje = db.q1("SELECT visitantes, paginas FROM audiencia_dia WHERE dia = ?", (dia,))
    total = db.q1("SELECT COALESCE(SUM(visitantes),0) v, COALESCE(SUM(paginas),0) p FROM audiencia_dia")
    online = db.q1("SELECT COUNT(*) n FROM presenca WHERE ultimo > ?", (time.time() - 75,))["n"]
    return {
        "hoje": hoje["visitantes"] if hoje else 0,
        "paginas_hoje": hoje["paginas"] if hoje else 0,
        "total": total["v"],
        "paginas_total": total["p"],
        "agora": online,
        "pico": int(db.get_meta("pico_simultaneo", "0") or 0),
    }


def limpar() -> None:
    corte = settings.agora().date().isoformat()
    db.executar("DELETE FROM audiencia_vistos WHERE dia < ?", (corte,))
