import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  ViewChild,
  afterRenderEffect,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { VoiceSessionService } from './voice-session.service';
import {
  MAX_ITEM_CHARS,
  MAX_QUERY_CHARS,
  MemoryItem,
  editedText,
  itemMeta,
  memorySummary,
  searchQuery,
} from './memory-ui-state';
import {
  formatElapsed,
  isSessionActive,
  isSessionReady,
  providerCopy,
  pipelineSummary,
  spectrumBarHeight,
  statusLabel,
} from './voice-ui-state';

@Component({
  selector: 'app-root',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnDestroy {
  @ViewChild('settingsButton') private settingsButton?: ElementRef<HTMLButtonElement>;
  @ViewChild('settingsPanel') private settingsPanel?: ElementRef<HTMLElement>;
  @ViewChild('tokenInput') private tokenInput?: ElementRef<HTMLInputElement>;
  @ViewChild('transcript') private transcript?: ElementRef<HTMLElement>;
  @ViewChild('denyButton') private denyButton?: ElementRef<HTMLButtonElement>;
  @ViewChild('memoryButton') private memoryButton?: ElementRef<HTMLButtonElement>;
  @ViewChild('memoryPanel') private memoryPanel?: ElementRef<HTMLElement>;
  @ViewChild('memoryClose') private memoryClose?: ElementRef<HTMLButtonElement>;
  @ViewChild('memorySearch') private memorySearch?: ElementRef<HTMLInputElement>;

  readonly session = inject(VoiceSessionService);
  readonly settingsOpen = signal(false);
  readonly memoryOpen = signal(false);
  readonly searchText = signal('');
  /** The one fact being edited, and the text typed so far. */
  readonly editing = signal<{ kind: string; id: number } | null>(null);
  readonly editText = signal('');
  readonly maxItemChars = MAX_ITEM_CHARS;
  readonly maxQueryChars = MAX_QUERY_CHARS;
  readonly elapsedMs = signal(0);
  readonly bars = Array.from({ length: 40 }, (_, index) => {
    const center = Math.sin(((index + 1) / 41) * Math.PI);
    return 0.35 + center * (0.5 + ((index * 17) % 7) / 35);
  });
  readonly visualState = computed(() => this.session.status() === 'stopped'
    ? 'disconnected'
    : this.session.status());
  readonly copy = computed(() => providerCopy(this.session.provider()));
  readonly statusLabel = computed(() => statusLabel(this.session.status(), this.session.provider()));
  readonly isSessionActive = computed(() => isSessionActive(this.session.status()));
  readonly isSessionReady = computed(() => isSessionReady(this.session.status()));
  readonly canControlSession = computed(() => this.isSessionReady());
  readonly pipelineSummary = computed(() => pipelineSummary(this.session.status(), this.session.provider()));
  readonly memorySummary = computed(() => memorySummary(this.session.memory(), searchQuery(this.searchText()) !== ''));

  // Keeps the newest line in view; reads the signal so it reruns per entry.
  private readonly followTranscript = afterRenderEffect(() => {
    this.session.conversation();
    const el = this.transcript?.nativeElement;
    if (el) el.scrollTop = el.scrollHeight;
  });

  // An edit stays open, with its text, until the backend accepts it; a refusal shows next to it.
  private seenEdits = 0;
  private readonly closeAcceptedEdit = effect(() => {
    const applied = this.session.editsApplied();
    if (applied === this.seenEdits) return;
    this.seenEdits = applied;
    untracked(() => {
      const editing = this.editing();
      if (editing) this.cancelEdit(editing);
    });
  });

  // Keeps focus inside the memory panel: on open, and when a forgotten row takes the focused button with it.
  private readonly focusMemoryPanel = afterRenderEffect(() => {
    if (!this.memoryOpen()) return;
    this.session.memory();
    const panel = this.memoryPanel?.nativeElement;
    if (panel && !panel.contains(document.activeElement)) (this.memorySearch ?? this.memoryClose)?.nativeElement.focus();
  });

  // Deny is focused first, so a stray Enter or Space never approves.
  private readonly focusActionCard = afterRenderEffect(() => {
    if (this.session.pendingAction()) this.denyButton?.nativeElement.focus();
  });

  token = '';
  private sessionStartedAt = 0;
  private searchTimer?: number;
  private readonly timer = window.setInterval(() => {
    if (!this.isSessionActive()) {
      this.sessionStartedAt = 0;
      this.elapsedMs.set(0);
      return;
    }
    if (!this.sessionStartedAt) this.sessionStartedAt = performance.now();
    this.elapsedMs.set(performance.now() - this.sessionStartedAt);
  }, 100);

  ngOnDestroy(): void {
    window.clearInterval(this.timer);
    window.clearTimeout(this.searchTimer);
  }

  openMemory(): void {
    this.memoryOpen.set(true);
    this.session.listMemory(this.searchText());
  }

  closeMemory(): void {
    if (!this.memoryOpen()) return;
    this.session.clearMemoryError();
    window.clearTimeout(this.searchTimer);
    this.cancelEdit();
    this.searchText.set('');
    this.memoryOpen.set(false);
    window.setTimeout(() => this.memoryButton?.nativeElement.focus());
  }

  closeMemoryFromBackdrop(event: MouseEvent): void {
    if (event.target === event.currentTarget) this.closeMemory();
  }

  onMemoryKeydown(event: KeyboardEvent): void {
    this.trapFocus(event, this.memoryPanel?.nativeElement);
  }

  /** Waits for a pause in typing, so each keystroke does not ask the backend. */
  onMemorySearch(value: string): void {
    this.searchText.set(value);
    window.clearTimeout(this.searchTimer);
    this.searchTimer = window.setTimeout(() => this.session.listMemory(value), 200);
  }

  isEditing(item: MemoryItem): boolean {
    const editing = this.editing();
    return editing?.kind === item.kind && editing.id === item.id;
  }

  startEdit(item: MemoryItem): void {
    this.session.clearMemoryError();
    this.editing.set({ kind: item.kind, id: item.id });
    this.editText.set(item.text);
    window.setTimeout(() => this.memoryPanel?.nativeElement.querySelector<HTMLInputElement>('.memory-edit')?.focus());
  }

  canSave(item: MemoryItem): boolean {
    return editedText(this.editText(), item.text) !== null;
  }

  saveEdit(item: MemoryItem): void {
    const text = editedText(this.editText(), item.text);
    if (text === null) return;
    this.session.editMemory(item.id, text);
  }

  /** Esc stops here, so it leaves the edit and not the whole panel. */
  cancelEdit(item?: { id: number }, event?: Event): void {
    event?.stopPropagation();
    this.editing.set(null);
    if (item) window.setTimeout(() => this.memoryPanel?.nativeElement.querySelector<HTMLElement>(`[data-edit="${item.id}"]`)?.focus());
  }

  undoEdit(item: MemoryItem): void {
    this.session.undoEditMemory(item.id);
  }

  forget(item: MemoryItem): void {
    this.session.forgetMemory(item.kind, item.id);
  }

  meta(item: MemoryItem): string {
    return itemMeta(item);
  }

  openSettings(): void {
    this.settingsOpen.set(true);
    window.setTimeout(() => this.tokenInput?.nativeElement.focus());
  }

  closeSettings(): void {
    const wasOpen = this.settingsOpen();
    this.token = '';
    this.settingsOpen.set(false);
    if (wasOpen) window.setTimeout(() => this.settingsButton?.nativeElement.focus());
  }

  closeSettingsFromBackdrop(event: MouseEvent): void {
    if (event.target === event.currentTarget) this.closeSettings();
  }

  onSettingsKeydown(event: KeyboardEvent): void {
    this.trapFocus(event, this.settingsPanel?.nativeElement);
  }

  private trapFocus(event: KeyboardEvent, panel: HTMLElement | undefined): void {
    if (event.key !== 'Tab' || !panel) return;
    const focusable = Array.from(panel.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled])'));
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  start(): void {
    const token = this.token.trim();
    this.sessionStartedAt = performance.now();
    this.elapsedMs.set(0);
    void this.session.start(token);
    this.closeSettings();
  }

  centerAction(): void {
    if (!this.isSessionActive() || this.session.status() === 'error') {
      this.openSettings();
      return;
    }
    if (this.session.status() !== 'connecting') this.toggleMute();
  }

  toggleMute(): void {
    if (this.canControlSession()) this.session.setMuted(!this.session.muted());
  }

  stop(): void {
    this.session.stop();
  }

  /**
   * Approve needs a real click: a script-made click event is not trusted and is ignored. Approve
   * is also ignored for half a second after the card appears, so a click meant for a button the
   * card pushed down cannot approve.
   */
  decide(allow: boolean, event: Event): void {
    if (!event.isTrusted) return;
    if (allow && performance.now() - this.session.pendingActionShownAt() < 500) return;
    this.session.decideAction(allow);
  }

  endOrStart(): void {
    if (this.isSessionActive()) this.stop();
    else this.openSettings();
  }

  elapsedLabel(): string {
    return formatElapsed(this.elapsedMs());
  }

  barHeight(strength: number): number {
    return spectrumBarHeight(this.session.status(), this.session.inputLevel(), strength);
  }
}
