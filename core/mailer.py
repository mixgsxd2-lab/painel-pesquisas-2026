"""Envio de e-mail ao dono do site (SMTP), em segundo plano para não travar a página."""
from __future__ import annotations

import logging
import smtplib
import threading
from email.message import EmailMessage

import settings

log = logging.getLogger("mailer")


def _enviar(assunto: str, corpo: str, responder_para: str | None) -> None:
    if not settings.SMTP_HOST:
        log.warning("SMTP não configurado; e-mail não enviado: %s", assunto)
        return
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = settings.SMTP_FROM
    msg["To"] = settings.EMAIL_DONO
    if responder_para:
        msg["Reply-To"] = responder_para
    msg.set_content(corpo)
    try:
        if settings.SMTP_PORT == 465:
            srv = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
        else:
            srv = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
            if settings.SMTP_TLS:
                srv.starttls()
        with srv:
            if settings.SMTP_USER:
                srv.login(settings.SMTP_USER, settings.SMTP_PASS)
            srv.send_message(msg)
    except Exception as e:
        log.error("Falha ao enviar e-mail (%s): %s", assunto, e)


def enviar_para_dono(assunto: str, corpo: str, responder_para: str | None = None) -> None:
    threading.Thread(target=_enviar, args=(assunto, corpo, responder_para), daemon=True).start()
