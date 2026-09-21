"""Notifications d'échec : Slack (webhook) et/ou email SMTP, selon les
variables d'environnement présentes. Toujours loggé quoi qu'il arrive."""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText

import requests

log = logging.getLogger(__name__)


def notifier_echec(etape: str, erreur: str) -> None:
    message = f"[pipeline FX] Échec de l'étape « {etape} » : {erreur}"
    log.error(message)

    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if webhook:
        try:
            requests.post(webhook, json={"text": message}, timeout=15)
        except requests.RequestException as exc:
            log.error("Notification Slack impossible : %s", exc)

    hote = os.environ.get("SMTP_HOST")
    destinataire = os.environ.get("NOTIF_EMAIL_TO")
    if hote and destinataire:
        try:
            mail = MIMEText(message, "plain", "utf-8")
            mail["Subject"] = f"[pipeline FX] Échec : {etape}"
            mail["From"] = os.environ.get("SMTP_USER", "pipeline-fx")
            mail["To"] = destinataire
            with smtplib.SMTP(hote, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as smtp:
                smtp.starttls()
                utilisateur = os.environ.get("SMTP_USER")
                if utilisateur:
                    smtp.login(utilisateur, os.environ.get("SMTP_PASS", ""))
                smtp.send_message(mail)
        except (smtplib.SMTPException, OSError) as exc:
            log.error("Notification email impossible : %s", exc)
