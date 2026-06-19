import { Component, inject, signal, computed } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';

const API = 'http://127.0.0.1:8000';

interface DictTrait { kind: string; value: number; band: string; count?: number;
  high?: number; low?: number; task?: number; group?: number; }
interface DictResult {
  lta: { tokens: number; traits: Record<string, DictTrait> };
  vics: Record<string, { label: string; value?: number }>;
}
interface LlmTrait { score: number; band: string; rationale: string; }
interface LlmResult {
  traits: Record<string, LlmTrait>;
  leadership_style?: string; summary?: string; model?: string;
}
interface Meta { lta_traits: string[]; vics_indices: string[];
  norming_corpus_default: string[]; llm_available: boolean; }

interface TraitInfo { what: string; high: string; low: string; }

@Component({
  selector: 'app-root',
  imports: [FormsModule],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  private http = inject(HttpClient);

  readonly traits = ['BACE', 'PWR', 'CC', 'SC', 'TASK', 'DIS', 'IGB'];
  readonly traitNames: Record<string, string> = {
    BACE: 'Belief in Ability to Control Events', PWR: 'Need for Power',
    CC: 'Conceptual Complexity', SC: 'Self-Confidence', TASK: 'Task Focus',
    DIS: 'Distrust of Others', IGB: 'In-Group Bias',
  };

  // Plain-language explanation of each personality trait.
  readonly info: Record<string, TraitInfo> = {
    BACE: {
      what: 'Does the leader feel they can steer events, or feel swept along by them?',
      high: 'Takes charge and initiates — "we decide our own destiny".',
      low: 'Reacts to events and waits; lets others or circumstances lead.',
    },
    PWR: {
      what: 'How much the leader wants to control and influence other people.',
      high: 'Dominates, asserts authority, outmaneuvers rivals.',
      low: 'Shares influence and prefers cooperation over control.',
    },
    CC: {
      what: "How black-and-white versus nuanced the leader's thinking is.",
      high: 'Sees shades of grey and many angles — "it depends".',
      low: 'Sees things as right/wrong, certain and simple.',
    },
    SC: {
      what: 'How sure the leader is of themselves and their own judgment.',
      high: 'Self-assured; trusts their own view — "I know what to do".',
      low: 'Self-doubting; looks to others and the situation for cues.',
    },
    TASK: {
      what: 'What drives the leader: getting the job done, or holding people together.',
      high: 'Focused on goals, problems and results.',
      low: 'Focused on people, relationships, morale and feelings.',
    },
    DIS: {
      what: 'How suspicious the leader is of other people and groups.',
      high: 'Sees enemies, threats and hidden motives.',
      low: 'Tends to trust others and treat them as potential partners.',
    },
    IGB: {
      what: "How strongly the leader divides the world into 'us' and 'them'.",
      high: 'Strong national/group pride; outsiders seen as a threat.',
      low: 'Inclusive; sees common ground with other groups.',
    },
  };

  // Plain-language explanation of each operational-code index.
  readonly vicsInfo: Record<string, string> = {
    'P-1': 'Does the leader see the political world as friendly or hostile? Near +1 = friendly and cooperative; near −1 = threatening.',
    'P-2': 'How hopeful the leader is about reaching their political goals. Higher = more optimistic.',
    'P-3': 'How predictable the leader thinks politics is. Higher = they see the future as more knowable.',
    'P-4': 'How much the leader feels they — rather than others or fate — control history. Higher = more personal control.',
    'P-5': 'How much the leader thinks luck and chance drive events. Higher = more is left to chance.',
    'I-1': "Whether the leader's overall approach leans cooperative (positive) or confrontational (negative).",
    'I-2': 'How gentle vs. forceful the tactics are — from rewards/promises (positive) to threats/punishment (negative).',
    'I-3': 'How much risk the leader is willing to take. Higher = more willing to gamble.',
    'I-4a': 'How much the leader switches between cooperative and confrontational moves. Higher = more balanced/flexible.',
    'I-4b': 'How much the leader switches between words and actions. Higher = more balanced.',
    'I-5': 'The mix of tactics used (rewards, promises, threats, etc.).',
    'Summary': 'An overall sense of whether the leader credits themselves (positive) or others (negative).',
  };

  text = signal('');
  meta = signal<Meta | null>(null);
  samples = signal<{ key: string; text: string }[]>([]);
  showHelp = signal(true);

  dict = signal<DictResult | null>(null);
  llm = signal<LlmResult | null>(null);
  dictLoading = signal(false);
  llmLoading = signal(false);
  error = signal('');

  vicsList = computed(() => {
    const d = this.dict();
    if (!d) return [];
    return Object.entries(d.vics)
      .filter(([, v]) => v.value !== undefined)
      .map(([code, v]) => ({ code, label: v.label, value: v.value as number }));
  });

  constructor() {
    this.http.get<Meta>(`${API}/meta`).subscribe({
      next: (m) => this.meta.set(m), error: () => {},
    });
    this.http.get<Record<string, { text: string }>>(`${API}/mock-speeches`).subscribe({
      next: (s) => this.samples.set(
        Object.entries(s).map(([key, v]) => ({ key, text: v.text }))),
      error: () => {},
    });
  }

  toggleHelp() { this.showHelp.update((v) => !v); }

  loadSample(text: string) {
    if (text) this.text.set(text);
  }

  runDictionary() {
    if (!this.text().trim()) return;
    this.dictLoading.set(true); this.error.set('');
    this.http.post<DictResult>(`${API}/analyze`, { text: this.text() }).subscribe({
      next: (r) => { this.dict.set(r); this.dictLoading.set(false); },
      error: (e) => { this.error.set(this.msg(e)); this.dictLoading.set(false); },
    });
  }

  runLlm() {
    if (!this.text().trim()) return;
    this.llmLoading.set(true); this.error.set('');
    this.http.post<LlmResult>(`${API}/analyze/llm`, { text: this.text() }).subscribe({
      next: (r) => { this.llm.set(r); this.llmLoading.set(false); },
      error: (e) => { this.error.set(this.msg(e)); this.llmLoading.set(false); },
    });
  }

  bandClass(band: string): string {
    return 'band-' + (band || '').toLowerCase();
  }

  /** Display value for a dictionary trait: ratio as %, density as raw. */
  dictValue(t: DictTrait): string {
    return t.kind === 'ratio' ? (t.value * 100).toFixed(0) + '%' : t.value.toFixed(1);
  }

  private msg(e: any): string {
    if (e?.status === 0) return 'Cannot reach the analyzer at ' + API + ' — make sure the backend is running.';
    if (e?.status === 503) return 'The AI scorer is not switched on (the server is missing its GROQ_API_KEY).';
    return e?.error?.detail || e?.message || 'Something went wrong with the request.';
  }
}
