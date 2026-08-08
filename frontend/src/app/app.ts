import { Component, inject, signal, computed } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { LANGS, Lang } from './i18n';

// Backend URL. Overridden in production by setting window.__API_URL__ in
// index.html (to the deployed backend); defaults to the local dev server.
declare global {
  interface Window { __API_URL__?: string; grecaptcha?: any }
}
const API = window.__API_URL__ || 'http://127.0.0.1:8000';

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
interface Reaction { id: string; name: string; role: string; stance: string;
  confidence: number; reasoning: string; response: string; }
interface StakeResult { reactions: Reaction[]; method: string; model?: string;
  calibrated?: boolean; }
interface PublicStakeholder { id: string; name: string; role: string; scope?: string;
  personality?: string; values: string[]; supports: string[]; opposes: string[];
  concerns: string[]; custom: boolean; }
interface SpeechOpt { id: string; label: string; }

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

  // Top-nav page selection
  page = signal<'analyze' | 'stakeholders' | 'guide'>('analyze');

  // --- Login gate ---------------------------------------------------------
  authed = signal(false);
  loginUser = signal('');
  loginPass = signal('');
  loginError = signal('');
  loginLoading = signal(false);

  text = signal('');
  submittedText = signal('');   // snapshot shown on the left once analyzed
  meta = signal<Meta | null>(null);
  showHelp = signal(true);

  dict = signal<DictResult | null>(null);
  llm = signal<LlmResult | null>(null);
  stake = signal<StakeResult | null>(null);
  dictLoading = signal(false);
  llmLoading = signal(false);
  stakeLoading = signal(false);
  error = signal('');

  // --- Stakeholder panel management --------------------------------------
  stakeholders = signal<PublicStakeholder[]>([]);
  speeches = signal<SpeechOpt[]>([]);
  showPanel = signal(false);
  showAddForm = signal(false);
  nsName = signal(''); nsRole = signal('');
  nsValues = signal(''); nsSupports = signal(''); nsOpposes = signal(''); nsConcerns = signal('');
  speechMode = signal<'new' | 'existing' | 'none'>('new');
  nsSpeechText = signal(''); nsSpeechFrom = signal('');
  addLoading = signal(false); addError = signal(''); addMsg = signal('');

  // --- PDF password re-prompt --------------------------------------------
  pdfPromptOpen = signal(false);
  pdfPass = signal('');
  pdfError = signal('');

  anyLoading = computed(() =>
    this.dictLoading() || this.llmLoading() || this.stakeLoading());
  analyzed = computed(() => !!this.dict() || !!this.llm() || !!this.stake());

  // Stakeholder stance filter + counts
  readonly stanceOrder = ['Support', 'Oppose', 'Mixed', 'Neutral'];
  stanceFilter = signal<string>('All');

  stanceCounts = computed(() => {
    const counts: Record<string, number> = { Support: 0, Oppose: 0, Mixed: 0, Neutral: 0 };
    for (const r of this.stake()?.reactions ?? []) {
      if (counts[r.stance] !== undefined) counts[r.stance]++;
    }
    return counts;
  });

  /** Reactions filtered by the chosen stance, grouped by stance then confidence. */
  filteredReactions = computed(() => {
    const all = this.stake()?.reactions ?? [];
    const f = this.stanceFilter();
    const rank = (s: string) => {
      const i = this.stanceOrder.indexOf(s);
      return i === -1 ? 99 : i;
    };
    return all
      .filter((r) => f === 'All' || r.stance === f)
      .slice()
      .sort((a, b) => rank(a.stance) - rank(b.stance) || b.confidence - a.confidence);
  });

  setStanceFilter(s: string) { this.stanceFilter.set(s); }

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
    // Resume an existing session if a token is already stored.
    if (sessionStorage.getItem('pp_token')) {
      this.authed.set(true);
      this.loadInitialData();
    }
  }

  private loadInitialData() {
    this.http.get<Meta>(`${API}/meta`).subscribe({
      next: (m) => this.meta.set(m), error: () => {},
    });
    this.loadStakeholders();
    this.loadSpeeches();
  }

  loadStakeholders() {
    this.http.get<{ stakeholders: PublicStakeholder[] }>(`${API}/stakeholders`).subscribe({
      next: (r) => this.stakeholders.set(r.stakeholders), error: () => {},
    });
  }

  loadSpeeches() {
    this.http.get<{ speeches: SpeechOpt[] }>(`${API}/stakeholders/speeches`).subscribe({
      next: (r) => this.speeches.set(r.speeches), error: () => {},
    });
  }

  private splitCsv(s: string): string[] {
    return s.split(',').map((x) => x.trim()).filter(Boolean);
  }

  toggleAddForm() {
    this.showAddForm.update((v) => !v);
    this.addError.set(''); this.addMsg.set('');
  }

  resetAddForm() {
    this.nsName.set(''); this.nsRole.set('');
    this.nsValues.set(''); this.nsSupports.set(''); this.nsOpposes.set(''); this.nsConcerns.set('');
    this.nsSpeechText.set(''); this.nsSpeechFrom.set(''); this.speechMode.set('new');
    this.showAddForm.set(false);
  }

  submitStakeholder() {
    const name = this.nsName().trim();
    if (!name) { this.addError.set(this.t().nameRequired); return; }
    const body: Record<string, unknown> = {
      name, role: this.nsRole().trim(),
      values: this.splitCsv(this.nsValues()), supports: this.splitCsv(this.nsSupports()),
      opposes: this.splitCsv(this.nsOpposes()), concerns: this.splitCsv(this.nsConcerns()),
      language: this.lang(),
    };
    if (this.speechMode() === 'new') body['speech_text'] = this.nsSpeechText();
    else if (this.speechMode() === 'existing') body['speech_from'] = this.nsSpeechFrom();

    this.addLoading.set(true); this.addError.set(''); this.addMsg.set('');
    this.http.post<{ calibrated: boolean; warning?: string }>(`${API}/stakeholders`, body).subscribe({
      next: (r) => {
        this.addLoading.set(false);
        this.addMsg.set(this.t().addedOk + (r.calibrated ? ' ' + this.t().addedCalibrated : ''));
        if (r.warning) this.addError.set(r.warning);
        this.resetAddForm();
        this.loadStakeholders(); this.loadSpeeches();
      },
      error: (e) => { this.addLoading.set(false); this.addError.set(this.msg(e)); },
    });
  }

  deleteStakeholder(id: string) {
    this.http.delete(`${API}/stakeholders/${id}`).subscribe({
      next: () => { this.loadStakeholders(); this.loadSpeeches(); },
      error: (e) => { this.addError.set(this.msg(e)); },
    });
  }

  toggleLang() { this.lang.update((l) => (l === 'en' ? 'ar' : 'en')); }
  toggleHelp() { this.showHelp.update((v) => !v); }

  // --- Login (backend auth + reCAPTCHA) -----------------------------------
  login() {
    const captcha = window.grecaptcha?.getResponse?.() ?? '';
    if (!captcha) { this.loginError.set(this.t().captchaNeeded); return; }
    this.loginLoading.set(true); this.loginError.set('');
    this.http.post<{ token: string }>(`${API}/auth/login`, {
      username: this.loginUser().trim(),
      password: this.loginPass(),
      captcha_token: captcha,
    }).subscribe({
      next: (r) => {
        sessionStorage.setItem('pp_token', r.token);
        this.loginLoading.set(false);
        this.loginPass.set('');
        this.authed.set(true);
        this.loadInitialData();
      },
      error: (e) => {
        this.loginLoading.set(false);
        window.grecaptcha?.reset?.();
        this.loginError.set(
          e?.status === 400 ? this.t().captchaFailed :
          e?.status === 429 ? this.t().tooMany : this.t().loginErr);
      },
    });
  }

  logout() {
    sessionStorage.removeItem('pp_token');
    location.reload();  // fresh login screen (re-renders the captcha cleanly)
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
    this.stake.set(null);
    this.submittedText.set('');
    this.error.set('');
  }

  /** Run every analysis together; skip the AI trait scorer if the server has it off. */
  runBoth() {
    if (!this.text().trim()) return;
    this.submittedText.set(this.text());
    this.runDictionary();
    this.runStakeholders();
    if (this.meta()?.llm_available !== false) this.runLlm();
  }

  runStakeholders() {
    if (!this.text().trim()) return;
    this.stanceFilter.set('All');
    this.stakeLoading.set(true); this.error.set('');
    this.http.post<StakeResult>(`${API}/analyze/stakeholders`,
      { text: this.text(), language: this.lang() }).subscribe({
      next: (r) => { this.stake.set(r); this.stakeLoading.set(false); },
      error: (e) => { this.error.set(this.msg(e)); this.stakeLoading.set(false); },
    });
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
    // Re-verify the password server-side (the client no longer holds it).
    this.pdfError.set('');
    this.http.post<{ ok: boolean }>(`${API}/auth/verify-password`,
      { password: this.pdfPass() }).subscribe({
      next: (r) => {
        if (r.ok) { this.pdfPromptOpen.set(false); this.generatePdf(); }
        else { this.pdfError.set(this.t().pdfWrongPass); }
      },
      error: () => this.pdfError.set(this.t().pdfWrongPass),
    });
  }

  bandClass(band: string): string {
    return 'band-' + (band || '').toLowerCase();
  }

  bandLabel(band: string): string {
    return this.t().bands[band] ?? band;
  }

  stanceClass(stance: string): string {
    return 'stance-' + (stance || '').toLowerCase();
  }

  stanceLabel(stance: string): string {
    return this.t().stances[stance] ?? stance;
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

    let stake = '';
    const st = this.stake();
    if (st) {
      const rows = st.reactions.map((r) =>
        `<div class="ai-row">
          <p><strong>${this.esc(r.name)}</strong> — ${this.esc(r.role)}</p>
          <p><strong>${this.esc(this.stanceLabel(r.stance))}</strong>
             (${r.confidence}%) — ${this.esc(r.reasoning)}</p>
          <p class="rat"><em>${this.esc(b.likelyResponse)}</em> ${this.esc(r.response)}</p>
        </div>`).join('');
      stake = `<h2>${this.esc(b.stakeHeading)}</h2>
        <p>${this.esc(b.stakeIntro)}</p>${rows}`;
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
      ${stake}
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
