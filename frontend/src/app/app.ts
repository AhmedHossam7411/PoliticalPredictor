import { Component, inject, signal, computed } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { LANGS, Lang } from './i18n';

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

  lang = signal<Lang>('en');
  t = computed(() => LANGS[this.lang()]);

  text = signal('');
  meta = signal<Meta | null>(null);
  samples = signal<{ key: string; text: string }[]>([]);
  showHelp = signal(true);

  dict = signal<DictResult | null>(null);
  llm = signal<LlmResult | null>(null);
  dictLoading = signal(false);
  llmLoading = signal(false);
  error = signal('');

  anyLoading = computed(() => this.dictLoading() || this.llmLoading());

  vicsList = computed(() => {
    const d = this.dict();
    if (!d) return [];
    return Object.entries(d.vics)
      .filter(([, v]) => v.value !== undefined)
      .map(([code, v]) => ({ code, value: v.value as number }));
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

  toggleLang() { this.lang.update((l) => (l === 'en' ? 'ar' : 'en')); }
  toggleHelp() { this.showHelp.update((v) => !v); }

  loadSample(text: string) {
    if (text) this.text.set(text);
  }

  /** Run both scorers together; skip the AI one if the server has it switched off. */
  runBoth() {
    if (!this.text().trim()) return;
    this.runDictionary();
    if (this.meta()?.llm_available !== false) this.runLlm();
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
    this.http.post<LlmResult>(`${API}/analyze/llm`,
      { text: this.text(), language: this.lang() }).subscribe({
      next: (r) => { this.llm.set(r); this.llmLoading.set(false); },
      error: (e) => { this.error.set(this.msg(e)); this.llmLoading.set(false); },
    });
  }

  bandClass(band: string): string {
    return 'band-' + (band || '').toLowerCase();
  }

  bandLabel(band: string): string {
    return this.t().bands[band] ?? band;
  }

  /** Display value for a dictionary trait: ratio as %, density as raw. */
  dictValue(t: DictTrait): string {
    return t.kind === 'ratio' ? (t.value * 100).toFixed(0) + '%' : t.value.toFixed(1);
  }

  private msg(e: any): string {
    const b = this.t();
    if (e?.status === 0) return b.errReach.replace('{api}', API);
    if (e?.status === 503) return b.errOff;
    return e?.error?.detail || e?.message || b.errGeneric;
  }
}
