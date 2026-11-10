"""Los archivos que programan a los bots (.github/workflows) tienen que ser YAML válido: si uno está mal escrito,
GitHub deja de correrlo sin avisar (pasó con el barrido de redes). También revisa los horarios y que los
programas que nombran existan."""
import glob
import os
import re
import unittest

try:
    import yaml
except ImportError:                      # en la máquina de alguien sin PyYAML se saltea; en GitHub se instala siempre
    yaml = None

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ARCHIVOS = sorted(glob.glob(os.path.join(RAIZ, ".github", "workflows", "*.yml")))
CAMPO = re.compile(r"^(\*|\d+(-\d+)?)(/\d+)?(,(\*|\d+(-\d+)?)(/\d+)?)*$")


@unittest.skipIf(yaml is None, "falta PyYAML")
class Workflows(unittest.TestCase):
    def cargar(self, ruta):
        with open(ruta, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_hay_workflows(self):
        self.assertGreater(len(ARCHIVOS), 10)

    def test_todos_son_yaml_valido_con_disparador_y_trabajos(self):
        for ruta in ARCHIVOS:
            with self.subTest(os.path.basename(ruta)):
                d = self.cargar(ruta)
                self.assertIsInstance(d, dict)
                on = d.get("on", d.get(True))          # YAML lee "on" como verdadero
                self.assertTrue(on, "sin disparador (on:)")
                self.assertTrue(d.get("jobs"), "sin trabajos (jobs:)")
                for nombre, job in d["jobs"].items():
                    self.assertTrue(job.get("steps") or job.get("uses"), f"{nombre}: sin pasos")
                    for paso in job.get("steps") or []:
                        self.assertTrue(paso.get("run") or paso.get("uses"), f"{nombre}: paso vacío")

    def test_horarios_bien_escritos(self):
        for ruta in ARCHIVOS:
            d = self.cargar(ruta)
            on = d.get("on", d.get(True))
            for s in (on.get("schedule") or []) if isinstance(on, dict) else []:
                with self.subTest(os.path.basename(ruta)):
                    campos = str(s.get("cron", "")).split()
                    self.assertEqual(len(campos), 5, f"cron con {len(campos)} campos")
                    for c in campos:
                        self.assertRegex(c, CAMPO)

    def test_los_programas_que_corren_existen(self):
        for ruta in ARCHIVOS:
            d = self.cargar(ruta)
            for job in d["jobs"].values():
                carpeta = (job.get("defaults") or {}).get("run", {}).get("working-directory", "")
                for paso in job.get("steps") or []:
                    wd = paso.get("working-directory", carpeta)
                    for prog in re.findall(r"python3? (?!-)([\w/.-]+\.py)", str(paso.get("run") or "")):
                        with self.subTest(f"{os.path.basename(ruta)}: {prog}"):
                            self.assertTrue(os.path.exists(os.path.join(RAIZ, wd, prog)), f"no existe {wd}/{prog}")


if __name__ == "__main__":
    unittest.main()
