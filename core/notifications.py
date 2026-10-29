"""Notifications d'échec : Slack (webhook) et/ou email SMTP, selon les
variables d'environnement présentes. Toujours loggé quoi qu'il arrive."""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText

import requests

from core.secrets import masquer_secrets

log = logging.getLogger(__name__)


def notifier_echec(etape: str, erreur: str) -> None:
    # Masquage défensif ici (en plus de la source) : ce message part vers un
    # webhook Slack externe — dernier filet avant publication hors du dépôt.
    message = f"[pipeline FX] Échec de l'étape « {etape} » : {masquer_secrets(erreur)}"
    log.error(message)

    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if webhook:
        try:
            requests.post(webhook, json={"text": message}, timeout=15)
        except requests.RequestException as exc:
            log.error("Notification Slack impossible : %s", masquer_secrets(str(exc)))

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
            log.error("Notification email impossible : %s", masquer_secrets(str(exc)))


# ------------------------------------------------------------------ alertes de fin de run (lot Verrouillage)
ETIQUETTE = "alerte-pipeline"
API = "https://api.github.com"


def _envoyer_canaux(sujet: str, message: str) -> None:
    """Slack et e-mail, s'ils sont déjà configurés (aucune nouvelle clé)."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if webhook:
        try:
            requests.post(webhook, json={"text": f"[pipeline FX] {sujet}\n{message}"}, timeout=15)
        except requests.RequestException as exc:
            log.error("Notification Slack impossible : %s", masquer_secrets(str(exc)))
    hote, destinataire = os.environ.get("SMTP_HOST"), os.environ.get("NOTIF_EMAIL_TO")
    if hote and destinataire:
        try:
            mail = MIMEText(message, "plain", "utf-8")
            mail["Subject"], mail["From"], mail["To"] = f"[pipeline FX] {sujet}", os.environ.get("SMTP_USER", "pipeline-fx"), destinataire
            with smtplib.SMTP(hote, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as smtp:
                smtp.starttls()
                if os.environ.get("SMTP_USER"):
                    smtp.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
                smtp.send_message(mail)
        except (smtplib.SMTPException, OSError) as exc:
            log.error("Notification email impossible : %s", masquer_secrets(str(exc)))


def notifier_alertes(alertes: list[dict], change: bool, corps: str, session=requests) -> str:
    """Tient à jour UNE issue GitHub « alerte-pipeline » : ouverte, commentée si la liste change, fermée quand il n'y
    a plus d'alerte. Retourne ce qui a été fait (journal). Sans GITHUB_TOKEN (exécution locale) : journal seulement."""
    jeton, depot = os.environ.get("GITHUB_TOKEN", "").strip(), os.environ.get("GITHUB_REPOSITORY", "").strip()
    if alertes and change:
        log.warning("Alertes de fin de run : %s", " | ".join(a["texte"] for a in alertes))
        _envoyer_canaux(f"{len(alertes)} alerte(s)", corps)
    if not jeton or not depot:
        return "issue GitHub non gérée (GITHUB_TOKEN absent : exécution locale)"
    entetes = {"Authorization": f"Bearer {jeton}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    try:
        rep = session.get(f"{API}/repos/{depot}/issues", params={"state": "open", "labels": ETIQUETTE, "per_page": 5},
                          headers=entetes, timeout=30)
        rep.raise_for_status()
        ouvertes = [i for i in rep.json() if "pull_request" not in i]
        if alertes and not ouvertes:
            session.post(f"{API}/repos/{depot}/labels", headers=entetes, timeout=30,   # 422 si elle existe déjà : sans effet
                         json={"name": ETIQUETTE, "color": "D97706", "description": "Alerte automatique du pipeline FX"})
            session.post(f"{API}/repos/{depot}/issues", headers=entetes, timeout=30,
                         json={"title": f"Alerte pipeline FX : {len(alertes)} point(s) à vérifier", "body": corps,
                               "labels": [ETIQUETTE]}).raise_for_status()
            return "issue ouverte"
        if alertes and change:
            session.post(f"{API}/repos/{depot}/issues/{ouvertes[0]['number']}/comments", headers=entetes, timeout=30,
                         json={"body": corps}).raise_for_status()
            return f"issue #{ouvertes[0]['number']} commentée"
        if not alertes and ouvertes:
            n = ouvertes[0]["number"]
            session.post(f"{API}/repos/{depot}/issues/{n}/comments", headers=entetes, timeout=30,
                         json={"body": "Plus aucune alerte à la fin du dernier run : issue fermée automatiquement."}).raise_for_status()
            session.patch(f"{API}/repos/{depot}/issues/{n}", headers=entetes, timeout=30, json={"state": "closed"}).raise_for_status()
            return f"issue #{n} fermée"
        return "issue inchangée"
    except requests.RequestException as exc:
        log.error("Issue d'alerte non mise à jour : %s", masquer_secrets(str(exc)))
        return f"issue non mise à jour ({masquer_secrets(str(exc))[:100]})"
