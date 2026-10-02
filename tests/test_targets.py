import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
