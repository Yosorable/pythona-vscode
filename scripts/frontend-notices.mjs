import { readFile, writeFile, readdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'frontend');
const lock = JSON.parse(await readFile(join(root, 'package-lock.json'), 'utf8'));
const notices = ['Pythona VSCode — bundled frontend notices\n\nThird-party software retains its original license and copyright.\n'];
for (const name of ['monaco-vscode-api.txt', 'vscode.txt', 'vscode-third-party.txt']) {
  notices.push(`\n${'='.repeat(72)}\n${name}\n\n${await readFile(join(root, '..', 'licenses', name), 'utf8')}\n`);
}
for (const [path, entry] of Object.entries(lock.packages)) {
  if (!path || entry.dev) continue;
  const folder = join(root, path);
  const names = (await readdir(folder)).filter(name => /^(licen[cs]e|copying|thirdpartynotices|notice)(\.|$)/i.test(name));
  notices.push(`\n${'='.repeat(72)}\n${path.replace(/^node_modules\//, '')} ${entry.version}\nLicense: ${entry.license ?? 'See below'}\n`);
  for (const name of names) {
    notices.push(`\n--- ${name} ---\n${await readFile(join(folder, name), 'utf8')}\n`);
  }
}
await writeFile(join(root, 'THIRD_PARTY_NOTICES.txt'), notices.join(''));
