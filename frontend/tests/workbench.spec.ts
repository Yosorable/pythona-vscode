import { test as base, expect, type Page } from '@playwright/test';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
type Host = { url: string; documents: string; state: string };
const test = base.extend<{ host: Host }>({
  host: async ({}, use) => {
    const temporary = await mkdtemp(join(tmpdir(), 'pythona_vscode_browser_'));
    const documents = join(temporary, 'Documents');
    const state = join(temporary, 'state.json');
    await mkdir(join(documents, 'Project One', 'src'), { recursive: true });
    await mkdir(join(documents, 'Other Project'));
    await writeFile(join(documents, 'Project One', 'main.py'), 'print("workspace one")\n');
    await writeFile(join(documents, 'Project One', 'src', '你好 🐍.py'), 'message = "needle in nested file"\n');
    await writeFile(join(documents, 'Other Project', 'other.py'), '# other workspace\n');
    const child = spawn(process.env.PYTHONA_TEST_PYTHON ?? 'python3', [
      'main.py', '--preview', '--port', '0', '--documents', documents, '--state', state,
    ], { cwd: projectRoot, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    const url = await new Promise<string>((accept, reject) => {
      const timeout = setTimeout(() => reject(new Error('Preview startup timed out: ' + output)), 10000);
      child.stdout.on('data', chunk => {
        output += String(chunk);
        const match = output.match(/Open (http:\/\/127\.0\.0\.1:\d+\/[^\s]+\/)/);
        if (match) { clearTimeout(timeout); accept(match[1]); }
      });
      child.stderr.on('data', chunk => { output += String(chunk); });
      child.on('error', error => { clearTimeout(timeout); reject(error); });
      child.on('exit', code => { clearTimeout(timeout); reject(new Error(`Preview exited (${code}): ${output}`)); });
    });
    try {
      await use({ url, documents, state });
    } finally {
      if (child.exitCode === null) {
        await fetch(new URL('api', url), { method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Pythona-Session': new URL(url).pathname.split('/')[1] },
          body: JSON.stringify({ action: 'host.close' }),
        }).catch(() => {});
        if (child.exitCode === null) {
          const timeout = setTimeout(() => child.kill('SIGTERM'), 5000);
          await once(child, 'exit');
          clearTimeout(timeout);
        }
      }
      await rm(temporary, { recursive: true, force: true });
    }
  },
});

async function ready(page: Page) {
  await page.waitForFunction(() => (window as any).pythonaWorkbench?.ready);
}

async function command(page: Page, id: string, ...args: unknown[]) {
  return page.evaluate(([id, args]) => (window as any).pythonaWorkbench.executeCommand(id, ...args), [id, args] as const);
}

async function startPicker(page: Page) {
  await page.evaluate(() => { void (window as any).pythonaWorkbench.executeCommand('pythona.openFolder'); });
}

async function choose(page: Page, name: string) {
  await page.getByRole('option', { name: `folder ${name}`, exact: true }).click();
  await Promise.all([
    page.waitForEvent('load'),
    page.getByText('Open This Folder', { exact: true }).click(),
  ]);
  await ready(page);
}

async function shortcut(page: Page, key: string) {
  const modifier = await page.evaluate(() => navigator.userAgent.includes('Macintosh') ? 'Meta' : 'Control');
  await page.keyboard.press(`${modifier}+${key}`);
}

async function savedPreferences(host: Host) {
  return JSON.parse(await readFile(join(dirname(host.state), 'preferences.json'), 'utf8'));
}

async function recordReadiness(page: Page) {
  await page.addInitScript(() => {
    (window as any).nativeReadyMessages = [];
    (window as any).webkit = { messageHandlers: {
      workbenchReady: { postMessage: (value: string) => (window as any).nativeReadyMessages.push(value) },
    } };
  });
}

async function waitForPaints(page: Page) {
  // Keep the theme blocked through several frames, including the old early-ready path.
  await page.evaluate(async () => {
    for (let frame = 0; frame < 12; frame++) await new Promise(requestAnimationFrame);
  });
}

async function recordNativeInput(page: Page) {
  await page.addInitScript(() => {
    // Match WKWebView's textarea input path when this fixture runs in Chrome.
    (window as any).EditContext = undefined;
    (window as any).inputRequests = [];
    (window as any).webkit = { messageHandlers: {
      workbenchReady: { postMessage() {} },
      workbenchInput: { postMessage(id: string) { (window as any).inputRequests.push(id); } },
    } };
  });
}

async function inputRequests(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as any).inputRequests);
}

async function editorPoint(page: Page, index = 0) {
  const area = await page.locator('.editor-group-container .monaco-editor .view-lines').nth(index).boundingBox();
  if (!area) throw new Error('The editor is not visible');
  return { x: area.x + Math.min(area.width / 2, 130), y: area.y + 10 };
}

test('native input activation keeps the tapped editor and ignores stale callbacks', async ({ page, host }) => {
  await recordNativeInput(page);
  await page.goto(host.url);
  await ready(page);
  await startPicker(page);
  await choose(page, 'Project One');
  await command(page, '_workbench.open', { scheme: 'file', path: '/Documents/Project One/main.py' });
  await command(page, 'workbench.action.splitEditorRight');
  await expect(page.locator('.editor-group-container .monaco-editor')).toHaveCount(2);
  expect(await inputRequests(page)).toEqual([]);
  for (const index of [0, 1]) {
    const point = await editorPoint(page, index);
    await page.mouse.click(point.x, point.y);
    await expect.poll(async () => (await inputRequests(page)).length).toBe(index + 1);
  }
  const [oldRequest, latestRequest] = await inputRequests(page);
  await page.evaluate(id => (window as any).pythonaWorkbench.activateInput(id), oldRequest);
  await expect(page.locator('.editor-group-container .monaco-editor textarea.inputarea').nth(1)).toBeFocused();
  await page.evaluate(id => (window as any).pythonaWorkbench.activateInput(id), latestRequest);
  await page.keyboard.insertText('native_input');
  await command(page, 'workbench.action.files.save');
  await expect.poll(() => readFile(join(host.documents, 'Project One/main.py'), 'utf8')).toContain('native_input');
});

test('native input activation leaves dragging, long presses, and newer quick inputs alone', async ({ page, host }) => {
  await recordNativeInput(page);
  await page.goto(host.url);
  await ready(page);
  await command(page, '_workbench.open', { scheme: 'vscode-userdata', path: '/User/settings.json' });
  const point = await editorPoint(page);
  await page.mouse.move(point.x, point.y);
  await page.mouse.down();
  await page.mouse.move(point.x + 90, point.y + 20, { steps: 8 });
  await page.mouse.up();
  await page.mouse.move(point.x, point.y);
  await page.mouse.down();
  await page.waitForTimeout(550);
  await page.mouse.up();
  expect(await inputRequests(page)).toEqual([]);
  await page.mouse.click(point.x, point.y);
  await expect.poll(async () => (await inputRequests(page)).length).toBe(1);
  const [request] = await inputRequests(page);
  await command(page, 'workbench.action.showCommands');
  const input = page.locator('.quick-input-widget:visible input');
  await expect(input).toBeFocused();
  await page.evaluate(id => (window as any).pythonaWorkbench.activateInput(id), request);
  await expect(input).toBeFocused();
  await page.keyboard.insertText('Color Theme');
  await expect(input).toHaveValue('>Color Theme');
  expect(await inputRequests(page)).toHaveLength(1);
});

test('cold startup stays dark and waits for a delayed theme before native readiness', async ({ page, host }) => {
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await recordReadiness(page);
  await page.route('**/dark_modern-*.json', async route => { await held; await route.continue(); });
  try {
    const requested = page.waitForRequest('**/dark_modern-*.json');
    await page.goto(host.url);
    await requested;
    await expect(page.locator('.monaco-workbench.vs-dark')).toHaveCount(1);
    await waitForPaints(page);
    expect(await page.evaluate(() => ({
      ready: (window as any).pythonaWorkbench.ready,
      messages: (window as any).nativeReadyMessages,
      editor: getComputedStyle(document.querySelector('.monaco-workbench')!).getPropertyValue('--vscode-editor-background').trim(),
      background: getComputedStyle(document.documentElement).backgroundColor,
    }))).toEqual({ ready: false, messages: [], editor: '#1f1f1f', background: 'rgb(24, 24, 24)' });
    release();
    await ready(page);
    await expect.poll(() => page.evaluate(() => (window as any).nativeReadyMessages)).toEqual(['ready']);
  } finally {
    release();
  }
});

test('a selected light theme survives a fresh browser and delayed theme loading', async ({ page, browser, host }) => {
  await page.goto(host.url);
  await ready(page);
  await page.evaluate(() => { void (window as any).pythonaWorkbench.executeCommand('workbench.action.selectTheme'); });
  await page.locator('.quick-input-widget:visible input').fill('Light Modern');
  await page.locator('.quick-input-list').getByText('Light Modern', { exact: true }).click();
  await expect.poll(async () => (await savedPreferences(host)).theme.name).toBe('Light Modern');
  expect((await savedPreferences(host)).settings).toContain('Light Modern');

  const firstPaint = await browser.newPage({ javaScriptEnabled: false });
  try {
    await firstPaint.goto(host.url);
    expect(await firstPaint.evaluate(() => ['html', 'body', '#startup'].map(selector =>
      getComputedStyle(document.querySelector(selector)!).backgroundColor)))
      .toEqual(['rgb(248, 248, 248)', 'rgb(248, 248, 248)', 'rgb(248, 248, 248)']);
  } finally {
    await firstPaint.close();
  }

  const fresh = await browser.newPage();
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  try {
    await recordReadiness(fresh);
    await fresh.route('**/light_modern-*.json', async route => { await held; await route.continue(); });
    const requested = fresh.waitForRequest('**/light_modern-*.json');
    await fresh.goto(host.url);
    await requested;
    await expect(fresh.locator('.monaco-workbench.vs')).toHaveCount(1);
    await waitForPaints(fresh);
    expect(await fresh.evaluate(() => ({ ready: (window as any).pythonaWorkbench.ready,
      messages: (window as any).nativeReadyMessages,
      background: getComputedStyle(document.documentElement).backgroundColor,
    }))).toEqual({ ready: false, messages: [], background: 'rgb(248, 248, 248)' });
    release();
    await ready(fresh);
    await expect(fresh.locator('.monaco-workbench.vs')).toHaveCount(1);
    await expect.poll(() => fresh.evaluate(() => (window as any).nativeReadyMessages)).toEqual(['ready']);
  } finally {
    release();
    await fresh.close();
  }
});

test('previewing and cancelling a theme does not replace the saved startup colors', async ({ page, host }) => {
  await page.goto(host.url);
  await ready(page);
  await page.evaluate(() => { void (window as any).pythonaWorkbench.executeCommand('workbench.action.selectTheme'); });
  await page.locator('.quick-input-widget:visible input').fill('Light Modern');
  await expect(page.locator('.monaco-workbench.vs')).toHaveCount(1);
  expect((await savedPreferences(host)).theme.type).toBe('dark');
  await page.keyboard.press('Escape');
  await expect(page.locator('.monaco-workbench.vs-dark')).toHaveCount(1);
  expect((await savedPreferences(host)).theme.type).toBe('dark');
});

test('user settings and custom startup colors are not overwritten on reload', async ({ page, host }) => {
  await page.goto(host.url);
  await ready(page);
  await command(page, '_workbench.open', { scheme: 'vscode-userdata', path: '/User/settings.json' });
  await page.locator('.monaco-editor .view-lines').click();
  await shortcut(page, 'a');
  const settings = '// Keep this comment\n{\n  "workbench.colorTheme": "Light Modern",\n'
    + '  "editor.fontSize": 19,\n  "workbench.colorCustomizations": {"sideBar.background": "#f2f4f8"},\n}\n';
  await page.keyboard.insertText(settings);
  await command(page, 'workbench.action.files.save');
  await expect.poll(async () => (await savedPreferences(host)).theme.colors['sideBar.background']).toBe('#f2f4f8');
  const saved = (await savedPreferences(host)).settings;
  // The editor may auto-indent typed JSON; persistence must retain the edited text.
  const lines = (text: string) => text.split(/\r?\n/).map(line => line.trim()).join('\n');
  expect(lines(saved)).toBe(lines(settings));
  await page.reload();
  await ready(page);
  await expect(page.locator('.monaco-workbench.vs')).toHaveCount(1);
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor)).toBe('rgb(242, 244, 248)');
  expect((await savedPreferences(host)).settings).toBe(saved);
});

test('foreground recovery keeps dirty editors and resumes opening and saving files', async ({ page, host }) => {
  await page.goto(host.url);
  await ready(page);
  await startPicker(page);
  await choose(page, 'Project One');
  await page.getByText('main.py', { exact: true }).dblclick();
  await command(page, 'cursorBottom');
  await command(page, 'type', { text: '# kept across background\n' });
  const documentID = await page.evaluate(() => ((window as any).resumeDocument = crypto.randomUUID()));
  let offline = true;
  let checks = 0;
  await page.route('**/health', async route => {
    checks++;
    if (offline) await route.fulfill({ status: 503, body: '' });
    else await route.continue();
  });
  await page.route('**/api', route => offline ? route.abort('failed') : route.continue());
  await page.evaluate(() => {
    window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }));
    (window as any).pythonaConnection.resume();
    void (window as any).pythonaWorkbench.executeCommand('_workbench.open', {
      scheme: 'file', path: '/Documents/Project One/src/你好 🐍.py',
    });
  });
  await expect.poll(() => checks).toBeGreaterThan(0);
  offline = false;
  await expect(page.locator('.tabs-container')).toContainText('你好 🐍.py');
  await command(page, '_workbench.open', { scheme: 'file', path: '/Documents/Project One/main.py' });
  await command(page, 'workbench.action.files.save');
  await expect.poll(() => readFile(join(host.documents, 'Project One/main.py'), 'utf8')).toContain('# kept across background');
  expect(await page.evaluate(() => (window as any).resumeDocument)).toBe(documentID);
});

test('a lost save reply is not blindly replayed after reconnection', async ({ page, host }) => {
  await page.goto(host.url);
  await ready(page);
  await startPicker(page);
  await choose(page, 'Project One');
  await page.getByText('main.py', { exact: true }).dblclick();
  await command(page, 'cursorBottom');
  await command(page, 'type', { text: '# save reply lost\n' });
  let writes = 0;
  await page.route('**/api', async route => {
    if (route.request().postDataJSON()?.action !== 'fs.write') return route.continue();
    writes++;
    await route.fetch();
    await route.abort('failed');
  });
  await command(page, 'workbench.action.files.save').catch(() => {});
  await expect(page.locator('.notifications-toasts')).toContainText('Failed to save');
  expect(await readFile(join(host.documents, 'Project One/main.py'), 'utf8')).toContain('# save reply lost');
  expect(writes).toBe(1);
  await page.evaluate(() => { void (window as any).pythonaWorkbench.requestClose(); });
  await expect(page.getByText('Save your changes before leaving this workspace?')).toBeVisible();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
});

test('opens a selected workspace, edits Unicode, saves, and restores it', async ({ page, host }) => {
  const errors: string[] = [];
  const external: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    if (!route.request().url().startsWith(new URL(host.url).origin)) {
      external.push(route.request().url());
      return route.abort();
    }
    return route.continue();
  });
  await page.goto(host.url);
  await ready(page);
  await expect(page.getByText('You have not yet opened a folder.')).toBeVisible();
  await expect(page.getByText('main.py', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Open Folder', exact: true }).click();
  await choose(page, 'Project One');
  await expect(page.getByText('Other Project', { exact: true })).toHaveCount(0);
  await page.getByText('main.py', { exact: true }).dblclick();
  await page.locator('.monaco-editor .view-lines').click();
  await shortcut(page, 'a');
  await page.keyboard.insertText('print("edited 你好 🐍")\n');
  await shortcut(page, 's');
  await expect.poll(() => readFile(join(host.documents, 'Project One/main.py'), 'utf8')).toBe('print("edited 你好 🐍")\n');
  await command(page, 'workbench.action.splitEditorRight');
  await expect(page.locator('.editor-group-container')).toHaveCount(2);
  await expect.poll(async () => JSON.parse(await readFile(host.state, 'utf8')).workspace).toBe('Project One');
  await page.reload();
  await ready(page);
  await expect(page.locator('.explorer-viewlet')).toContainText('main.py');
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
});

test('cancel keeps dirty edits; saving before switching writes the original workspace', async ({ page, host }) => {
  await page.goto(host.url);
  await ready(page);
  await startPicker(page);
  await choose(page, 'Project One');
  await page.getByText('main.py', { exact: true }).dblclick();
  await command(page, 'cursorBottom');
  await command(page, 'type', { text: '# unsaved edit\n' });
  await startPicker(page);
  await page.getByRole('option', { name: 'folder Other Project', exact: true }).click();
  await page.getByText('Open This Folder', { exact: true }).click();
  await expect(page.getByText('Save your changes before leaving this workspace?')).toBeVisible();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.locator('.explorer-viewlet')).toContainText('main.py');
  expect(await readFile(join(host.documents, 'Project One/main.py'), 'utf8')).not.toContain('unsaved edit');
  await startPicker(page);
  await page.getByRole('option', { name: 'folder Other Project', exact: true }).click();
  await page.getByText('Open This Folder', { exact: true }).click();
  await Promise.all([page.waitForEvent('load'), page.getByRole('button', { name: 'Save All', exact: true }).click()]);
  await ready(page);
  await expect(page.locator('.explorer-viewlet')).toContainText('other.py');
  expect(await readFile(join(host.documents, 'Project One/main.py'), 'utf8')).toContain('# unsaved edit');
  expect(await readFile(join(host.documents, 'Other Project/other.py'), 'utf8')).toBe('# other workspace\n');
});

test('quick open and workspace text search include unopened nested files', async ({ page, host }) => {
  await page.goto(host.url);
  await ready(page);
  await startPicker(page);
  await choose(page, 'Project One');
  await shortcut(page, 'p');
  await page.locator('.quick-input-widget input').fill('你好');
  await expect(page.locator('.quick-input-list')).toContainText('你好 🐍.py');
  await page.keyboard.press('Enter');
  await expect(page.locator('.tabs-container')).toContainText('你好 🐍.py');
  await command(page, 'workbench.action.findInFiles', { query: 'needle in nested file', triggerSearch: true });
  await expect(page.locator('.search-view')).toContainText('你好 🐍.py');
});

test('closing a dirty workspace offers discard and returns to an empty workbench', async ({ page, host }) => {
  await page.goto(host.url);
  await ready(page);
  await startPicker(page);
  await choose(page, 'Project One');
  await page.getByText('main.py', { exact: true }).dblclick();
  await command(page, 'type', { text: '# discard this\n' });
  await page.evaluate(() => { void (window as any).pythonaWorkbench.executeCommand('pythona.closeFolder'); });
  await Promise.all([page.waitForEvent('load'), page.getByRole('button', { name: "Don't Save", exact: true }).click()]);
  await ready(page);
  await expect(page.getByText('You have not yet opened a folder.')).toBeVisible();
  expect(await readFile(join(host.documents, 'Project One/main.py'), 'utf8')).not.toContain('discard this');
  expect(JSON.parse(await readFile(host.state, 'utf8')).workspace).toBeNull();
});

test('the first HTML paint is dark before JavaScript or the workbench loads', async ({ browser, host }) => {
  const page = await browser.newPage({ javaScriptEnabled: false, viewport: { width: 1194, height: 834 } });
  try {
    await page.goto(host.url);
    const colors = await page.evaluate(() => ({
      html: getComputedStyle(document.documentElement).backgroundColor,
      body: getComputedStyle(document.body).backgroundColor,
      startup: getComputedStyle(document.querySelector('#startup')!).backgroundColor,
    }));
    expect(colors).toEqual({ html: 'rgb(24, 24, 24)', body: 'rgb(24, 24, 24)', startup: 'rgb(24, 24, 24)' });
  } finally {
    await page.close();
  }
});

test('a new untitled file saves into the selected project through Save As', async ({ page, host }) => {
  await page.goto(host.url);
  await ready(page);
  await startPicker(page);
  await choose(page, 'Project One');
  await command(page, 'workbench.action.files.newUntitledFile');
  await command(page, 'type', { text: 'print("new file 你好")\n' });
  await page.evaluate(() => { void (window as any).pythonaWorkbench.executeCommand('workbench.action.files.save'); });
  const input = page.locator('.quick-input-widget:visible input');
  await expect(input).toBeVisible();
  await input.fill('/Documents/Project One/created.py');
  await page.keyboard.press('Enter');
  await expect.poll(() => readFile(join(host.documents, 'Project One/created.py'), 'utf8')
    .catch(error => error.code === 'ENOENT' ? null : Promise.reject(error))).toMatch(/^print\("new file 你好"\)\r?\n$/);
  await expect(page.locator('.explorer-viewlet')).toContainText('created.py');
});

test('File and Edit popups accept taps over an open editor', async ({ browser, host }) => {
  const page = await browser.newPage({
    viewport: { width: 1210, height: 782 },
    screen: { width: 1210, height: 834 },
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)',
    hasTouch: true,
  });

  try {
    await page.goto(host.url);
    await ready(page);
    await startPicker(page);
    await choose(page, 'Project One');
    await page.getByText('main.py', { exact: true }).dblclick();
    await command(page, 'cursorBottom');
    await command(page, 'type', { text: '# saved from the menu\n' });

    // WKWebView can keep the titlebar inactive while the user taps its menus.
    await page.locator('.part.titlebar').evaluate(element => element.classList.add('inactive'));

    const menu = page.locator('.menubar-menu-items-holder');
    await page.getByRole('menuitem', { name: 'File', exact: true }).tap();
    await menu.getByText('Save', { exact: true }).tap();
    await expect.poll(() => readFile(join(host.documents, 'Project One/main.py'), 'utf8'))
      .toContain('# saved from the menu');

    await page.getByRole('menuitem', { name: 'Edit', exact: true }).tap();
    await menu.getByText('Find', { exact: true }).tap();
    await expect(page.locator('.find-widget').getByRole('textbox', { name: 'Find', exact: true })).toBeVisible();
    await page.keyboard.press('Escape');

    await page.getByRole('menuitem', { name: 'View', exact: true }).tap();
    await menu.getByText('Editor Layout', { exact: true }).tap();
    await menu.getByText('Split Right', { exact: true }).tap();
    await expect(page.locator('.editor-group-container')).toHaveCount(2);

    await page.getByRole('menuitem', { name: 'Go', exact: true }).tap();
    const goToFile = menu.getByRole('menuitem', { name: /^Go to File/ });
    expect(await goToFile.evaluate(item => {
      const rect = item.getBoundingClientRect();
      return item.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
    })).toBe(true);
    await page.keyboard.press('Escape');
    await shortcut(page, 'p');
    await page.locator('.quick-input-widget input').fill('main.py');
    await expect(page.locator('.quick-input-list')).toContainText('main.py');
  } finally {
    await page.close();
  }
});
