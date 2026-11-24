"""Exercise the shipped snippet with an isolated Nginx and synthetic files only.

Run on Linux: python tests/nginx/check_private_media.py
Requires the nginx executable; never uses system configuration or reloads a service.
"""
import http.client
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest


class NginxMediaBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        nginx = shutil.which("nginx") or "/usr/sbin/nginx"
        if not Path(nginx).is_file():
            raise RuntimeError("Install nginx in the test environment; this check must not be skipped.")
        cls.scratch = tempfile.TemporaryDirectory(prefix="joatham-nginx-fixtures-")
        cls.addClassCleanup(cls.scratch.cleanup)
        root = Path(cls.scratch.name)
        root.chmod(0o755)
        cls.media = root / "media"
        for relative in ("payments/supporting_docs/proof.txt", "abonnements/preuves/proof.txt",
                         "messages/entreprise_1/conversation_1/fake.txt", "profiles/avatar.png",
                         "entreprises/logos/public.png", "future-private-module/proof.txt"):
            target = cls.media / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"SYNTHETIC FILE ONLY")
        (cls.media / "entreprises/logos/link.png").symlink_to(cls.media / "payments/supporting_docs/proof.txt")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]
        source = Path(__file__).resolve().parents[2] / "deploy/nginx/media-access.conf"
        snippet = source.read_text().replace("/home/joatham/apps/joatham_saas/media/", str(cls.media) + "/")
        config = root / "nginx.conf"
        config.write_text(
            f"daemon off; master_process off; pid {root}/nginx.pid;\n"
            f"error_log {root}/error.log; events {{ worker_connections 32; }}\n"
            f"http {{ access_log off; server {{ listen 127.0.0.1:{cls.port};\n"
            + snippet
            + '\nlocation ~ \\.txt$ { return 200 "UNSAFE REGEX"; }\n'
            + 'location / { return 404; }\n} }\n'
        )
        subprocess.run([nginx, "-t", "-p", str(root) + "/", "-c", str(config)], check=True)
        cls.process = subprocess.Popen([nginx, "-p", str(root) + "/", "-c", str(config)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_nginx)
        for _ in range(100):
            if cls.process.poll() is not None:
                raise RuntimeError((root / "error.log").read_text())
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("Isolated Nginx did not start.")

    @classmethod
    def stop_nginx(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)

    def request(self, path, method="GET"):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_public_logo_and_head(self):
        status, _, body = self.request("/media/entreprises/logos/public.png")
        self.assertEqual((status, body), (200, b"SYNTHETIC FILE ONLY"))
        self.assertEqual(self.request("/media/entreprises/logos/public.png", "HEAD")[0], 200)

    def test_existing_private_files_and_future_prefixes_are_denied(self):
        for name in ("payments/supporting_docs/proof.txt", "abonnements/preuves/proof.txt",
                     "messages/entreprise_1/conversation_1/fake.txt", "profiles/avatar.png",
                     "future-private-module/proof.txt"):
            for method in ("GET", "HEAD"):
                with self.subTest(name=name, method=method):
                    status, headers, body = self.request("/media/" + name, method)
                    self.assertEqual(status, 404)
                    self.assertEqual(headers.get("Cache-Control"), "private, no-store")
                    self.assertNotIn(b"SYNTHETIC", body)

    def test_normalized_and_encoded_parent_paths_do_not_escape_public_logos(self):
        for tail in ("../../payments/supporting_docs/proof.txt",
                     "%2e%2e/%2e%2e/payments/supporting_docs/proof.txt"):
            self.assertEqual(self.request("/media/entreprises/logos/" + tail)[0], 404)

    def test_symlink_from_public_logo_to_private_file_is_denied(self):
        status, _, body = self.request("/media/entreprises/logos/link.png")
        self.assertIn(status, (403, 404))
        self.assertNotIn(b"SYNTHETIC", body)

    def test_directory_listing_and_bare_media_are_denied(self):
        for path in ("/media", "/media/", "/media/entreprises/logos/"):
            self.assertIn(self.request(path)[0], (403, 404))

    def test_public_logos_are_read_only(self):
        self.assertEqual(self.request("/media/entreprises/logos/public.png", "POST")[0], 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
