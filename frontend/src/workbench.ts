import {
  getService,
  IFileDialogService,
  IHostService,
  IStorageService,
  IWorkbenchLayoutService,
  initialize,
} from '@codingame/monaco-vscode-api';
import { registerExtension, ExtensionHostKind } from '@codingame/monaco-vscode-api/extensions';
import { CommandsRegistry } from '@codingame/monaco-vscode-api/monaco';
import { EventType as GestureEventType, type GestureEvent } from '@codingame/monaco-vscode-api/vscode/vs/base/browser/touch';
import { ColorScheme } from '@codingame/monaco-vscode-api/vscode/vs/platform/theme/common/theme';
import getWorkbenchServiceOverride from '@codingame/monaco-vscode-workbench-service-override';
import getConfigurationServiceOverride from '@codingame/monaco-vscode-configuration-service-override';
import { initUserConfiguration } from '@codingame/monaco-vscode-configuration-service-override/common';
import getDialogsServiceOverride from '@codingame/monaco-vscode-dialogs-service-override';
import getExplorerServiceOverride from '@codingame/monaco-vscode-explorer-service-override';
import { registerCustomProvider } from '@codingame/monaco-vscode-files-service-override';
import getLanguagesServiceOverride from '@codingame/monaco-vscode-languages-service-override';
import getModelServiceOverride from '@codingame/monaco-vscode-model-service-override';
import getNotificationsServiceOverride from '@codingame/monaco-vscode-notifications-service-override';
import getOutputServiceOverride from '@codingame/monaco-vscode-output-service-override';
import getSearchServiceOverride from '@codingame/monaco-vscode-search-service-override';
import getStorageServiceOverride, { StorageScope } from '@codingame/monaco-vscode-storage-service-override';
import getTextmateServiceOverride from '@codingame/monaco-vscode-textmate-service-override';
import getThemeServiceOverride from '@codingame/monaco-vscode-theme-service-override';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import TextmateWorker from '@codingame/monaco-vscode-textmate-service-override/worker?worker';
import OutputWorker from '@codingame/monaco-vscode-output-service-override/worker?worker';
import SearchWorker from '@codingame/monaco-vscode-search-service-override/worker?worker';
import '@codingame/monaco-vscode-theme-defaults-default-extension';
import '@codingame/monaco-vscode-python-default-extension';
import '@codingame/monaco-vscode-json-default-extension';
import '@codingame/monaco-vscode-markdown-basics-default-extension';
import 'vscode/localExtensionHost';
import type * as VSCode from 'vscode';
import { call, type Bootstrap } from './bridge';
import { WorkspaceFiles, workspaceURI } from './filesystem';
import { HostStorage } from './storage';
import { restorePreferences } from './preferences';
import { t } from './strings';

export async function start(bootstrap: Bootstrap): Promise<void> {
  window.MonacoEnvironment = {
    getWorker(_moduleId, label) {
      switch (label) {
        case 'TextMateWorker': return new TextmateWorker();
        case 'OutputLinkDetectionWorker': return new OutputWorker();
        case 'LocalFileSearchWorker': return new SearchWorker();
        default: return new EditorWorker();
      }
    },
  };

  registerCustomProvider('file', new WorkspaceFiles(bootstrap.workspace));
  await initUserConfiguration(bootstrap.preferences.settings);
  const configurationDefaults = {
    'workbench.colorTheme': 'Dark Modern',
    'workbench.startupEditor': 'none',
    'workbench.tips.enabled': false,
    'workbench.enableExperiments': false,
    'workbench.editor.enablePreview': true,
    'workbench.activity.showAccounts': false,
    'workbench.secondarySideBar.defaultVisibility': 'hidden',
    'window.menuBarVisibility': 'classic',
    'window.commandCenter': true,
    'window.title': '${dirty}${activeEditorShort}${separator}${rootName}${separator}Pythona VSCode',
    'editor.fontSize': 14,
    'editor.fontFamily': 'Menlo, Monaco, monospace',
    'editor.minimap.enabled': false,
    'editor.scrollBeyondLastLine': false,
    'editor.stickyScroll.enabled': true,
    'files.autoSave': 'off',
    'files.hotExit': 'off',
    'explorer.confirmDelete': true,
    'telemetry.telemetryLevel': 'off',
    'security.workspace.trust.enabled': false,
    'extensions.autoCheckUpdates': false,
    'extensions.autoUpdate': false,
    'chat.disableAIFeatures': true,
  };

  const workbench = document.querySelector<HTMLElement>('#workbench')!;
  await initialize({
    ...getWorkbenchServiceOverride(),
    ...getConfigurationServiceOverride(),
    ...getDialogsServiceOverride(),
    ...getExplorerServiceOverride(),
    ...getLanguagesServiceOverride(),
    ...getModelServiceOverride(),
    ...getNotificationsServiceOverride(),
    ...getOutputServiceOverride(),
    ...getSearchServiceOverride(),
    ...getStorageServiceOverride({
      forcedValues: { 'workbench.activity.showAccounts': false },
      databaseFactories: {
        [StorageScope.APPLICATION]: () => new HostStorage('application'),
        [StorageScope.PROFILE]: () => new HostStorage('profile'),
        [StorageScope.WORKSPACE]: () => new HostStorage(`workspace-${bootstrap.workspace?.id ?? 'empty'}`),
      },
    }),
    ...getTextmateServiceOverride(),
    ...getThemeServiceOverride(),
  }, workbench, {
    configurationDefaults,
    initialColorTheme: {
      themeType: bootstrap.preferences.theme.type as ColorScheme,
      colors: bootstrap.preferences.theme.colors,
    },
    enableWorkspaceTrust: false,
    workspaceProvider: {
      workspace: bootstrap.workspace ? { folderUri: workspaceURI(bootstrap.workspace) } : undefined,
      trusted: true,
      async open() { await chooseFolder(); return true; },
    },
    productConfiguration: {
      nameShort: 'Pythona VSCode',
      nameLong: 'Pythona VSCode',
      applicationName: 'pythona-vscode',
      enableTelemetry: false,
    },
    windowIndicator: { label: 'Pythona', tooltip: t('localWorkspace'), command: 'pythona.openFolder' },
  });

  // Gesture dispatch snapshots nested targets before a command removes its menu.
  // Skip the later tap on the menubar button so it cannot reopen and steal focus.
  workbench.addEventListener(GestureEventType.Tap, event => {
    const initialTarget = (event as GestureEvent).initialTarget;
    if (event.target instanceof Element && event.target.classList.contains('menubar-menu-button')
        && initialTarget instanceof Node && !initialTarget.isConnected) {
      event.stopImmediatePropagation();
    }
  }, true);

  const extension = registerExtension({
    name: 'workspace', publisher: 'pythona', version: '0.1.0', engines: { vscode: '*' },
    contributes: {
      commands: [
        { command: 'pythona.openFolder', title: t('openFolder'), category: 'Pythona' },
        { command: 'pythona.closeFolder', title: t('closeFolder'), category: 'Pythona' },
        { command: 'pythona.closeWindow', title: t('closeWindow'), category: 'Pythona' },
      ],
    },
  }, ExtensionHostKind.LocalProcess);
  const api = await extension.getApi();
  await extension.setAsDefaultApi();
  const preferences = await restorePreferences(bootstrap.preferences, error => {
    void api.window.showErrorMessage(`${t('preferencesFailed')} ${error instanceof Error ? error.message : String(error)}`);
  });

  async function confirmLeave(): Promise<boolean> {
    if (!api.workspace.textDocuments.some(document => document.isDirty)) return true;
    const answer = await api.window.showWarningMessage(
      t('saveChanges'), { modal: true }, t('saveAll'), t('discard'),
    );
    if (answer === t('saveAll')) return api.workspace.saveAll(true);
    return answer === t('discard');
  }

  async function flush(): Promise<void> {
    await preferences.flush();
    await (await getService(IStorageService)).flush();
  }

  async function openFolder(path: string): Promise<void> {
    if (!await confirmLeave()) return;
    await flush();
    await call('workspace.open', { path });
    window.location.reload();
  }

  let choosing = false;
  async function chooseFolder(): Promise<void> {
    if (choosing) return;
    choosing = true;
    try {
      let path = '';
      while (true) {
        const listing = await call<{ path: string; directories: string[]; parent: string | null; canOpen: boolean }>('folders.list', { path });
        type Choice = VSCode.QuickPickItem & { action: 'browse' | 'open' | 'create'; path: string };
        const choices: Choice[] = [];
        if (listing.canOpen) {
          choices.push({ label: `$(folder-opened) ${t('openThis')}`, description: path, action: 'open', path });
          choices.push({ label: `$(arrow-up) ${t('parentFolder')}`, action: 'browse', path: listing.parent ?? '' });
        } else {
          for (const recent of bootstrap.recent) {
            choices.push({ label: `$(history) ${recent.split('/').at(-1)}`, description: recent,
              detail: t('recent'), action: 'open', path: recent });
          }
        }
        choices.push(...listing.directories.map(name => ({
          label: `$(folder) ${name}`, action: 'browse' as const, path: path ? `${path}/${name}` : name,
        })));
        choices.push({ label: `$(new-folder) ${t('newFolder')}`, action: 'create', path });
        const choice = await api.window.showQuickPick(choices, {
          title: t('folderTitle'), placeHolder: path ? `Documents / ${path}` : t('chooseProject'),
          ignoreFocusOut: true, matchOnDescription: true,
        });
        if (!choice) return;
        if (choice.action === 'open') {
          await openFolder(choice.path);
          return;
        }
        if (choice.action === 'create') {
          const name = await api.window.showInputBox({
            title: t('newFolder'), prompt: t('folderName'), ignoreFocusOut: true,
            validateInput: value => (!value || value === '.' || value === '..' || value.startsWith('.') || /[\/\0]/.test(value))
              ? t('invalidName') : undefined,
          });
          if (!name) continue;
          path = path ? `${path}/${name}` : name;
          await call('folders.create', { path });
        } else {
          path = choice.path;
        }
      }
    } catch (error) {
      await api.window.showErrorMessage(error instanceof Error ? error.message : String(error));
    } finally {
      choosing = false;
    }
  }

  async function closeFolder(): Promise<void> {
    if (!await confirmLeave()) return;
    await flush();
    await call('workspace.close');
    window.location.reload();
  }

  async function closeWindow(): Promise<void> {
    if (!await confirmLeave()) return;
    await flush();
    await call('host.close');
    document.body.textContent = t('closed');
  }

  api.commands.registerCommand('pythona.openFolder', chooseFolder);
  api.commands.registerCommand('pythona.closeFolder', closeFolder);
  api.commands.registerCommand('pythona.closeWindow', closeWindow);
  CommandsRegistry.registerCommand('workbench.action.closeFolder', closeFolder);
  CommandsRegistry.registerCommand('workbench.action.openRecent', chooseFolder);

  // Route the workbench's native Open Folder actions to the Documents picker.
  const dialogs = await getService(IFileDialogService);
  dialogs.pickFolderAndOpen = chooseFolder;
  dialogs.pickWorkspaceAndOpen = chooseFolder;
  const host = await getService(IHostService);
  host.close = closeWindow;
  window.pythonaWorkbench.requestClose = async () => {
    try { await closeWindow(); }
    catch (error) { await api.window.showErrorMessage(error instanceof Error ? error.message : String(error)); }
  };
  window.pythonaWorkbench.executeCommand = (command, ...args) => Promise.resolve(api.commands.executeCommand(command, ...args));

  await api.commands.executeCommand('workbench.view.explorer');
  await (await getService(IWorkbenchLayoutService)).whenRestored;
}
