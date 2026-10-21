"""Agendador (APScheduler): roda o pipeline a cada hora e a apuração a cada 2 minutos.

Uma trava de arquivo garante UM único agendador mesmo com vários processos web.
Também pode ser executado sozinho:  python scheduler.py
"""
from __future__ import annotations

import atexit
import logging
import os
from datetime import datetime, timedelta

import settings

log = logging.getLogger("scheduler")
_sched = None
_arquivo_trava = None


def _pegar_trava() -> bool:
    global _arquivo_trava
    caminho = settings.DATA_DIR / "scheduler.lock"
    _arquivo_trava = open(caminho, "a+")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(_arquivo_trava.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(_arquivo_trava.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        _arquivo_trava.close()
        _arquivo_trava = None
        return False


def iniciar(bloquear: bool = False):
    global _sched
    if _sched is not None or settings.DEMO or not settings.RUN_SCHEDULER:
        return None
    if not _pegar_trava():
        log.info("Outro processo já executa o agendador.")
        return None

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.schedulers.blocking import BlockingScheduler

    from core import audiencia
    from pipeline.run import configurar_log, rodada, rodada_apuracao

    configurar_log()
    cls = BlockingScheduler if bloquear else BackgroundScheduler
    _sched = cls(timezone=settings.TZ, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 600})
    _sched.add_job(rodada, "interval", minutes=settings.INTERVALO_PIPELINE_MIN, id="pipeline",
                   next_run_time=datetime.now(settings.TZ) + timedelta(seconds=15))
    _sched.add_job(rodada_apuracao, "interval", minutes=settings.INTERVALO_APURACAO_MIN, id="apuracao")
    _sched.add_job(audiencia.limpar, "cron", hour=3, minute=5, id="limpeza")
    log.info("Agendador iniciado: pipeline a cada %d min; apuração a cada %d min.",
             settings.INTERVALO_PIPELINE_MIN, settings.INTERVALO_APURACAO_MIN)
    if not bloquear:
        atexit.register(lambda: _sched.shutdown(wait=False))
    _sched.start()
    return _sched


if __name__ == "__main__":
    from core import db

    db.init_db()
    iniciar(bloquear=True)
