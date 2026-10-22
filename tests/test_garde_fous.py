"""Le réseau est bloqué dans les tests (tests/conftest.py) : un appel réel échoue tout de suite, sans attente."""
import socket
import time

import pytest
import requests


def test_requete_http_externe_bloquee_immediatement():
    debut = time.perf_counter()
    with pytest.raises(requests.exceptions.ConnectionError):
        requests.get("https://api.github.com/repos/pierrickcohendet-sudo/agents-forex/actions/runs", timeout=30)
    assert time.perf_counter() - debut < 5


def test_resolution_dns_bloquee_mais_machine_locale_permise():
    with pytest.raises(OSError, match="réseau bloqué"):
        socket.getaddrinfo("api.twelvedata.com", 443)
    assert socket.getaddrinfo("127.0.0.1", 80)
