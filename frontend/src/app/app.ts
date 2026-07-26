import { Component, inject, signal, computed } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { LANGS, Lang } from './i18n';

const API = 'http://127.0.0.1:8000';

// Simple front-end gate. Change these to whatever username / password you want.
const CREDENTIALS = { username: 'admin', password: 'predict2026' };

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

  // --- Login gate ---------------------------------------------------------
  authed = signal(false);
  loginUser = signal('');
  loginPass = signal('');
  loginError = signal('');

  text = signal('');
  submittedText = signal('');   // snapshot shown on the left once analyzed
  meta = signal<Meta | null>(null);
  showHelp = signal(true);

  dict = signal<DictResult | null>(null);
  llm = signal<LlmResult | null>(null);
  dictLoading = signal(false);
  llmLoading = signal(false);
  error = signal('');

  // --- PDF password re-prompt --------------------------------------------
  pdfPromptOpen = signal(false);
  pdfPass = signal('');
  pdfError = signal('');

  anyLoading = computed(() => this.dictLoading() || this.llmLoading());
  analyzed = computed(() => !!this.dict() || !!this.llm());

  vicsList = computed(() => {
    const d = this.dict();
    if (!d) return [];
    return Object.entries(d.vics)
      .filter(([, v]) => v.value !== undefined)
      .map(([code, v]) => ({ code, value: v.value as number }));
  });

  /** Big summary for the right-hand panel: prefer the AI summary, else build
   *  a short one from the word scorer's high/low bands. */
  summary = computed(() => {
    const l = this.llm();
    if (l?.summary) return l.summary;
    const d = this.dict();
    if (!d) return '';
    const b = this.t();
    const highs = this.traits.filter((tr) => d.lta.traits[tr]?.band === 'High');
    const lows = this.traits.filter((tr) => d.lta.traits[tr]?.band === 'Low');
    const name = (tr: string) => b.traitNames[tr];
    const parts: string[] = [];
    if (highs.length) parts.push(`${b.higher} ${highs.map(name).join(', ')}.`);
    if (lows.length) parts.push(`${b.lower} ${lows.map(name).join(', ')}.`);
    return parts.join(' ');
  });

  constructor() {
    this.http.get<Meta>(`${API}/meta`).subscribe({
      next: (m) => this.meta.set(m), error: () => {},
    });
  }

  toggleLang() { this.lang.update((l) => (l === 'en' ? 'ar' : 'en')); }
  toggleHelp() { this.showHelp.update((v) => !v); }

  // --- Login --------------------------------------------------------------
  login() {
    if (this.loginUser().trim() === CREDENTIALS.username &&
        this.loginPass() === CREDENTIALS.password) {
      this.authed.set(true);
      this.loginError.set('');
      this.loginPass.set('');
    } else {
      this.loginError.set(this.t().loginErr);
    }
  }

  logout() {
    this.authed.set(false);
    this.loginUser.set('');
    this.loginPass.set('');
  }

  async pasteFromClipboard() {
    try {
      const clip = await navigator.clipboard.readText();
      if (clip) this.text.set(clip);
    } catch { /* clipboard blocked — user can paste manually */ }
  }

  clearText() {
    this.text.set('');
    this.dict.set(null);
    this.llm.set(null);
    this.submittedText.set('');
    this.error.set('');
  }

  /** Run both scorers together; skip the AI one if the server has it switched off. */
  runBoth() {
    if (!this.text().trim()) return;
    this.submittedText.set(this.text());
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

  // --- PDF (password-gated) ----------------------------------------------
  openPdfPrompt() {
    this.pdfPass.set('');
    this.pdfError.set('');
    this.pdfPromptOpen.set(true);
  }

  cancelPdf() { this.pdfPromptOpen.set(false); }

  confirmPdf() {
    if (this.pdfPass() !== CREDENTIALS.password) {
      this.pdfError.set(this.t().pdfWrongPass);
      return;
    }
    this.pdfPromptOpen.set(false);
    this.generatePdf();
  }

  bandClass(band: string): string {
    return 'band-' + (band || '').toLowerCase();
  }

  bandLabel(band: string): string {
    return this.t().bands[band] ?? band;
  }

  /** Display value for a dictionary trait: ratio as %, density as raw. */
  dictValue(tr: DictTrait): string {
    return tr.kind === 'ratio' ? (tr.value * 100).toFixed(0) + '%' : tr.value.toFixed(1);
  }

  /** Open a printable window with the full analysis; the browser's print
   *  dialog lets the user "Save as PDF". */
  private generatePdf() {
    const html = this.buildPdfHtml();
    const w = window.open('', '_blank');
    if (!w) return;
    w.document.open();
    w.document.write(html);
    w.document.close();
    w.focus();
    // Give the new document a tick to lay out before printing.
    w.onload = () => w.print();
  }

  private esc(s: string): string {
    return (s ?? '').replace(/[&<>"]/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] as string));
  }

  private buildPdfHtml(): string {
    const b = this.t();
    const d = this.dict();
    const l = this.llm();
    const dir = b.dir;

    let word = '';
    if (d) {
      const traitRows = this.traits.map((tr) => {
        const tt = d.lta.traits[tr];
        return `<tr><td>${this.esc(b.traitNames[tr])} (${tr})</td>
          <td>${this.esc(this.bandLabel(tt.band))}</td></tr>`;
      }).join('');
      const vicsRows = this.vicsList().map((v) =>
        `<tr><td>${this.esc(v.code)}</td><td>${v.value.toFixed(2)}</td></tr>`).join('');
      word = `<h2>${this.esc(b.pdfWordHeading)}</h2>
        <h3>${this.esc(b.personalityHeading)}</h3>
        <table>${traitRows}</table>
        <h3>${this.esc(b.politicsHeading)}</h3>
        <table>${vicsRows}</table>`;
    }

    let ai = '';
    if (l) {
      const style = l.leadership_style
        ? `<p><strong>${this.esc(b.leadershipLabel)}</strong> ${this.esc(l.leadership_style)}</p>` : '';
      const summ = l.summary ? `<p>${this.esc(l.summary)}</p>` : '';
      const rows = this.traits.map((tr) => {
        const tt = l.traits[tr];
        return `<div class="ai-row">
          <p><strong>${this.esc(b.traitNames[tr])} (${tr})</strong>
             — ${this.esc(this.bandLabel(tt.band))}, ${tt.score}/100</p>
          <p class="rat"><em>${this.esc(b.whyScore)}</em> ${this.esc(tt.rationale)}</p>
        </div>`;
      }).join('');
      ai = `<h2>${this.esc(b.pdfAiHeading)}</h2>${style}${summ}${rows}`;
    }

    return `<!doctype html><html dir="${dir}"><head><meta charset="utf-8">
      <title>${this.esc(b.pdfDocTitle)}</title>
      <style>
        body { font-family: system-ui, Segoe UI, Roboto, Arial, sans-serif;
          color: #111; margin: 32px; line-height: 1.5; }
        h1 { font-size: 22px; margin: 0 0 4px; }
        h2 { font-size: 16px; margin: 22px 0 6px; border-bottom: 2px solid #444; padding-bottom: 4px; }
        h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: #555; margin: 14px 0 4px; }
        table { width: 100%; border-collapse: collapse; margin: 4px 0 8px; }
        td { border: 1px solid #ccc; padding: 5px 8px; font-size: 13px; }
        .quote { white-space: pre-wrap; background: #f6f6f6; border: 1px solid #ddd;
          border-radius: 6px; padding: 10px 12px; font-size: 12px; }
        .ai-row { margin: 8px 0; }
        .rat { color: #333; font-size: 12px; margin: 2px 0 0; }
        .foot { margin-top: 28px; color: #888; font-size: 11px; }
      </style></head><body>
      <h1>${this.esc(b.pdfDocTitle)}</h1>
      <h2>${this.esc(b.pdfInputHeading)}</h2>
      <div class="quote">${this.esc(this.submittedText())}</div>
      ${word}
      ${ai}
      <p class="foot">${this.esc(b.pdfGenerated)}</p>
      </body></html>`;
  }

  private msg(e: any): string {
    const b = this.t();
    if (e?.status === 0) return b.errReach.replace('{api}', API);
    if (e?.status === 503) return b.errOff;
    return e?.error?.detail || e?.message || b.errGeneric;
  }
}
