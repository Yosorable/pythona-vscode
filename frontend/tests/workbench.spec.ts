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
