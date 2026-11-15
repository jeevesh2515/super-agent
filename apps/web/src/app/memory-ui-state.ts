/**
 * Memory screen state logic, kept free of Angular so the self-tests can run it.
 * Everything from the backend is untrusted input: parsed strictly, bounded, and
 * shown as text only.
 */

export interface MemoryItem {
  kind: 'fact' | 'reminder';
  id: number;
  text: string;
  createdAt: string;
  fromUser: boolean;
  dueAt?: string;
  repeat?: string | null;
}

export interface MemoryView {
  enabled: boolean;
  paused: boolean;
  undoable: number;
  items: readonly MemoryItem[];
}

export interface MemoryResult {
  op: string;
  ok: boolean;
  error: string;
}

/** The store holds at most 150 facts and 200 open reminders; the page bounds what it will keep. */
export const MAX_MEMORY_ITEMS = 350;
export const MAX_ITEM_CHARS = 240;
export const MAX_QUERY_CHARS = 100;
/** A search needs three characters, as the backend's recall does. */
export const MIN_QUERY_CHARS = 3;

const OPS = new Set(['list', 'edit', 'forget', 'undo', 'pause']);
const ERROR_TEXT: Record<string, string> = {
  'memory-off': 'Memory is off.',
  'bad-text': `A fact must be 1 to ${MAX_ITEM_CHARS} characters.`,
  secret: 'That looks like a secret, so it was not saved.',
  duplicate: 'That fact is already remembered.',
  'not-found': 'That item is already gone. The list was refreshed.',
  'nothing-to-restore': 'There is nothing to restore.',
  full: 'Memory is full. Forget something first.',
  failed: 'That did not work. Nothing was changed.',
};

const isId = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
const isText = (value: unknown, max: number): value is string =>
  typeof value === 'string' && value.length > 0 && value.length <= max;

function parseItem(raw: unknown): MemoryItem | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const item = raw as Record<string, unknown>;
  if ((item['kind'] !== 'fact' && item['kind'] !== 'reminder') || !isId(item['id'])
    || !isText(item['text'], MAX_ITEM_CHARS) || typeof item['createdAt'] !== 'string'
    || typeof item['fromUser'] !== 'boolean') return null;
  const parsed: MemoryItem = {
    kind: item['kind'], id: item['id'], text: item['text'],
    createdAt: item['createdAt'].slice(0, 40), fromUser: item['fromUser'],
  };
  if (item['kind'] === 'reminder') {
    if (typeof item['dueAt'] !== 'string') return null;
    parsed.dueAt = item['dueAt'].slice(0, 40);
    parsed.repeat = typeof item['repeat'] === 'string' ? item['repeat'].slice(0, 20) : null;
  }
  return parsed;
}

/** A `memory.items` message as a view, or null if any part of it is not what the backend sends. */
export function parseMemoryItems(message: { enabled?: unknown; paused?: unknown; undoable?: unknown; items?: unknown }): MemoryView | null {
  const { enabled, paused, undoable, items } = message;
  if (typeof enabled !== 'boolean' || typeof paused !== 'boolean' || !Array.isArray(items)
    || items.length > MAX_MEMORY_ITEMS || typeof undoable !== 'number'
    || !Number.isInteger(undoable) || undoable < 0 || undoable > MAX_MEMORY_ITEMS) return null;
  const parsed = items.map(parseItem);
  if (parsed.some((item) => item === null)) return null;
  return { enabled, paused, undoable, items: parsed as MemoryItem[] };
}

/** A `memory.result` message, or null. The error is kept only if it is one of the backend's fixed codes. */
export function parseMemoryResult(message: { op?: unknown; ok?: unknown; error?: unknown }): MemoryResult | null {
  const { op, ok, error } = message;
  if (typeof op !== 'string' || !OPS.has(op) || typeof ok !== 'boolean') return null;
  return { op, ok, error: ok ? '' : typeof error === 'string' && error in ERROR_TEXT ? error : 'failed' };
}

/** Fixed wording for a backend error code; nothing the backend sent is shown verbatim. */
export function memoryErrorText(code: string): string {
  return ERROR_TEXT[code] ?? ERROR_TEXT['failed'];
}

/**
 * What to ask the backend for: no filter unless the text holds a word of at least three characters,
 * the same rule the backend's recall uses, so "a b c" lists everything on both sides.
 */
export function searchQuery(typed: string): string {
  const trimmed = typed.trim().slice(0, MAX_QUERY_CHARS);
  return new RegExp(`[\\p{L}\\p{N}_]{${MIN_QUERY_CHARS},}`, 'u').test(trimmed) ? trimmed : '';
}

/** The text to send for an edit, or null if it is empty, unchanged or too long. */
export function editedText(typed: string, current: string): string | null {
  const text = typed.trim().replace(/\s+/g, ' ');
  return text.length > 0 && text.length <= MAX_ITEM_CHARS && text !== current ? text : null;
}

const DATE = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
const DATE_TIME = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
});

function formatted(iso: string, format: Intl.DateTimeFormat): string {
  const time = new Date(iso);
  return Number.isNaN(time.getTime()) ? '' : format.format(time);
}

/** One plain line under an item: where it came from, when it was saved, and when a reminder is due. */
export function itemMeta(item: MemoryItem): string {
  const parts = [item.fromUser ? 'Saved from your words' : 'Origin not recorded'];
  const saved = formatted(item.createdAt, DATE);
  if (saved) parts.push(`saved ${saved}`);
  const due = item.dueAt ? formatted(item.dueAt, DATE_TIME) : '';
  if (due) parts.push(`due ${due}${item.repeat ? ' (repeats)' : ''}`);
  return parts.join(' · ');
}

export function memorySummary(view: MemoryView | null, searching: boolean): string {
  if (!view) return 'Loading memory.';
  if (!view.enabled) return 'Memory is off.';
  const count = view.items.length;
  if (count === 0) return searching ? 'Nothing matches that search.' : 'Nothing is remembered yet.';
  return `${count} ${count === 1 ? 'item' : 'items'}${searching ? ' match' : ''}.`;
}
