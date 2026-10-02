import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import targets  # noqa: E402


def make_app(root, app_id, manifest, compose=""):
    folder = Path(root) / app_id
    folder.mkdir()
    (folder / "umbrel-app.yml").write_text(manifest, encoding="utf-8")
    if compose:
        (folder / "docker-compose.yml").write_text(compose, encoding="utf-8")
    return folder


class ScalarTest(unittest.TestCase):
    def test_plain_quoted_and_comment(self):
        text = 'id: a\nname: "Meu App"\nversion: \'1.0\'\nport: 80 # http\n'
        self.assertEqual(targets._scalar(text, "name"), "Meu App")
        self.assertEqual(targets._scalar(text, "version"), "1.0")
        self.assertEqual(targets._scalar(text, "port"), "80")

    def test_apostrophe_inside_double_quotes(self):
        self.assertEqual(targets._scalar('name: "Bob\'s App"\n', "name"), "Bob's App")

    def test_double_quote_inside_single_quotes(self):
        self.assertEqual(targets._scalar("name: 'Say \"hi\"'\n", "name"), 'Say "hi"')

    def test_hash_without_space_is_not_a_comment(self):
        self.assertEqual(targets._scalar("name: C#\n", "name"), "C#")

    def test_missing_key(self):
        self.assertEqual(targets._scalar("id: a\n", "name"), "")


class ReadAppTest(unittest.TestCase):
    def test_proxy_target(self):
        with tempfile.TemporaryDirectory() as root:
            folder = make_app(
                root, "a1", "id: a1\nname: A1\nport: 3000\n",
                "services:\n  app_proxy:\n    environment:\n      APP_HOST: a1_web_1\n      APP_PORT: 3000\n",
            )
            app = targets.read_app(folder)
        self.assertEqual((app["kind"], app["target"]), ("proxy", "http://a1_web_1:3000"))

    def test_expose_is_not_a_published_port(self):
        compose = "services:\n  web:\n    image: x\n    ports:\n      - 9000:9000\n    expose:\n      - 8080\n"
        with tempfile.TemporaryDirectory() as root:
            folder = make_app(root, "a2", "id: a2\nname: A2\nport: 9000\n", compose)
            app = targets.read_app(folder)
        self.assertEqual(app["containers"][0]["published_ports"], ["9000:9000"])
        self.assertEqual(app["target"], "http://a2_web_1:9000")

    def test_unreadable_app_keeps_the_shape_the_page_needs(self):
        with tempfile.TemporaryDirectory() as root:
            folder = make_app(root, "a3", "id: a3\n")
            with mock.patch.object(Path, "read_text", side_effect=OSError("boom")):
                app = targets.read_app(folder)
        self.assertEqual(app["error"], "boom")
        self.assertEqual(app["containers"], [])
        self.assertEqual(app["kind"], "outro")
        self.assertEqual(app["target"], "")

    def test_folder_without_manifest_is_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "vazia").mkdir()
            self.assertEqual(targets.scan(root), [])


class ConfigStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = targets.connect(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_empty_config(self):
        self.assertEqual(targets.load_config(self.db), {"domain": "", "hostnames": {}, "unpublished": []})

    def test_domain_is_normalized_saved_and_cleared(self):
        targets.save_domain(self.db, " MeuDominio.com ")
        self.assertEqual(targets.load_config(self.db)["domain"], "meudominio.com")
        targets.save_domain(self.db, "")
        self.assertEqual(targets.load_config(self.db)["domain"], "")

    def test_hostname_saved_replaced_and_cleared(self):
        targets.save_hostname(self.db, "a1", "a.meudominio.com")
        targets.save_hostname(self.db, "a1", "b.meudominio.com")
        self.assertEqual(targets.load_config(self.db)["hostnames"], {"a1": "b.meudominio.com"})
        targets.save_hostname(self.db, "a1", "")
        self.assertEqual(targets.load_config(self.db)["hostnames"], {})

    def test_unpublished_flag_set_and_cleared(self):
        targets.save_unpublished(self.db, "b", True)
        targets.save_unpublished(self.db, "a", True)
        targets.save_unpublished(self.db, "a", True)
        self.assertEqual(targets.load_config(self.db)["unpublished"], ["a", "b"])
        targets.save_unpublished(self.db, "a", False)
        self.assertEqual(targets.load_config(self.db)["unpublished"], ["b"])

    def test_unpublished_requires_boolean_and_valid_id(self):
        with self.assertRaises(ValueError):
            targets.save_unpublished(self.db, "a", "true")
        with self.assertRaises(ValueError):
            targets.save_unpublished(self.db, "../x", True)

    def test_invalid_values_are_rejected(self):
        for bad in ("sem-ponto", "http://x.com", "a b.com", "x.com/path", "-a.com"):
            with self.assertRaises(ValueError, msg=bad):
                targets.save_domain(self.db, bad)
            with self.assertRaises(ValueError, msg=bad):
                targets.save_hostname(self.db, "a1", bad)
        with self.assertRaises(ValueError):
            targets.save_hostname(self.db, "../x", "a.meudominio.com")


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "apps").mkdir()
        make_app(root / "apps", "a1", "id: a1\nname: A1\n")
        self.server = targets.make_server(root / "apps", 0, root / "t.db")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def put(self, path, value, content_type="application/json"):
        req = urllib.request.Request(self.base + path, data=json.dumps({"value": value}).encode(),
                                     method="PUT", headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return json.load(r)

    def test_domain_and_hostname_round_trip(self):
        self.assertEqual(self.put("/api/domain", "meudominio.com")[0], 200)
        status, config = self.put("/api/hostnames/a1", "a1.meudominio.com")
        self.assertEqual(status, 200)
        self.assertEqual(config, {"domain": "meudominio.com", "hostnames": {"a1": "a1.meudominio.com"},
                                  "unpublished": []})
        self.assertEqual(self.get("/api/config"), config)

    def test_unpublished_round_trip(self):
        status, config = self.put("/api/unpublished/a1", True)
        self.assertEqual((status, config["unpublished"]), (200, ["a1"]))
        self.assertEqual(self.put("/api/unpublished/a1", False)[1]["unpublished"], [])

    def test_unpublished_rejects_non_boolean(self):
        self.assertEqual(self.put("/api/unpublished/a1", "sim")[0], 400)

    def test_invalid_value_is_400(self):
        status, body = self.put("/api/domain", "invalido")
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_non_json_content_type_is_rejected(self):
        self.assertEqual(self.put("/api/domain", "meudominio.com", "text/plain")[0], 415)
        self.assertEqual(self.get("/api/config")["domain"], "")


if __name__ == "__main__":
    unittest.main()
