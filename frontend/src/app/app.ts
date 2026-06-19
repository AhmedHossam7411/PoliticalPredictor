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

  text = signal('');
  meta = signal<Meta | null>(null);
  samples = signal<{ key: string; text: string }[]>([]);

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
    if (e?.status === 0) return 'Cannot reach API at ' + API + ' — is uvicorn running?';
    if (e?.status === 503) return 'LLM not configured (set GROQ_API_KEY on the server).';
    return e?.error?.detail || e?.message || 'Request failed.';
  }
}
