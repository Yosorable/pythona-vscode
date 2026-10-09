# Agent guide

Read README.md for the architecture, runtime limits, and validation commands.

- Keep `main.py` as the entry point. UIKit and Rubicon imports belong only on the iOS path.
- The frontend uses the real VS Code workbench through `monaco-vscode-api`.
  Keep every `@codingame/monaco-vscode-*` package on the same pinned version.
- Rebuild and include `frontend/dist` and `frontend/THIRD_PARTY_NOTICES.txt`
  after frontend changes. Installed projects run without Node.js or a CDN.
- Open one explicitly selected project folder in Documents. Documents itself
  must never become the workspace. Keep workspace identity on every file request.
- Keep file operations relative to open directory descriptors. Reject traversal
  and symlink traversal; atomic saves must preserve existing data on failure.
- Network and filesystem work stay off UIKit's main thread. Use `run_on_ui`
  for UIKit calls and explicitly close the HTTP server, descriptors, and WebKit handlers.
- Keep the server loopback-only, with session, Host, and Origin validation.
  A browser preview uses temporary files unless `--documents` is explicitly supplied.
- Keep the web view transparent until the frontend readiness message arrives.
  Wait for theme loading and layout restoration, including on workspace reload.
  Use the saved theme for native, HTML, and initial workbench colors; preserve user
  settings and do not persist unconfirmed theme previews.
- Keep custom product strings in `frontend/src/strings.ts` and load upstream
  language packs before importing workbench code.
- Run the relevant Python and built-frontend integration tests after behavior changes.
  Native smoke tests use temporary workspaces and must not edit the user's projects.
