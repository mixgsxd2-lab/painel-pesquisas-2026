"""Atualização disparada por visitas (sem agendador).

Quando alguém acessa uma página, verificamos se já passou o intervalo mínimo desde a última
rodada. Se passou, UMA rodada do pipeline começa em segundo plano — quem visitou não espera.

Seguro com muitas visitas ao mesmo tempo:
  * checagem barata em memória: no máximo 1 consulta ao banco a cada 15 s por processo;
  * "reserva" (lease) gravada no SQLite dentro de uma transação BEGIN IMMEDIATE: entre todas as
    threads e todos os processos, só um consegue iniciar a rodada;
  * a reserva tem validade; se o processo morrer no meio, ela expira e outra visita assume.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

import settings
from core import db

log = logging.getLogger("gatilho")

CHECAR_A_CADA_S = 15
_ultima_checagem = 0.0
_trava_local = threading.Lock()

TAREFAS = {
    # nome: (intervalo mínimo entre rodadas em s, validade máxima da reserva em s)
    "pipeline": (lambda: settings.INTERVALO_PIPELINE_MIN * 60, 45 * 60),
    "apuracao": (lambda: settings.INTERVALO_APURACAO_MIN * 60, 10 * 60),
}


def _ler(c: sqlite3.Connection, chave: str) -> float:
    r = c.execute("SELECT valor FROM meta WHERE chave = ?", (chave,)).fetchone()
    try:
        return float(r[0]) if r and r[0] else 0.0
    except ValueError:
        return 0.0


def _gravar(c: sqlite3.Connection, chave: str, valor: float) -> None:
    c.execute(
        "INSERT INTO meta(chave, valor) VALUES(?, ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
        (chave, repr(valor)),
    )


def reservar(nome: str) -> bool:
    """Tenta pegar a reserva da tarefa. True = este processo deve executá-la agora."""
    intervalo, validade = TAREFAS[nome][0](), TAREFAS[nome][1]
    agora = time.time()
    c = db.conectar()
    c.execute("PRAGMA busy_timeout = 200")  # a visita nunca espera mais que 0,2 s por isto
    c.isolation_level = None  # transação controlada manualmente
    try:
        c.execute("BEGIN IMMEDIATE")  # trava de escrita: só um escritor por vez no banco todo
        if _ler(c, f"reserva:{nome}") > agora or agora - _ler(c, f"inicio:{nome}") < intervalo:
            c.execute("ROLLBACK")
            return False
        _gravar(c, f"reserva:{nome}", agora + validade)
        _gravar(c, f"inicio:{nome}", agora)
        c.execute("COMMIT")
        return True
    except sqlite3.OperationalError:  # banco ocupado: outra visita está cuidando disso
        try:
            c.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        return False
    finally:
        c.close()


def liberar(nome: str) -> None:
    db.set_meta(f"reserva:{nome}", "0")


def _executar(nome: str, fn) -> None:
    try:
        fn()
    except Exception:
        log.exception("Tarefa %s falhou", nome)
    finally:
        liberar(nome)


def em_andamento(nome: str = "pipeline") -> bool:
    try:
        return float(db.get_meta(f"reserva:{nome}", "0") or 0) > time.time()
    except ValueError:
        return False


def ao_visitar() -> None:
    """Chamado a cada página visitada. Retorna imediatamente."""
    global _ultima_checagem
    if settings.DEMO or not settings.AUTO_ATUALIZAR:
        return
    agora = time.time()
    with _trava_local:
        if agora - _ultima_checagem < CHECAR_A_CADA_S:
            return
        _ultima_checagem = agora

    from pipeline.run import configurar_log, rodada, rodada_apuracao

    configurar_log()
    if reservar("pipeline"):
        log.info("Visita disparou uma rodada do pipeline.")
        threading.Thread(target=_executar, args=("pipeline", rodada), name="pipeline", daemon=True).start()
    if agora >= settings.INICIO_APURACAO.timestamp() and reservar("apuracao"):
        threading.Thread(target=_executar, args=("apuracao", rodada_apuracao), name="apuracao", daemon=True).start()
