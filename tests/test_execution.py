"""Exercise real script execution and its shared-interpreter lifecycle."""

import io
import os
from pathlib import Path
import py_compile
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from vscode_app.execution import OUTPUT_LIMIT
from vscode_app.filesystem import WorkspaceError
from vscode_app.workspace import WorkspaceApp


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pythona_vscode_run_")
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "Documents" / "Project 你好"
        self.project.mkdir(parents=True)
        (self.root / "Documents" / "Other").mkdir()
        self.app = WorkspaceApp(self.root / "Documents", self.root / "state.json")
        self.workspace = self.app.open_workspace(self.project.name)
        self.request = None
        self.worker_errors = []
        original_hook = threading.excepthook

        def record(error):
            if error.thread.name == "PythonaVSCodeRun":
                self.worker_errors.append(str(error.exc_value))
            else:
                original_hook(error)

        self.hook = patch.object(threading, "excepthook", record)
        self.hook.start()

    def tearDown(self):
        self.app.close()
        if self.app.runner.current:
            self.app.runner.current.thread.join()
        self.hook.stop()
        self.temporary.cleanup()
        self.assertEqual(self.worker_errors, [])

    def start(self, code, **options):
        path = options.get("path", "main.py")
        (self.project / path).write_text(code, encoding="utf-8")
        self.request = {"workspace": self.workspace["id"], "id": str(uuid.uuid4()),
                        "path": path, **options}
        return self.app.dispatch("run.start", self.request)

    def status(self, **payload):
        return self.app.dispatch("run.status", {**self.request, **payload})

    def wait_for(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.status()
            if predicate(status):
                return status
            time.sleep(0.01)
        self.fail(f"Python did not reach the expected state: {self.status()}")

    def finished(self):
        return self.wait_for(lambda status: status["state"] == "finished")

    def input(self, text="", *, eof=False):
        status = self.wait_for(lambda status: status["state"] == "input")
        request = {**self.request, "request": status["input"], "text": text, "eof": eof}
        self.app.dispatch("run.input", request)
        return request

    def stop(self):
        self.app.dispatch("run.stop", self.request)

    def test_script_arguments_cwd_imports_and_host_state_are_restored(self):
        (self.project / "src").mkdir()
        (self.project / "src" / "helper.py").write_text('value = "first"\n')
        previous = (sys.stdin, sys.stdout, sys.stderr, sys.argv, sys.path, sys.meta_path,
                    sys.modules["__main__"], os.getcwd())
        self.start('import os, sys, helper\nprint(__name__, helper.value, sys.argv[1:])\n'
                   'print(os.getcwd(), __file__)\nos.chdir("..")\n',
                   path="src/main.py", arguments='one "two words" 你好', cwd="src")
        result = self.finished()
        self.assertEqual(result["exitCode"], 0)
        self.assertIn("__main__ first ['one', 'two words', '你好']", result["output"])
        self.assertIn(str(self.project / "src"), result["output"])
        self.assertNotIn("helper", sys.modules)
        self.assertEqual(previous, (sys.stdin, sys.stdout, sys.stderr, sys.argv, sys.path,
                                   sys.meta_path, sys.modules["__main__"], os.getcwd()))

    def test_rerun_reloads_project_source_even_with_valid_stale_bytecode(self):
        helper = self.project / "helper.py"
        helper.write_text('value = "first"\n')
        py_compile.compile(str(helper), doraise=True)
        timestamp = helper.stat().st_mtime_ns
        self.start('import helper\nprint(helper.value)\n')
        self.assertEqual(self.finished()["output"], "first\n")
        helper.write_text('value = "other"\n')
        os.utime(helper, ns=(timestamp, timestamp))
        self.start('import helper\nprint(helper.value)\n')
        self.assertEqual(self.finished()["output"], "other\n")

    def test_unicode_input_output_stderr_and_binary_streams(self):
        self.start('import sys\nname = input("Name: ")\nprint("Hello", name)\n'
                   'print("error text", file=sys.stderr)\n'
                   'sys.stdout.buffer.write(b"\\xe4")\n'
                   'sys.stdout.buffer.write(b"\\xbd\\xa0\\n")\n')
        accepted = self.input("你好 🐍")
        with self.assertRaises(WorkspaceError):
            self.app.dispatch("run.input", accepted)
        result = self.finished()
        self.assertEqual(result["exitCode"], 0)
        self.assertEqual(result["output"], "Name: 你好 🐍\nHello 你好 🐍\nerror text\n你\n")

    def test_stdin_buffer_and_eof(self):
        self.start('import sys\nprint(repr(sys.stdin.buffer.read()))\n')
        self.input("你好\0")
        self.input(eof=True)
        result = self.finished()
        self.assertEqual(result["exitCode"], 0)
        self.assertIn(repr("你好\0\n".encode()), result["output"])

    def test_stop_wakes_input_and_does_not_poison_next_run(self):
        self.start('input("Waiting: ")\n')
        old = self.wait_for(lambda status: status["state"] == "input")
        old_request = dict(self.request)
        self.stop()
        self.assertEqual(self.finished()["exitCode"], 130)
        self.start('print(input("Again: "))\n')
        with self.assertRaises(WorkspaceError):
            self.app.dispatch("run.input", {**old_request, "request": old["input"], "text": "stale"})
        with self.assertRaises(WorkspaceError):
            self.app.dispatch("run.stop", old_request)
        self.input("fresh")
        self.assertIn("Again: fresh\nfresh\n", self.finished()["output"])

    def test_stop_interrupts_python_loops_and_script_threads(self):
        self.start('import threading\ndef worker():\n print("child ready")\n while True: pass\n'
                   'threading.Thread(target=worker).start()\nwhile True: pass\n')
        self.wait_for(lambda status: "child ready" in status["output"])
        self.stop()
        self.assertEqual(self.finished()["exitCode"], 130)
        self.start('print("next run")\n')
        self.assertEqual(self.finished()["output"], "next run\n")

    def test_host_output_is_not_routed_to_the_script(self):
        host_output = io.StringIO()
        with patch.object(sys, "stdout", host_output):
            self.start('input("script: ")\n')
            self.wait_for(lambda status: status["state"] == "input")
            print("host output")
            self.stop()
            result = self.finished()
        self.assertEqual(host_output.getvalue(), "host output\n")
        self.assertEqual(result["output"], "script: ")

    def test_blocking_calls_remain_stopping_until_return_and_block_workspace_changes(self):
        self.start('import time\nprint("sleeping")\ntime.sleep(0.35)\nprint("too late")\n')
        self.wait_for(lambda status: "sleeping" in status["output"])
        self.stop()
        self.assertEqual(self.status()["state"], "stopping")
        for action, payload in [("workspace.open", {"path": "Other"}), ("workspace.close", {}),
                                ("host.close", {}), ("run.start", {**self.request, "id": str(uuid.uuid4())})]:
            with self.subTest(action=action), self.assertRaises(WorkspaceError):
                self.app.dispatch(action, payload)
        result = self.finished()
        self.assertEqual(result["exitCode"], 130)
        self.assertNotIn("too late", result["output"])

    def test_stop_is_deferred_until_import_finishes(self):
        (self.project / "slow.py").write_text(
            'import time\nfrom pathlib import Path\nprint("importing")\ntime.sleep(.2)\n'
            'Path("import-finished").write_text("yes")\n')
        self.start('import slow\nprint("after import")\n')
        self.wait_for(lambda status: "importing" in status["output"])
        self.stop()
        result = self.finished()
        self.assertEqual(result["exitCode"], 130)
        self.assertEqual((self.project / "import-finished").read_text(), "yes")
        self.assertNotIn("after import", result["output"])

    def test_preview_trace_fallback_stops_and_restores_tracing(self):
        previous = sys.gettrace(), threading.gettrace()
        with patch.object(sys, "monitoring", None, create=True):
            self.start('print("fallback ready")\nwhile True: pass\n')
            self.wait_for(lambda status: "fallback ready" in status["output"])
            self.stop()
            self.assertEqual(self.finished()["exitCode"], 130)
        self.assertEqual(previous, (sys.gettrace(), threading.gettrace()))

    def test_closed_or_detached_streams_do_not_break_cleanup(self):
        for source in ('import sys\nsys.stdout.detach()\nsys.stdin.detach()\n',
                       'import sys\nsys.stdout.close()\nsys.stderr.close()\nsys.stdin.close()\n'):
            with self.subTest(source=source):
                self.start(source)
                self.assertEqual(self.finished()["exitCode"], 0)
                self.start('print("streams restored")\n')
                self.assertEqual(self.finished()["output"], "streams restored\n")

    def test_a_moved_workspace_must_be_reopened_before_execution(self):
        (self.project / "main.py").write_text('print("original")\n')
        moved = self.project.with_name("Moved")
        self.project.rename(moved)
        self.project.mkdir()
        (self.project / "main.py").write_text('print("replacement")\n')
        with self.assertRaisesRegex(WorkspaceError, "workspace moved"):
            self.app.dispatch("run.start", {"workspace": self.workspace["id"],
                                           "id": str(uuid.uuid4()), "path": "main.py"})
        self.assertIsNone(self.app.runner.current)

    def test_errors_and_system_exit_leave_the_editor_host_alive(self):
        for source, code, text in [('raise ValueError("example")', 1, 'ValueError: example'),
                                   ('def broken(:', 1, 'SyntaxError'),
                                   ('import sys; sys.exit(7)', 7, ''),
                                   ('import sys; sys.exit("reason")', 1, 'reason'),
                                   ('print("recovered")', 0, 'recovered')]:
            with self.subTest(source=source):
                self.start(source)
                result = self.finished()
                self.assertEqual(result["exitCode"], code)
                self.assertIn(text, result["output"])
                self.assertFalse(self.app.closed.is_set())
                if "Error" in text:
                    self.assertIn('/Documents/Project 你好/main.py', result["output"])

    def test_duplicate_start_is_not_replayed_and_output_is_bounded(self):
        self.start('print("x" * (2 * 1024 * 1024))\n')
        result = self.finished()
        self.assertTrue(result["truncated"])
        self.assertLessEqual(self.app.runner.current.output_end - self.app.runner.current.output_start, OUTPUT_LIMIT)
        identity = self.app.runner.current
        self.app.dispatch("run.start", self.request)
        self.assertIs(self.app.runner.current, identity)
        while result["more"]:
            previous = result["next"]
            result = self.status(after=previous)
            self.assertGreater(result["next"], previous)
            self.assertFalse(result["truncated"])

    def test_execution_rejects_traversal_symlinks_and_stale_workspace_requests(self):
        (self.project / "main.py").write_text('print("valid")\n')
        (self.project / "link.py").symlink_to(self.project / "main.py")
        (self.project / "linkdir").symlink_to(self.project, target_is_directory=True)
        base = {"workspace": self.workspace["id"], "id": str(uuid.uuid4()), "path": "main.py"}
        for extra in [{"path": "../main.py"}, {"path": "link.py"}, {"path": "linkdir/main.py"},
                      {"cwd": "linkdir"}, {"cwd": "../Other"}, {"arguments": '"unterminated'},
                      {"arguments": [3]}, {"id": "bad"}, {"path": "README.md"}]:
            with self.subTest(extra=extra), self.assertRaises(WorkspaceError):
                self.app.dispatch("run.start", {**base, **extra})
        self.app.open_workspace("Other")
        for action in ("run.start", "run.status", "run.stop", "run.input"):
            with self.subTest(action=action), self.assertRaises(WorkspaceError):
                self.app.dispatch(action, base)


if __name__ == "__main__":
    unittest.main()
