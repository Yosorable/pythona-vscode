import { getService, IConfigurationService, IWorkbenchThemeService } from '@codingame/monaco-vscode-api';
import { getUserConfiguration, onUserConfigurationChange } from '@codingame/monaco-vscode-configuration-service-override/common';
import { parse } from '@codingame/monaco-vscode-api/vscode/vs/base/common/json';
import { migrateThemeSettingsId } from '@codingame/monaco-vscode-api/vscode/vs/workbench/services/themes/common/workbenchThemeService';
import { call, type Preferences, type ThemeSnapshot } from './bridge';
import { t } from './strings';

export async function restorePreferences(initial: Preferences, reportError: (error: unknown) => void) {
  const themes = await getService(IWorkbenchThemeService);
  const configuration = await getService(IConfigurationService);
  const available = await themes.getColorThemes();

  async function loadSelectedTheme(): Promise<void> {
    const name = migrateThemeSettingsId(configuration.getValue<string>('workbench.colorTheme'));
    const selected = available.find(theme => theme.settingsId === name)
      ?? available.find(theme => theme.settingsId === initial.theme.name)
      ?? available.find(theme => theme.settingsId === 'Dark Modern');
    // initialize() returns before the theme service's asynchronous JSON loading.
    // Its public sequencer also waits for any theme initialization already in flight.
    if (!selected || !await themes.setColorTheme(selected.id, undefined)) {
      throw new Error(t('themeFailed'));
    }
  }
  await loadSelectedTheme();

  function snapshot(): ThemeSnapshot {
    const theme = themes.getColorTheme();
    const colors: Record<string, string> = {};
    for (const key of ['foreground', 'editor.background', 'editor.foreground', 'sideBar.background',
      'titleBar.activeBackground', 'titleBar.inactiveBackground', 'activityBar.background',
      'statusBar.background', 'panel.background']) {
      const color = theme.getColor(key);
      if (color) colors[key] = '#' + [color.rgba.r, color.rgba.g, color.rgba.b]
        .map(component => component.toString(16).padStart(2, '0')).join('');
    }
    return { name: theme.settingsId, type: theme.type, colors };
  }

  function applySurface(): void {
    const theme = snapshot();
    const style = document.documentElement.style;
    style.setProperty('--startup-background', theme.colors['sideBar.background']);
    style.setProperty('--startup-foreground', theme.colors.foreground);
    style.colorScheme = theme.type === 'light' || theme.type === 'hcLight' ? 'light' : 'dark';
    window.webkit?.messageHandlers?.workbenchTheme?.postMessage(JSON.stringify(theme));
  }

  let previous = JSON.stringify(initial);
  let pending = Promise.resolve();
  async function save(): Promise<void> {
    const settings = await getUserConfiguration();
    const theme = snapshot();
    const configured = migrateThemeSettingsId(configuration.getValue<string>('workbench.colorTheme'));
    // Quick-pick previews change the applied theme before the user confirms it.
    if (theme.name !== configured) return;
    const rawTheme = parse(settings)?.['workbench.colorTheme'];
    const userTheme = configuration.inspect<string>('workbench.colorTheme').userValue;
    // A file event can precede the configuration service parsing the new settings.
    if (typeof rawTheme === 'string' && migrateThemeSettingsId(rawTheme) !== migrateThemeSettingsId(userTheme ?? '')) return;
    const value = { settings, theme };
    const encoded = JSON.stringify(value);
    if (encoded === previous) return;
    await call('preferences.update', value);
    previous = encoded;
  }
  function enqueueSave(): Promise<void> {
    pending = pending.catch(() => {}).then(save);
    return pending;
  }
  function changed(): void { void enqueueSave().catch(reportError); }

  applySurface();
  themes.onDidColorThemeChange(() => { applySurface(); changed(); });
  configuration.onDidChangeConfiguration(changed);
  onUserConfigurationChange(changed);
  await enqueueSave().catch(reportError);

  return {
    async flush(): Promise<void> {
      await configuration.reloadConfiguration();
      await loadSelectedTheme();
      await enqueueSave();
    },
  };
}
