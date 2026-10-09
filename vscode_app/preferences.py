"""Persist user settings and the confirmed theme used for the first native/HTML frame."""

from copy import deepcopy
import json
import re

from .filesystem import WorkspaceError


DEFAULT_THEME = {
    "name": "Dark Modern", "type": "dark",
    "colors": {"sideBar.background": "#181818", "editor.background": "#1f1f1f",
               "foreground": "#cccccc"},
}


def validate_theme(value):
    if (not isinstance(value, dict) or not isinstance(value.get("name"), str)
            or not 0 < len(value["name"]) <= 256
            or value.get("type") not in ("dark", "light", "hcDark", "hcLight")):
        raise WorkspaceError("InvalidRequest", "Invalid theme.")
    colors = value.get("colors")
    if (not isinstance(colors, dict) or len(colors) > 64
            or not {"sideBar.background", "editor.background", "foreground"} <= colors.keys()
            or not all(isinstance(key, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9.]{0,79}", key)
                       and isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color)
                       for key, color in colors.items())):
        raise WorkspaceError("InvalidRequest", "Invalid theme colors.")
    return {"name": value["name"], "type": value["type"],
            "colors": {key: color.lower() for key, color in colors.items()}}


def validate_preferences(value):
    if (not isinstance(value, dict) or not isinstance(value.get("settings"), str)
            or len(value["settings"].encode("utf-8")) > 1024 * 1024):
        raise WorkspaceError("InvalidRequest", "Invalid user settings.")
    # VS Code owns JSON-with-comments parsing; preserve the user's file verbatim.
    return {"settings": value["settings"], "theme": validate_theme(value.get("theme"))}


class Preferences:
    def __init__(self, state_directory):
        self.path = state_directory / "preferences.json"
        self.value = {"settings": "{}", "theme": deepcopy(DEFAULT_THEME)}
        try:
            self.value = validate_preferences(json.loads(self.path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            self._restore_legacy_theme(state_directory)
        except (OSError, ValueError, WorkspaceError):
            pass

    def _restore_legacy_theme(self, directory):
        # Earlier versions kept the selected theme only in VS Code's profile cache.
        try:
            profile = json.loads((directory / "workbench" / "profile.json").read_text(encoding="utf-8"))
            cached = json.loads(profile["colorThemeData"])
            scheme = {"vs": "light", "vs-dark": "dark", "hc-black": "hcDark", "hc-light": "hcLight"}
            colors = {key: value for key, value in cached["colorMap"].items()
                      if key in ("sideBar.background", "editor.background", "foreground")}
            theme = validate_theme({"name": cached["settingsId"],
                                    "type": scheme[cached["id"].split()[0]], "colors": colors})
            self.value = {"settings": json.dumps({"workbench.colorTheme": theme["name"]}), "theme": theme}
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, WorkspaceError):
            pass

    def update(self, value):
        value = validate_preferences(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=True) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.value = value

    def snapshot(self):
        return deepcopy(self.value)


def startup_style(theme):
    """Only validated hex colors and a fixed color-scheme enter inline CSS."""
    theme = validate_theme(theme)
    scheme = "light" if theme["type"] in ("light", "hcLight") else "dark"
    colors = theme["colors"]
    return (f'<style>:root {{ --startup-background: {colors["sideBar.background"]}; '
            f'--startup-foreground: {colors["foreground"]}; color-scheme: {scheme}; }}</style>')
