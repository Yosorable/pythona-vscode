from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vscode_app.filesystem import WorkspaceError
from vscode_app.preferences import DEFAULT_THEME, Preferences, startup_style
from vscode_app.workspace import WorkspaceApp


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pythona_vscode_preferences_")
        self.root = Path(self.temporary.name)
        self.preferences = Preferences(self.root)
        self.light = {"settings": '// Keep my settings\n{"workbench.colorTheme": "Light Modern",}\n',
                      "theme": {"name": "Light Modern", "type": "light", "colors": {
                          "sideBar.background": "#f8f8f8", "editor.background": "#ffffff", "foreground": "#616161"}}}

    def tearDown(self):
        self.temporary.cleanup()

    def test_restores_settings_with_comments_and_matching_startup_palette(self):
        self.preferences.update(self.light)
        self.assertEqual(Preferences(self.root).snapshot(), self.light)
        style = startup_style(self.light["theme"])
        self.assertIn("--startup-background: #f8f8f8", style)
        self.assertIn("color-scheme: light", style)

    def test_invalid_colors_and_oversized_settings_cannot_change_saved_preferences(self):
        self.preferences.update(self.light)
        for color in ["</style><script>alert(1)</script>", "red", "#fff", "#ffffff00", None]:
            invalid = deepcopy(self.light)
            invalid["theme"]["colors"]["sideBar.background"] = color
            with self.subTest(color=color), self.assertRaises(WorkspaceError):
                self.preferences.update(invalid)
        with self.assertRaises(WorkspaceError):
            self.preferences.update({**self.light, "settings": "x" * (1024 * 1024 + 1)})
        self.assertEqual(Preferences(self.root).snapshot(), self.light)

    def test_failed_atomic_replace_retains_disk_and_in_memory_preferences(self):
        self.preferences.update(self.light)
        with patch.object(Path, "replace", side_effect=OSError("full disk")):
            with self.assertRaises(OSError):
                self.preferences.update({"settings": "{}", "theme": DEFAULT_THEME})
        self.assertEqual(self.preferences.snapshot(), self.light)
        self.assertEqual(Preferences(self.root).snapshot(), self.light)
        self.assertFalse(self.preferences.path.with_suffix(".tmp").exists())

    def test_corrupt_preferences_fall_back_and_legacy_theme_can_migrate(self):
        self.preferences.path.write_text("not json")
        self.assertEqual(Preferences(self.root).snapshot()["theme"], DEFAULT_THEME)
        self.preferences.path.unlink()
        profile = self.root / "workbench" / "profile.json"
        profile.parent.mkdir()
        profile.write_text(json.dumps({"colorThemeData": json.dumps({
            "id": "vs vscode-theme-defaults-themes-light_modern-json", "settingsId": "Light Modern",
            "colorMap": self.light["theme"]["colors"],
        })}))
        restored = Preferences(self.root).snapshot()
        self.assertEqual(restored["theme"], self.light["theme"])
        self.assertEqual(json.loads(restored["settings"])["workbench.colorTheme"], "Light Modern")

    def test_workspace_changes_do_not_reset_preferences(self):
        documents = self.root / "Documents"
        (documents / "Project").mkdir(parents=True)
        app = WorkspaceApp(documents, self.root / "state.json")
        try:
            app.dispatch("preferences.update", self.light)
            app.dispatch("workspace.open", {"path": "Project"})
            app.dispatch("workspace.close")
            self.assertEqual(app.dispatch("bootstrap")["preferences"], self.light)
        finally:
            app.close()


if __name__ == "__main__":
    unittest.main()
