import json
import os
from pathlib import Path
import tempfile
import unittest

from vscode_app.filesystem import MAX_FILE_BYTES, WorkspaceError
from vscode_app.workspace import WorkspaceApp


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pythona_vscode_test_")
        self.root = Path(self.temporary.name)
        self.documents = self.root / "Documents"
        self.project = self.documents / "Project 你好 🐍"
        self.project.mkdir(parents=True)
        (self.project / "main.py").write_text('print("original")\n', encoding="utf-8")
        (self.documents / "Other").mkdir()
        (self.documents / "Other" / "private.py").write_text("private", encoding="utf-8")
        self.state = self.root / "state" / "state.json"
        self.app = WorkspaceApp(self.documents, self.state)

    def tearDown(self):
        self.app.close()
        self.temporary.cleanup()

    def open(self, path="Project 你好 🐍"):
        return self.app.dispatch("workspace.open", {"path": path})

    def fs(self, action, path="", **payload):
        return self.app.dispatch("fs." + action, {
            "workspace": self.app.workspace["id"], "path": path, **payload,
        })

    def write(self, path, text, **options):
        return self.fs("write", path, data=text.encode(),
                       create=True, overwrite=True, **options)

    def test_starts_empty_and_opens_only_a_selected_project(self):
        self.assertIsNone(self.app.dispatch("bootstrap")["workspace"])
        with self.assertRaises(WorkspaceError):
            self.open("")
        self.open()
        self.assertEqual(self.fs("list"), [["main.py", 1]])
        self.assertNotIn("Other", str(self.fs("list")))
        self.assertEqual(self.app.dispatch("folders.list")["directories"], ["Other", "Project 你好 🐍"])

    def test_workspace_switch_rejects_requests_from_previous_page(self):
        old = self.open()
        self.open("Other")
        with self.assertRaisesRegex(WorkspaceError, "no longer open"):
            self.app.dispatch("fs.read", {"workspace": old["id"], "path": "main.py"})
        self.assertEqual(self.fs("list"), [["private.py", 1]])

    def test_reopens_last_workspace_and_can_close_it(self):
        expected = self.open()
        self.app.close()
        self.app = WorkspaceApp(self.documents, self.state)
        self.assertEqual(self.app.workspace, expected)
        self.app.dispatch("workspace.close")
        self.app.close()
        self.app = WorkspaceApp(self.documents, self.state)
        self.assertIsNone(self.app.workspace)
        self.assertEqual(self.app.recent, ["Project 你好 🐍"])

    def test_missing_last_workspace_starts_empty(self):
        self.open()
        self.app.close()
        self.project.rename(self.documents / "Moved")
        self.app = WorkspaceApp(self.documents, self.state)
        self.assertIsNone(self.app.workspace)

    def test_failed_state_save_keeps_previous_workspace(self):
        expected = self.open()
        self.state.unlink()
        self.state.mkdir()
        with self.assertRaises(WorkspaceError):
            self.open("Other")
        self.assertEqual(self.app.workspace, expected)
        self.assertEqual(self.fs("list"), [["main.py", 1]])

    def test_workspace_traversal_and_documents_root_are_rejected(self):
        for path in ["", ".", "..", "../outside", "/", "Other/../Project 你好 🐍", "Other//nested", "a\0b"]:
            with self.subTest(path=path), self.assertRaises(WorkspaceError):
                self.open(path)

    def test_file_operations_cannot_escape_the_workspace(self):
        self.open()
        for path in ["../Other/private.py", "/Other/private.py", "a/../../private.py", "main.py\0"]:
            with self.subTest(path=path), self.assertRaises(WorkspaceError):
                self.fs("read", path)
            with self.subTest(path=path), self.assertRaises(WorkspaceError):
                self.write(path, "unexpected")
        with self.assertRaises(WorkspaceError):
            self.fs("rename", "main.py", target="../stolen.py", overwrite=False)
        with self.assertRaises(WorkspaceError):
            self.fs("delete", "", recursive=True)
        self.assertEqual((self.documents / "Other/private.py").read_text(), "private")

    def test_symlinks_cannot_escape_or_redirect_file_access(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret").write_text("secret")
        (self.documents / "Linked Project").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(WorkspaceError):
            self.open("Linked Project")
        self.open()
        (self.project / "link").symlink_to(outside, target_is_directory=True)
        (self.project / "secret").symlink_to(outside / "secret")
        for path in ["link/secret", "secret"]:
            with self.assertRaises(WorkspaceError):
                self.fs("read", path)
            with self.assertRaises(WorkspaceError):
                self.write(path, "changed")
        self.fs("delete", "link", recursive=True)
        self.assertEqual((outside / "secret").read_text(), "secret")

    def test_open_directory_descriptor_survives_path_replacement(self):
        self.open()
        moved = self.documents / "Moved"
        self.project.rename(moved)
        self.project.symlink_to(self.documents / "Other", target_is_directory=True)
        self.write("main.py", "still in original project")
        self.assertEqual((moved / "main.py").read_text(), "still in original project")
        self.assertFalse((self.documents / "Other/main.py").exists())

    def test_atomic_unicode_save_and_conflicting_external_edit(self):
        self.open()
        original = self.fs("read", "main.py")
        (self.project / "main.py").chmod(0o640)
        result = self.write("main.py", "print('你好 🐍')\n", expected=original["revision"])
        self.assertNotEqual(result["revision"], original["revision"])
        self.assertEqual((self.project / "main.py").stat().st_mode & 0o777, 0o640)
        (self.project / "main.py").write_text("external edit")
        with self.assertRaisesRegex(WorkspaceError, "changed on disk"):
            self.write("main.py", "stale edit", expected=result["revision"])
        self.assertEqual((self.project / "main.py").read_text(), "external edit")
        self.assertFalse(list(self.project.glob(".pythona-vscode-*.tmp")))

    def test_file_and_folder_creation_rename_and_delete(self):
        self.open()
        self.fs("mkdir", "nested")
        self.write("nested/a.py", "hello")
        self.fs("rename", "nested/a.py", target="nested/renamed.py", overwrite=False)
        self.assertEqual(self.fs("list", "nested"), [["renamed.py", 1]])
        self.fs("delete", "nested", recursive=True)
        self.assertFalse((self.project / "nested").exists())

    def test_existing_file_is_not_overwritten_by_create(self):
        self.open()
        with self.assertRaises(WorkspaceError):
            self.fs("write", "main.py", data=b"hello", create=True, overwrite=False)
        self.assertEqual((self.project / "main.py").read_text(), 'print("original")\n')

    def test_nonregular_files_and_large_files_are_rejected(self):
        self.open()
        os.mkfifo(self.project / "pipe")
        with self.assertRaises(WorkspaceError):
            self.fs("read", "pipe")
        with (self.project / "large.bin").open("wb") as stream:
            stream.truncate(MAX_FILE_BYTES + 1)
        with self.assertRaisesRegex(WorkspaceError, "16 MiB"):
            self.fs("read", "large.bin")

    def test_settings_are_local_persistent_and_path_scoped(self):
        self.app.dispatch("storage.update", {"key": "profile", "insert": {"theme": "dark"}})
        self.assertEqual(self.app.dispatch("storage.read", {"key": "profile"}), {"theme": "dark"})
        self.app.dispatch("storage.update", {"key": "profile", "delete": ["theme"]})
        self.assertEqual(self.app.dispatch("storage.read", {"key": "profile"}), {})
        with self.assertRaises(WorkspaceError):
            self.app.dispatch("storage.read", {"key": "../../private"})

    def test_malformed_requests_do_not_write_files(self):
        self.open()
        for extra in [{"data": "not bytes"}, {"data": b"h", "create": "yes"},
                      {"data": b"h", "expected": "bad"}]:
            with self.assertRaises(WorkspaceError):
                self.fs("write", "bad.py", **extra)
        self.assertFalse((self.project / "bad.py").exists())


if __name__ == "__main__":
    unittest.main()
