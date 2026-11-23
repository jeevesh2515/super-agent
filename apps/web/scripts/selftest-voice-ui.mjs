import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const base = path.join(os.tmpdir(), 'opencode');
await mkdir(base, { recursive: true });
const workdir = await mkdtemp(path.join(base, 'voice-ui-'));
const require = createRequire(import.meta.url);
async function load(file) {
  const sourcePath = fileURLToPath(new URL(`../src/app/${file}.ts`, import.meta.url));
  const { outputText } = ts.transpileModule(await readFile(sourcePath, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  });
  const compiled = path.join(workdir, `${file}.cjs`);
  await writeFile(compiled, outputText);
  return require(compiled);
}
const ui = await load('voice-ui-state');
const mem = await load('memory-ui-state');
await rm(workdir, { recursive: true, force: true });

let cases = 0;
function equal(actual, expected) {
  assert.equal(actual, expected);
  cases += 1;
}

equal(ui.statusLabel('stopped'), 'Disconnected');
equal(ui.statusLabel('connecting'), 'Connecting');
equal(ui.statusLabel('listening'), 'Listening');
equal(ui.statusLabel('speaking'), 'Local echo');
equal(ui.statusLabel('speaking', 'local'), 'Speaking');
equal(ui.statusLabel('listening', 'local'), 'Listening');
equal(ui.pipelineSummary('speaking', 'local'), 'Playing the local reply');
equal(ui.pipelineSummary('speaking', 'fake'), 'Playing the local echo');
equal(ui.statusLabel('muted'), 'Muted');
equal(ui.statusLabel('error'), 'Needs attention');
equal(ui.statusLabel('thinking'), 'Thinking');
equal(ui.statusLabel('unexpected'), 'Unavailable');
equal(ui.pipelineSummary('stopped'), 'Ready for a local session');
equal(ui.pipelineSummary('connecting'), 'Authenticating on loopback');
equal(ui.pipelineSummary('speaking'), 'Playing the local echo');
equal(ui.pipelineSummary('unexpected'), 'Local voice path');
equal(ui.isSessionActive('stopped'), false);
equal(ui.isSessionActive('error'), false);
equal(ui.isSessionActive('connecting'), true);
equal(ui.isSessionActive('listening'), true);
equal(ui.isSessionReady('connecting'), false);
equal(ui.isSessionReady('muted'), true);
equal(ui.isSessionReady('thinking'), true);
equal(ui.isSessionActive('thinking'), true);
equal(ui.pipelineSummary('thinking'), 'Working on a reply locally');
equal(ui.formatElapsed(0), '00:00.0');
equal(ui.formatElapsed(61_234), '01:01.2');
equal(ui.spectrumBarHeight('stopped', 1, 0.5), 9.5);
equal(ui.spectrumBarHeight('connecting', 0, 0.5), 18);
equal(ui.spectrumBarHeight('speaking', 0, 0.5), 57);
equal(ui.spectrumBarHeight('listening', 0, 0.5), 8);
equal(ui.spectrumBarHeight('listening', 1, 0.5), 50);

equal(ui.statusLabel('speaking', 'gemini-live'), 'Speaking');
equal(ui.pipelineSummary('speaking', 'gemini-live'), 'Playing the Gemini reply');
equal(ui.pipelineSummary('listening', 'gemini-live'), 'Microphone streaming to Gemini (cloud)');
equal(ui.pipelineSummary('thinking', 'gemini-live'), 'Waiting for the Gemini (cloud) reply');
equal(ui.pipelineSummary('listening', 'fake'), 'Microphone streaming locally');
equal(ui.pipelineSummary('listening', 'local'), 'Microphone streaming locally');
equal(ui.pipelineSummary('muted', 'gemini-live'), 'Microphone transmission paused');
equal(ui.providerCopy('fake').badge, 'Fake echo adapter');
equal(ui.providerCopy('local').privacy, 'Local model active. Microphone audio stays local.');
equal(ui.providerCopy('gemini-live').tag, 'Cloud');
equal(ui.providerCopy('gemini-live').badge, 'Gemini Live (cloud)');
for (const p of ['gemini-live', '', 'unknown']) {
  const text = JSON.stringify(ui.providerCopy(p)).toLowerCase();
  equal(text.includes('stays local') || text.includes('stays on this device'), false);
  equal(text.includes('local only'), false);
}
for (const p of ['', 'unknown']) equal(JSON.stringify(ui.providerCopy(p)).toLowerCase().includes('fake'), false);
equal(ui.providerCopy('').badge, 'Not connected');

// Memory screen state logic.
const item = (over = {}) => ({ kind: 'fact', id: 3, text: 'my sister is Asha', createdAt: '2026-11-14T09:30:00+00:00', fromUser: true, ...over });
const listMsg = (over = {}) => ({ enabled: true, paused: false, undoable: 0, items: [item()], ...over });
const view = mem.parseMemoryItems(listMsg());
equal(view.items.length, 1);
equal(view.items[0].text, 'my sister is Asha');
equal(view.paused, false);
equal(mem.parseMemoryItems(listMsg({ enabled: false, items: [] })).enabled, false);
const reminder = item({ kind: 'reminder', id: 4, text: 'call home', dueAt: '2026-11-15T10:00:00+00:00', repeat: 'daily' });
equal(mem.parseMemoryItems(listMsg({ items: [reminder] })).items[0].repeat, 'daily');
equal(mem.parseMemoryItems(listMsg({ items: [{ ...reminder, repeat: null }] })).items[0].repeat, null);
equal(mem.parseMemoryItems(listMsg({ items: [item({ editUndoable: true })] })).items[0].editUndoable, true);
equal(mem.parseMemoryItems(listMsg()).items[0].editUndoable, undefined);
// Anything the backend would never send is refused whole, not partly shown.
for (const bad of [
  listMsg({ enabled: 'yes' }), listMsg({ paused: 1 }), listMsg({ undoable: -1 }), listMsg({ undoable: 1.5 }),
  listMsg({ undoable: 'x' }), listMsg({ items: 'nope' }), listMsg({ items: null }), listMsg({ items: [null] }),
  listMsg({ items: ['text'] }), listMsg({ items: [item({ kind: 'note' })] }), listMsg({ items: [item({ id: '3' })] }),
  listMsg({ items: [item({ id: 0 })] }), listMsg({ items: [item({ id: 1.5 })] }), listMsg({ items: [item({ text: '' })] }),
  listMsg({ items: [item({ text: 'x'.repeat(241) })] }), listMsg({ items: [item({ text: 5 })] }),
  listMsg({ items: [item({ fromUser: 'true' })] }), listMsg({ items: [item({ createdAt: 5 })] }),
  listMsg({ items: [item({ kind: 'reminder' })] }),
  listMsg({ items: [item({ editUndoable: false })] }), listMsg({ items: [item({ editUndoable: 'yes' })] }),
  listMsg({ items: [{ ...reminder, editUndoable: true }] }),
  listMsg({ items: Array.from({ length: 351 }, (_, i) => item({ id: i + 1 })) }),
  {}, { enabled: true },
]) equal(mem.parseMemoryItems(bad), null);
equal(mem.parseMemoryItems(listMsg({ items: Array.from({ length: 350 }, (_, i) => item({ id: i + 1 })) })).items.length, 350);
// Text stays text: markup in an item is kept as the characters it is, for the template to escape.
equal(mem.parseMemoryItems(listMsg({ items: [item({ text: '<img src=x onerror=alert(1)>' })] })).items[0].text, '<img src=x onerror=alert(1)>');

equal(JSON.stringify(mem.parseMemoryResult({ op: 'edit', ok: true })), '{"op":"edit","ok":true,"error":""}');
equal(mem.parseMemoryResult({ op: 'edit', ok: false, error: 'secret' }).error, 'secret');
equal(mem.parseMemoryResult({ op: 'edit', ok: false, error: 'something <b>new</b>' }).error, 'failed');
equal(mem.parseMemoryResult({ op: 'edit', ok: false }).error, 'failed');
equal(mem.parseMemoryResult({ op: 'undo_edit', ok: false, error: 'nothing-to-restore' }).error, 'nothing-to-restore');
equal(mem.parseMemoryResult({ op: 'delete', ok: true }), null);
equal(mem.parseMemoryResult({ op: 'edit', ok: 'yes' }), null);
equal(mem.parseMemoryResult({ ok: true }), null);
equal(mem.memoryErrorText('memory-off'), 'Memory is off.');
equal(mem.memoryErrorText('secret'), 'That looks like a secret, so it was not saved.');
equal(mem.memoryErrorText('anything else'), 'That did not work. Nothing was changed.');

equal(mem.searchQuery(''), '');
equal(mem.searchQuery('  si '), '');
equal(mem.searchQuery(' sis '), 'sis');
equal(mem.searchQuery('a b c'), '', 'no word of 3 characters is no search, as in the backend');
equal(mem.searchQuery('- - -'), '');
equal(mem.searchQuery('a bcd'), 'a bcd');
equal(mem.searchQuery('caf\u00e9'), 'caf\u00e9');
equal(mem.searchQuery('x'.repeat(150)).length, 100);
equal(mem.editedText('  a   new  fact ', 'old'), 'a new fact');
equal(mem.editedText('same', 'same'), null);
equal(mem.editedText('   ', 'old'), null);
equal(mem.editedText('x'.repeat(241), 'old'), null);
equal(mem.editedText('x'.repeat(240), 'old').length, 240);

equal(mem.itemMeta(item()).startsWith('You asked to save this · saved '), true);
equal(mem.itemMeta(item({ fromUser: false })).startsWith('No request recorded'), true);
equal(mem.itemMeta(item({ createdAt: 'garbage' })), 'You asked to save this');
equal(mem.itemMeta(reminder).includes('due '), true);
equal(mem.itemMeta(reminder).endsWith('(repeats)'), true);
equal(mem.memorySummary(null, false), 'Loading memory.');
equal(mem.memorySummary(mem.parseMemoryItems(listMsg({ enabled: false, items: [] })), false), 'Memory is off.');
equal(mem.memorySummary(mem.parseMemoryItems(listMsg({ items: [] })), false), 'Nothing is remembered yet.');
equal(mem.memorySummary(mem.parseMemoryItems(listMsg({ items: [] })), true), 'Nothing matches that search.');
equal(mem.memorySummary(view, false), '1 item.');
equal(mem.memorySummary(mem.parseMemoryItems(listMsg({ items: [item(), item({ id: 5 })] })), true), '2 items match.');

console.log(`voice-ui state self-test: PASS (${cases} cases)`);
