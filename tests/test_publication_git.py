"""Publication git du robot (core/publication_web.pousser_git) sur des dépôts git locaux jetables :
un commit distant arrive pendant le run, le push doit quand même réussir ; conflit sur les données :
la version du run est gardée ; échec définitif : exception et raison enregistrée (run rouge)."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from core import publication_web as pw  # noqa: E402

CONFIG = {"git_push": "toujours"}


def git(*args, cwd):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} : {r.stderr}")
    return r.stdout.strip()


def ecrire(chemin: Path, texte: str):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding="utf-8")


@unittest.skipIf(shutil.which("git") is None, "git absent")
class Publication(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.distant = self.tmp / "distant.git"
        git("init", "--bare", "-b", "master", str(self.distant), cwd=self.tmp)
        self.dev = self.tmp / "dev"
        git("clone", str(self.distant), str(self.dev), cwd=self.tmp)
        for d in (self.dev,):
            git("config", "user.name", "dev", cwd=d)
            git("config", "user.email", "dev@example.org", cwd=d)
        git("checkout", "-b", "master", cwd=self.dev)
        ecrire(self.dev / "code.py", "x = 1\n")
        ecrire(self.dev / "docs" / "data" / "latest.json", json.dumps({"date": "2026-10-14"}))
        git("add", ".", cwd=self.dev)
        git("commit", "-m", "init", cwd=self.dev)
        git("push", "origin", "master", cwd=self.dev)
        self.robot = self.tmp / "robot"
        git("clone", str(self.distant), str(self.robot), cwd=self.tmp)
        git("config", "user.name", "robot", cwd=self.robot)
        git("config", "user.email", "robot@example.org", cwd=self.robot)
        self.pause, pw.PAUSE_PUSH_S = pw.PAUSE_PUSH_S, 0
        pw.ECHEC_PUSH.clear()

    def tearDown(self):
        pw.PAUSE_PUSH_S = self.pause
        pw.ECHEC_PUSH.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def commit_dev(self, fichier, texte, message):
        ecrire(self.dev / fichier, texte)
        git("add", ".", cwd=self.dev)
        git("commit", "-m", message, cwd=self.dev)
        git("push", "origin", "master", cwd=self.dev)

    def test_commit_distant_pendant_le_run_push_reussi(self):
        ecrire(self.robot / "docs" / "data" / "latest.json", json.dumps({"date": "2026-10-15"}))
        self.commit_dev("code.py", "x = 2\n", "code poussé pendant le run")       # le push du robot n'est plus fast-forward
        self.assertTrue(pw.pousser_git(CONFIG, self.robot, "rapport quotidien"))
        git("pull", "origin", "master", cwd=self.dev)
        self.assertEqual(json.loads((self.dev / "docs" / "data" / "latest.json").read_text(encoding="utf-8"))["date"], "2026-10-15")
        self.assertEqual((self.dev / "code.py").read_text(encoding="utf-8"), "x = 2\n")   # le code distant est conservé
        self.assertEqual(pw.ECHEC_PUSH, [])

    def test_conflit_sur_les_donnees_notre_version_gardee(self):
        ecrire(self.robot / "docs" / "data" / "latest.json", json.dumps({"date": "2026-10-15", "source": "run"}))
        self.commit_dev("docs/data/latest.json", json.dumps({"date": "2026-10-15", "source": "local"}), "données régénérées en local")
        self.assertTrue(pw.pousser_git(CONFIG, self.robot, "rapport quotidien"))
        git("pull", "origin", "master", cwd=self.dev)
        self.assertEqual(json.loads((self.dev / "docs" / "data" / "latest.json").read_text(encoding="utf-8"))["source"], "run")

    def test_echec_definitif_exception_et_raison(self):
        ecrire(self.robot / "docs" / "data" / "latest.json", json.dumps({"date": "2026-10-16"}))
        git("remote", "set-url", "origin", str(self.tmp / "absent.git"), cwd=self.robot)
        with self.assertRaises(pw.PushEchoue):
            pw.pousser_git(CONFIG, self.robot, "rapport quotidien")
        self.assertEqual(len(pw.ECHEC_PUSH), 1)
        self.assertIn("git push impossible après 4 essai(s) sur 4", pw.ECHEC_PUSH[0])   # réseau : 4 essais

    def test_conflit_sur_config_jamais_ecrase(self):
        # le seul fichier hors données que le robot committe : config.yaml (identifiant Notion)
        self.commit_dev("config.yaml", "notion: ancien\n", "config initiale")
        git("pull", "origin", "master", cwd=self.robot)
        ecrire(self.robot / "config.yaml", "notion: robot\n")
        self.commit_dev("config.yaml", "notion: dev\n", "config modifiée pendant le run")
        with self.assertRaises(pw.ConflitCode):
            pw.pousser_git(CONFIG, self.robot, "rapport quotidien")
        self.assertIn("1 essai(s)", pw.ECHEC_PUSH[0])                                      # pas de nouvel essai
        git("pull", "origin", "master", cwd=self.dev)
        self.assertEqual((self.dev / "config.yaml").read_text(encoding="utf-8"), "notion: dev\n")

    def test_rien_a_committer(self):
        self.assertFalse(pw.pousser_git(CONFIG, self.robot, "rien"))
        self.assertEqual(pw.ECHEC_PUSH, [])


class SortieOrchestrateur(unittest.TestCase):
    def test_run_rouge_et_resume_si_le_push_a_echoue(self):
        import os
        import orchestrateur
        resume = Path(tempfile.mkdtemp()) / "resume.md"
        os.environ["GITHUB_STEP_SUMMARY"] = str(resume)
        try:
            pw.ECHEC_PUSH.clear()
            self.assertEqual(orchestrateur._sortie_avec_publication(0), 0)
            pw.ECHEC_PUSH.append("git push impossible après 4 essais vers master : rejeté")
            self.assertEqual(orchestrateur._sortie_avec_publication(0), 1)
            self.assertIn("n'a pas été poussé", resume.read_text(encoding="utf-8"))
        finally:
            pw.ECHEC_PUSH.clear()
            os.environ.pop("GITHUB_STEP_SUMMARY", None)


if __name__ == "__main__":
    unittest.main()
