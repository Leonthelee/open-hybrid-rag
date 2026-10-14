import unittest
import os

class TestDockerHardening(unittest.TestCase):
    """
    Verificación estática y determinista de conformidad con CIS Docker Benchmark v1.6.0.
    100% libre de dependencias externas (Standard Library).
    """

    @classmethod
    def setUpClass(cls):
        cls.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.dockerfile_path = os.path.join(cls.base_dir, "Dockerfile")
        cls.compose_path = os.path.join(cls.base_dir, "docker-compose.yml")
        cls.dockerignore_path = os.path.join(cls.base_dir, ".dockerignore")

        with open(cls.dockerfile_path, "r", encoding="utf-8") as f:
            cls.dockerfile_content = f.read()

        with open(cls.compose_path, "r", encoding="utf-8") as f:
            cls.compose_content = f.read()

        if os.path.exists(cls.dockerignore_path):
            with open(cls.dockerignore_path, "r", encoding="utf-8") as f:
                cls.dockerignore_content = f.read()
        else:
            cls.dockerignore_content = ""

    def test_dockerfile_multi_stage_build(self):
        """CIS Benchmark: Verificar construcción multi-etapa para minimizar superficie de ataque."""
        self.assertIn("AS builder", self.dockerfile_content)
        self.assertIn("AS runtime", self.dockerfile_content)

    def test_dockerfile_non_root_user(self):
        """CIS 4.1: Asegurar que el contenedor no corre como usuario root."""
        self.assertIn("useradd", self.dockerfile_content)
        self.assertIn("USER appuser", self.dockerfile_content)
        self.assertIn("/sbin/nologin", self.dockerfile_content)

    def test_dockerfile_healthcheck_present(self):
        """CIS 4.6: Asegurar que la imagen Docker incluye instrucción de HEALTHCHECK."""
        self.assertIn("HEALTHCHECK", self.dockerfile_content)
        self.assertIn("/health", self.dockerfile_content)

    def test_compose_read_only_root_filesystem(self):
        """CIS 5.12: Asegurar que el sistema de archivos raíz está montado en sólo lectura."""
        self.assertIn("read_only: true", self.compose_content)

    def test_compose_cap_drop_all(self):
        """CIS 5.3: Asegurar que se restringen todas las capacidades del kernel de Linux."""
        self.assertIn("cap_drop:", self.compose_content)
        self.assertIn("- ALL", self.compose_content)

    def test_compose_no_new_privileges(self):
        """CIS 5.25: Asegurar la prohibición de escalamiento de privilegios."""
        self.assertIn("security_opt:", self.compose_content)
        self.assertIn("no-new-privileges:true", self.compose_content)

    def test_compose_resource_limits(self):
        """CIS 5.10: Asegurar que se configuran límites de CPU y memoria."""
        self.assertIn("limits:", self.compose_content)
        self.assertIn("cpus:", self.compose_content)
        self.assertIn("memory:", self.compose_content)

    def test_compose_localhost_only_binding(self):
        """CIS Network: Asegurar que los puertos sólo se exponen en 127.0.0.1 (Loopback)."""
        self.assertIn("127.0.0.1:8000:8000", self.compose_content)
        self.assertNotIn('"8000:8000"', self.compose_content)
        self.assertNotIn("'8000:8000'", self.compose_content)

    def test_dockerignore_covers_sensitive_files(self):
        """CIS Filesystem: Asegurar que .dockerignore ignora .git, .env y entornos virtuales."""
        self.assertTrue(os.path.exists(self.dockerignore_path))
        self.assertIn(".git", self.dockerignore_content)
        self.assertIn(".env", self.dockerignore_content)
        self.assertIn(".venv", self.dockerignore_content)

if __name__ == "__main__":
    unittest.main()
