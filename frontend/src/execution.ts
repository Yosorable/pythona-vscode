import type * as VSCode from 'vscode';
import { getService, IEditorGroupsService, IEditorService } from '@codingame/monaco-vscode-api';
import { call, type Workspace } from './bridge';
import { workspaceURI } from './filesystem';
import { t } from './strings';
import type { PythonConsole } from './pythonConsole';

interface RunStatus {
  id: string;
  path: string;
  state: 'running' | 'input' | 'stopping' | 'finished';
  exitCode: number | null;
  input: number | null;
  output: string;
  next: number;
  more: boolean;
  truncated: boolean;
}

export function installExecution(api: typeof VSCode, workspace: Workspace | null, output: PythonConsole) {
  const status = api.window.createStatusBarItem(api.StatusBarAlignment.Left, 20);
  let current: RunStatus | null = null;
  let offset = 0;
  let finished: string | null = null;
  let submitting: string | null = null;
  let sent: string | null = null;
  let starting = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let polling: Promise<void> | null = null;
  let disposed = false;

  const active = () => current !== null && current.state !== 'finished';
  const payload = () => ({ workspace: workspace?.id, id: current?.id });
  const message = (error: unknown) => error instanceof Error ? error.message : String(error);
  const guarded = <T extends unknown[]>(fn: (...args: T) => Promise<unknown>) => async (...args: T) => {
    try { return await fn(...args); }
    catch (error) { void api.window.showErrorMessage(message(error)); }
  };
  output.onInput(guarded(provideInput));

  function updateInput(): void {
    const identity = current?.state === 'input' && current.input !== null ? `${current.id}:${current.input}` : null;
    output.setInput(identity, identity !== null, submitting !== null || (identity !== null && sent === identity));
  }

  async function provideInput(text: string, eof = false): Promise<void> {
    const run = current;
    if (!run || run.input === null || run.state !== 'input' || submitting) return;
    const identity = `${run.id}:${run.input}`;
    if (sent === identity) return;
    submitting = identity;
    updateInput();
    try {
      await call('run.input', { workspace: workspace?.id, id: run.id, request: run.input, text, eof });
      sent = identity;
    } finally {
      // Reconcile a lost reply by reading the request identity, never by
      // replaying input. Keep the draft if this same request is still waiting.
      await poll();
      submitting = null;
      updateInput();
    }
  }

  function apply(result: RunStatus | null): void {
    if (result && result.id !== current?.id) {
      output.clear();
      output.appendLine(`> ${result.path}`);
      offset = 0;
      finished = null;
      sent = null;
      if (!starting && result.state !== 'finished') {
        // Recover an active run after reload without moving keyboard focus.
        void guarded(() => output.show())();
      }
    }
    current = result;
    updateInput();
    void api.commands.executeCommand('setContext', 'pythona.pythonRunning', active());
    void api.commands.executeCommand('setContext', 'pythona.pythonInput', result?.state === 'input');
    if (!result) { status.hide(); return; }
    if (result.truncated) output.appendLine(t('pythonOutputTruncated'));
    output.append(result.output);
    offset = result.next;
    if (result.state === 'finished' && !result.more) {
      if (finished !== result.id) {
        output.appendLine('\n' + (result.exitCode === 130 ? t('pythonStopped')
          : t('pythonFinished').replace('{code}', String(result.exitCode))));
        finished = result.id;
      }
      status.hide();
      return;
    }
    status.text = result.state === 'input' ? `$(keyboard) ${t('pythonWaitingInput')}`
      : result.state === 'stopping' ? `$(loading~spin) ${t('pythonStopping')}`
      : `$(loading~spin) ${t('pythonRunning')}`;
    status.tooltip = result.path;
    status.command = result.state === 'input' ? 'pythona.pythonInput' : 'pythona.showPythonOutput';
    status.show();
  }

  function schedule(delay: number): void {
    clearTimeout(timer);
    if (!disposed) timer = setTimeout(() => { void poll(); }, delay);
  }

  function poll(): Promise<void> {
    if (polling) return polling;
    if (!workspace || disposed) return Promise.resolve();
    clearTimeout(timer);
    polling = (async () => {
      const requestedRun = current?.id;
      const requestedOffset = offset;
      try {
        let result = await call<RunStatus | null>('run.status', { workspace: workspace.id, after: offset });
        if (result && result.id !== current?.id && offset !== 0) {
          result = await call<RunStatus>('run.status', { workspace: workspace.id, id: result.id, after: 0 });
        }
        if (disposed) return;
        if (current?.id !== requestedRun || offset !== requestedOffset) {
          // A start response can arrive while a foreground status read is in
          // flight. Do not let that older read replace the newly started run.
          schedule(0);
          return;
        }
        apply(result);
        if (active() || result?.more) schedule(result?.more ? 0 : 100);
      } catch {
        // A failed read may be retried. Start/input/stop are never replayed here.
        if (active() || starting) {
          status.tooltip = t('connectionUnavailable');
          schedule(800);
        }
      } finally { polling = null; }
    })();
    return polling;
  }

  async function run(resource?: VSCode.Uri, context?: { groupId?: number }, withArguments = false): Promise<void> {
    if (starting) return;
    starting = true;
    try {
      // Editor-title actions can retain a previous tab's URI when their menu
      // conditions remain unchanged. The forwarded group identifies the actual
      // editor whose Run button was pressed, including an unfocused split.
      const uri = typeof context?.groupId === 'number'
        ? (await getService(IEditorGroupsService)).getGroup(context.groupId)?.activeEditor?.resource
        : resource ?? (await getService(IEditorService)).activeEditor?.resource;
      const root = workspace && workspaceURI(workspace);
      if (!uri || !root || uri.scheme !== 'file' || !uri.path.startsWith(root.path + '/')
          || !uri.path.endsWith('.py')) throw new Error(t('pythonChooseFile'));
      await poll();
      if (active()) { await output.show(); return; }
      let argumentsText = '';
      if (withArguments) {
        const answer = await api.window.showInputBox({
          title: t('pythonArguments'), prompt: t('pythonArgumentsPrompt'), ignoreFocusOut: true,
        });
        if (answer === undefined) return;
        argumentsText = answer;
      }
      if (!await api.workspace.saveAll(false)) throw new Error(t('pythonSaveFailed'));
      const id = crypto.randomUUID();
      await output.show();
      try {
        const result = await call<RunStatus>('run.start', {
          workspace: workspace!.id, id, path: uri.path.slice(root.path.length + 1),
          arguments: argumentsText,
        });
        apply(result);
      } catch (error) {
        // Resolve a lost start response by reading its identity, without running
        // the file twice. A new user Run action always gets a new identity.
        await poll();
        if (current?.id !== id) throw error;
      }
      schedule(0);
    } finally { starting = false; }
  }

  async function stop(): Promise<void> {
    if (!active()) return;
    await call('run.stop', payload());
    await poll();
  }

  api.commands.registerCommand('pythona.runPython', guarded((resource?: VSCode.Uri, context?: { groupId?: number }) => run(resource, context)));
  api.commands.registerCommand('pythona.runPythonArgs', guarded((resource?: VSCode.Uri, context?: { groupId?: number }) => run(resource, context, true)));
  api.commands.registerCommand('pythona.stopPython', guarded(stop));
  api.commands.registerCommand('pythona.pythonInput', guarded(() => output.show()));
  api.commands.registerCommand('pythona.pythonEOF', guarded(() => provideInput('', true)));
  api.commands.registerCommand('pythona.showPythonOutput', guarded(() => output.show()));
  window.addEventListener('pageshow', () => { void poll(); });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void poll();
  });
  window.addEventListener('pagehide', () => {
    disposed = true;
    clearTimeout(timer);
  });
  void poll();

  return {
    async beforeLeave(): Promise<boolean> {
      await poll();
      if (!active()) return true;
      if (await api.window.showWarningMessage(t('pythonStopBeforeLeaving'), { modal: true },
        t('stopPython')) !== t('stopPython')) return false;
      await stop();
      const deadline = performance.now() + 3000;
      while (active() && performance.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 100));
        await poll();
      }
      if (!active()) return true;
      void api.window.showWarningMessage(t('pythonStillStopping'));
      return false;
    },
  };
}
