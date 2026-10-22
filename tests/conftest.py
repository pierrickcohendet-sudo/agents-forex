"""Garde-fous de la suite de tests (pytest).

- Réseau BLOQUÉ par défaut : toute résolution DNS ou connexion vers autre chose que la machine locale lève
  une erreur immédiate (jamais d'attente d'un délai réseau, jamais d'appel réel à Twelve Data, FRED, RSS,
  Gemini, Notion ou à l'API GitHub). Un test qui a vraiment besoin du réseau porte le marqueur `reseau` ;
  il est exclu de la suite par défaut (pytest.ini) et se lance à part : `pytest -m reseau`.
- Délai de 60 s par test (pytest-timeout, pytest.ini) : un test bloqué échoue au lieu de geler la suite.
"""
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LOCAUX = {"localhost", "127.0.0.1", "::1", "", None}


class ReseauBloque(OSError):
    pass


def _hote(adresse):
    return adresse[0] if isinstance(adresse, tuple) and adresse else adresse


@pytest.fixture(autouse=True)
def _bloquer_reseau(request, monkeypatch):
    if request.node.get_closest_marker("reseau"):
        yield
        return
    origine_gai, origine_connect = socket.getaddrinfo, socket.socket.connect

    def getaddrinfo(host, *args, **kwargs):
        if host not in LOCAUX:
            raise ReseauBloque(f"réseau bloqué dans les tests : résolution de {host!r} (marqueur « reseau » si voulu)")
        return origine_gai(host, *args, **kwargs)

    def connect(self, adresse):
        if self.family in (socket.AF_INET, socket.AF_INET6) and _hote(adresse) not in LOCAUX:
            raise ReseauBloque(f"réseau bloqué dans les tests : connexion à {adresse!r}")
        return origine_connect(self, adresse)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", connect)
    yield
