"""Journal V2 (lot V6) : la logique du navigateur (docs/site/journal_logique.js) est testée par Node
(tests/journal_v2.test.mjs) : migration des notes V1, bilan mensuel, « peut toucher mon scénario », .ics."""
import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent : tests du Journal V2 non lancés")
def test_journal_v2_node():
    r = subprocess.run(["node", str(RACINE / "tests" / "journal_v2.test.mjs")], capture_output=True, text=True,
                       encoding="utf-8", timeout=50)
    assert r.returncode == 0, r.stderr or r.stdout
    assert "tous les tests passent" in r.stdout
