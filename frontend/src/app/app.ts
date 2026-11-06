import { Component, inject, signal, computed } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { LANGS, Lang } from './i18n';

// Backend URL. Overridden in production by setting window.__API_URL__ in
// index.html (to the deployed backend); defaults to the local dev server.
declare global {
  interface Window { __API_URL__?: string }
}
const API = window.__API_URL__ || 'http://127.0.0.1:8000';
const TRAIT_COLORS: Record<string, string> = {
  BACE: '#2563eb', PWR: '#dc2626', CC: '#7c3aed', SC: '#ea580c',
  TASK: '#16a34a', DIS: '#92400e', IGB: '#0d9488',
};

/** Text from PDFs and web pages keeps its old line breaks, which leaves it stuck in a
 *  narrow column. Turn a break inside a sentence into a space, one character for one
 *  so word positions stay valid. Blank lines, sentence ends and short lines keep theirs. */
function reflowLines(chars: string[]): string[] {
  const out = [...chars];
  let lineStart = 0;
  for (let i = 0; i < chars.length; i++) {
    if (chars[i] !== '\n') continue;
    let last = i - 1;
    while (last >= lineStart && /[ \t]/.test(chars[last])) last--;
    let next = i + 1;
    while (next < chars.length && /[ \t]/.test(chars[next])) next++;
    const blank = last < lineStart || next >= chars.length || chars[next] === '\n';
    const ended = !blank && /[.!?:;؟؛…"”’)»]/.test(chars[last]);
    if (!blank && !ended && last - lineStart + 1 >= 40) out[i] = ' ';
    lineStart = i + 1;
  }
  return out;
}

/** A filled word = high/problem-solving/one-list word; underline only = low/relationship.
 *  A word on several lists gets one underline per list. */
function highlightStyle(labels: string[]): string {
  const [trait, pole] = labels[0].split(':');
  const lines = labels.map((l, i) => `inset 0 ${-2 * (i + 1)}px 0 ${TRAIT_COLORS[l.split(':')[0]]}`);
  const fill = pole === 'low' ? '' : `background:${TRAIT_COLORS[trait]}2e;`;
  return `${fill}box-shadow:${lines.join(',')};`;
}

interface DictTrait { kind: string; value: number; band: string; count?: number;
  high?: number; low?: number; task?: number; group?: number;
  // Evidence weighting: band uses `adjusted`; confidence = how much text backs it.
  adjusted?: number; raw_band?: string; confidence?: 'low' | 'medium' | 'high';
  percent?: number; hits?: number;
  // Words found: {word: count}, or per list for the two-list traits.
  matches?: Record<string, number> | Record<string, Record<string, number>>; }
// One counted word: character offsets (code points) and lists, e.g. "CC:high".
interface WordSpan { start: number; end: number; labels: string[]; }
// One speaker's text from a document holding several ("chair" = the chair's short remarks).
interface Speech { id: string; speaker: string; title: string | null; spoke_in: string | null;
  kind: 'speech' | 'chair'; words: number; text: string; }
interface HighlightPiece { text: string; style: string; title: string; }
interface InputInfo { language: 'en' | 'ar'; dialect: 'msa' | 'egyptian' | 'mixed' | null; }
interface DictResult {
  input?: InputInfo; vics_supported?: boolean;
  lta: { tokens: number; traits: Record<string, DictTrait> };
  spans?: WordSpan[];
  vics: Record<string, { label: string; value?: number }>;
}
interface LlmTrait { score: number; band: string; rationale: string; }
// How much of a long document the AI was sent.
interface Excerpted { read_words: number; total_words: number; }
interface LlmResult {
  traits: Record<string, LlmTrait>;
  leadership_style?: string; summary?: string; model?: string; input?: InputInfo;
  excerpted?: Excerpted | null;
}
interface Meta { lta_traits: string[]; vics_indices: string[];
  norming_corpus_default: string[]; llm_available: boolean; }
interface Reaction { id: string; name: string; role: string; stance: string;
  confidence: number; reasoning: string; response: string; }
interface StakeResult { reactions: Reaction[]; method: string; model?: string;
  calibrated?: boolean; fallback_reason?: string; excerpted?: Excerpted | null; }
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
  private sanitizer = inject(DomSanitizer);
  captchaSvg = signal<SafeHtml | null>(null);
  captchaId = signal('');
  captchaAnswer = signal('');

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
  dictText = signal('');        // the text `dict` was scored on
  hiddenLists = signal<ReadonlySet<string>>(new Set());
  docSpeeches = signal<Speech[]>([]);
  selectedSpeech = signal('');  // '' = the whole document
  private fullText = '';        // the whole document, to go back to
  analyzedSpeech = signal('');  // who the current results are about
  analyzedMixed = signal(false);  // the results combine several speakers
  speechScores = signal<{ speech: Speech; traits: Record<string, DictTrait> }[] | null>(null);
  scoringSpeeches = signal(false);
  uploading = signal(false);
  uploadedName = signal('');
  uploadError = signal('');
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

  /** "The AI read 5,120 of 41,836 words…", or '' when it read the whole text. */
  excerptNote(excerpted?: Excerpted | null): string {
    if (!excerpted) return '';
    const fmt = (n: number) => n.toLocaleString('en-US');
    return this.t().aiExcerptNote.replace('{read}', fmt(excerpted.read_words)).replace('{total}', fmt(excerpted.total_words));
  }

  /** Display name of a word list, e.g. "Conceptual Complexity: High list". */
  private listName(label: string): string {
    const b = this.t();
    const [trait, pole] = label.split(':');
    if (trait !== 'CC' && trait !== 'SC' && trait !== 'TASK') return b.traitNames[trait];
    const [first, second] = this.listNames(trait);
    return `${b.traitNames[trait]}: ${b.listOf.replace('{x}', pole === 'low' ? second : first)}`;
  }

  /** The word lists found in the analyzed text, in trait order, with counts. */
  highlightLegend = computed(() => {
    const counts: Record<string, number> = {};
    for (const span of this.dict()?.spans ?? []) {
      for (const l of span.labels) counts[l] = (counts[l] ?? 0) + 1;
    }
    const hidden = this.hiddenLists();
    return this.traits.flatMap((tr) => [`${tr}:high`, `${tr}:low`])
      .filter((l) => counts[l])
      .map((l) => ({ label: l, name: this.listName(l), count: counts[l], hidden: hidden.has(l),
                     style: highlightStyle([l]) }));
  });

  /** The analyzed text cut at every counted word's edges, styled by the lists covering it. */
  highlightPieces = computed<HighlightPiece[]>(() => {
    const text = this.submittedText();
    const hidden = this.hiddenLists();
    // Offsets count code points; Array.from keeps emoji etc. from shifting them.
    const chars = reflowLines(Array.from(text));
    const spans = (this.dictText() === text ? this.dict()?.spans ?? [] : [])
      .map((s) => ({ ...s, labels: s.labels.filter((l) => !hidden.has(l)) }))
      .filter((s) => s.labels.length);
    const cuts = [...new Set([0, chars.length, ...spans.flatMap((s) => [s.start, s.end])])].sort((a, b) => a - b);
    // Walk the cuts in order, tracking which spans are open: a long document has
    // thousands of them, and checking every span at every cut freezes the page.
    const ordered = [...spans].sort((a, b) => a.start - b.start);
    let open: WordSpan[] = [];
    let next = 0;
    return cuts.slice(0, -1).map((start, i) => {
      const end = cuts[i + 1];
      open = open.filter((s) => s.end > start);
      while (next < ordered.length && ordered[next].start <= start) open.push(ordered[next++]);
      const labels = [...new Set(open.flatMap((s) => s.labels))];
      return { text: chars.slice(start, end).join(''),
               style: labels.length ? highlightStyle(labels) : '',
               title: labels.map((l) => this.listName(l)).join('\n') };
    });
  });

  toggleList(label: string) {
    const next = new Set(this.hiddenLists());
    if (!next.delete(label)) next.add(label);
    this.hiddenLists.set(next);
  }

  /** Detected language of the analyzed text (e.g. "Arabic — Egyptian colloquial"). */
  inputLang = computed(() => {
    const info = this.dict()?.input ?? this.llm()?.input;
    if (!info) return '';
    return this.t().inputLangs[info.language === 'ar' ? info.dialect ?? 'msa' : 'en'];
  });

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
  wordSummary = computed(() => {
    const d = this.dict();
    if (!d) return '';
    const b = this.t();
    const highs = this.traits.filter((tr) => d.lta.traits[tr]?.band === 'High');
    const lows = this.traits.filter((tr) => d.lta.traits[tr]?.band === 'Low');
    const name = (tr: string) => b.traitNames[tr];
    const parts: string[] = [];
    if (highs.length) parts.push(`${b.higher} ${highs.map(name).join(', ')}.`);
    if (lows.length) parts.push(`${b.lower} ${lows.map(name).join(', ')}.`);
    const task = d.lta.traits['TASK']?.band;
    if (task && task !== 'Balanced' && task !== 'Too few words') parts.push(`${name('TASK')}: ${this.bandLabel(task)}.`);
    return parts.join(' ');
  });

  constructor() {
    // Resume an existing session if a token is already stored.
    if (sessionStorage.getItem('pp_token')) {
      this.authed.set(true);
      this.loadInitialData();
    } else {
      this.loadCaptcha();
    }
  }

  /** Fetch a fresh self-hosted captcha challenge for the login form. */
  loadCaptcha() {
    this.captchaAnswer.set('');
    this.http.get<{ id: string; svg: string }>(`${API}/auth/captcha`).subscribe({
      next: (c) => {
        this.captchaId.set(c.id);
        this.captchaSvg.set(this.sanitizer.bypassSecurityTrustHtml(c.svg));
      },
      error: () => {},
    });
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

  toggleLang() {
    this.lang.update((l) => (l === 'en' ? 'ar' : 'en'));
    // Re-run the language-dependent analyses so the AI prose (and the PDF) match
    // the new language — labels alone flipping would leave stale English content.
    const snap = this.submittedText();
    if (snap.trim()) {
      this.runStakeholders(snap);
      if (this.llm() && this.meta()?.llm_available !== false) this.runLlm(snap);
    }
  }
  toggleHelp() { this.showHelp.update((v) => !v); }

  // --- Login (backend auth + reCAPTCHA) -----------------------------------
  login() {
    if (!this.captchaAnswer().trim()) { this.loginError.set(this.t().captchaNeeded); return; }
    this.loginLoading.set(true); this.loginError.set('');
    this.http.post<{ token: string }>(`${API}/auth/login`, {
      username: this.loginUser().trim(),
      password: this.loginPass(),
      captcha_id: this.captchaId(),
      captcha_answer: this.captchaAnswer(),
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
        this.loadCaptcha();   // challenge is single-use — issue a fresh one
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
      if (clip) { this.text.set(clip); this.detectSpeeches(clip); }
    } catch { /* clipboard blocked — user can paste manually */ }
  }

  /** "Barack Obama — President of the United States of America (spoke in Arabic)". */
  speechLabel(s: Speech): string {
    const b = this.t();
    if (s.kind === 'chair') return b.chairRemarks;
    const who = s.title ? `${s.speaker} — ${s.title}` : s.speaker;
    return s.spoke_in ? `${who} (${b.spokeIn.replace('{x}', s.spoke_in)})` : who;
  }

  /** Show one speaker's text in the box, or the whole document for ''. */
  pickSpeech(id: string) {
    this.selectedSpeech.set(id);
    const speech = this.docSpeeches().find((s) => s.id === id);
    this.text.set(speech ? speech.text : this.fullText);
  }

  private setSpeeches(text: string, speeches: Speech[]) {
    this.fullText = text;
    this.docSpeeches.set(speeches);
    this.selectedSpeech.set('');
    this.speechScores.set(null);
  }

  /** Look for several speakers in pasted text; a short paste can't hold a record. */
  detectSpeeches(text: string) {
    if (text.length < 1000) { this.setSpeeches(text, []); return; }
    this.http.post<{ speeches: Speech[] }>(`${API}/split-speeches`, { text }).subscribe({
      next: (r) => this.setSpeeches(text, r.speeches),
    });
  }

  /** The textarea has the pasted text only after the paste event finishes. */
  onTextPaste() {
    setTimeout(() => this.detectSpeeches(this.text()));
  }

  /** Word-score every speaker at once, for comparing them side by side. */
  scoreAllSpeeches() {
    const speeches = this.docSpeeches().filter((s) => s.kind === 'speech');
    this.scoringSpeeches.set(true);
    this.http.post<{ results: DictResult[] }>(`${API}/analyze/batch`, { texts: speeches.map((s) => s.text) }).subscribe({
      next: (r) => {
        this.speechScores.set(speeches.map((speech, i) => ({ speech, traits: r.results[i].lta.traits })));
        this.scoringSpeeches.set(false);
      },
      error: (e) => { this.error.set(this.msg(e)); this.scoringSpeeches.set(false); },
    });
  }

  /** Put an uploaded file's text in the box, where it can be checked before analyzing. */
  uploadSpeech(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';  // so choosing the same file again fires "change"
    if (!file) return;
    this.uploadError.set('');
    this.uploadedName.set('');
    if (file.size > 50 * 1024 * 1024) {
      this.uploadError.set(this.t().uploadErrors['file-too-big']);
      return;
    }
    this.uploading.set(true);
    this.http.post<{ text: string; speeches: Speech[] }>(`${API}/extract-text`, file, {
      params: { filename: file.name },
      headers: { 'Content-Type': 'application/octet-stream' },
    }).subscribe({
      next: (r) => {
        this.text.set(r.text);
        this.setSpeeches(r.text, r.speeches);
        this.uploadedName.set(file.name);
        this.uploading.set(false);
      },
      error: (e) => {
        const errors = this.t().uploadErrors;
        this.uploadError.set(errors[e?.error?.detail] ?? errors['file-unreadable']);
        this.uploading.set(false);
      },
    });
  }

  clearText() {
    this.text.set('');
    this.setSpeeches('', []);
    this.analyzedSpeech.set('');
    this.analyzedMixed.set(false);
    this.uploadedName.set('');
    this.uploadError.set('');
    this.dict.set(null);
    this.llm.set(null);
    this.stake.set(null);
    this.submittedText.set('');
    this.error.set('');
  }

  /** Run every analysis together; skip the AI trait scorer if the server has it off. */
  runBoth() {
    if (!this.text().trim()) return;
    const snapshot = this.text();
    this.submittedText.set(snapshot);
    const picked = this.docSpeeches().find((s) => s.id === this.selectedSpeech());
    this.analyzedSpeech.set(picked ? this.speechLabel(picked) : '');
    this.analyzedMixed.set(!picked && this.docSpeeches().length > 0);
    this.runDictionary(snapshot);
    this.runStakeholders(snapshot);
    if (this.meta()?.llm_available !== false) this.runLlm(snapshot);
  }

  runStakeholders(text: string = this.text()) {
    if (!text.trim()) return;
    this.stanceFilter.set('All');
    this.stakeLoading.set(true); this.error.set('');
    this.http.post<StakeResult>(`${API}/analyze/stakeholders`,
      { text, language: this.lang() }).subscribe({
      next: (r) => { this.stake.set(r); this.stakeLoading.set(false); },
      error: (e) => { this.error.set(this.msg(e)); this.stakeLoading.set(false); },
    });
  }

  runDictionary(text: string = this.text()) {
    if (!text.trim()) return;
    this.dictLoading.set(true); this.error.set('');
    this.http.post<DictResult>(`${API}/analyze`, { text }).subscribe({
      next: (r) => { this.dict.set(r); this.dictText.set(text); this.dictLoading.set(false); },
      error: (e) => { this.error.set(this.msg(e)); this.dictLoading.set(false); },
    });
  }

  runLlm(text: string = this.text()) {
    if (!text.trim()) return;
    this.llmLoading.set(true); this.error.set('');
    this.http.post<LlmResult>(`${API}/analyze/llm`,
      { text, language: this.lang() }).subscribe({
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
    return 'band-' + (band || '').toLowerCase().replace(/ /g, '-');
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

  /** A dictionary trait's figure: the two lists' split, or the list words' share of the text. */
  dictValue(trait: string, tr: DictTrait): string {
    const b = this.t();
    const p = tr.percent ?? 0;
    if (tr.kind !== 'ratio') return `${p.toFixed(1)}% ${b.ofWords}`;
    if (!tr.hits) return b.noListWords;
    if (tr.band === 'Too few words') return `${b.listWordsLabel}: ${tr.hits}`;
    const [first, second] = this.listNames(trait);
    return `${p.toFixed(0)}% ${first} / ${(100 - p).toFixed(0)}% ${second}`;
  }

  /** Display names of a two-list trait's lists, first list first. */
  private listNames(trait: string): [string, string] {
    const b = this.t();
    return trait === 'TASK'
      ? [b.bands['Problem-solving'], b.bands['Relationship-building']]
      : [b.bands['High'], b.bands['Low']];
  }

  /** "must ×3, every ×2, clear +4 more": a list's words, most used first. */
  private wordsFound(found: Record<string, number> | undefined, limit: number): string {
    const b = this.t();
    const words = Object.entries(found ?? {}).sort((x, y) => y[1] - x[1]);
    if (!words.length) return b.noneFound;
    const shown = words.slice(0, limit).map(([w, n]) => (n > 1 ? `${w} ×${n}` : w)).join(', ');
    return words.length > limit ? `${shown} ${b.moreWords.replace('{n}', String(words.length - limit))}` : shown;
  }

  /** Why a word-list trait got its result: its words, in relation to the speech's length. */
  dictExplain(trait: string, tr: DictTrait, tokens: number, limit = 8): string {
    const b = this.t();
    const fill = (text: string, vars: Record<string, string | number>) =>
      Object.entries(vars).reduce((out, [k, v]) => out.replace(`{${k}}`, String(v)), text);
    const hits = tr.hits ?? 0;
    if (tr.kind !== 'ratio') {
      const found = tr.matches as Record<string, number>;
      const share = hits
        ? fill(b.reasonOnList, { hits, tokens, p: (tr.percent ?? 0).toFixed(1), words: this.wordsFound(found, limit) })
        : fill(b.reasonNoneOnList, { tokens });
      const verdict = tr.band === 'High' ? b.reasonAbove : tr.band === 'Low' ? b.reasonBelow
        : tr.raw_band !== tr.band ? fill(b.reasonThin, { x: this.bandLabel(tr.raw_band ?? '') }) : b.reasonUsual;
      return `${share} ${verdict}`;
    }
    const m = tr.matches as Record<string, Record<string, number>>;
    const [firstKey, secondKey, firstN, secondN] = trait === 'TASK'
      ? ['task', 'group', tr.task ?? 0, tr.group ?? 0] : ['high', 'low', tr.high ?? 0, tr.low ?? 0];
    const [first, second] = this.listNames(trait);
    const side = (name: string, n: number, key: string) =>
      `${b.listOf.replace('{x}', name)} (${n}): ${this.wordsFound(m[key], limit)}.`;
    const count = fill(b.reasonSplit, { hits, tokens });
    const lists = hits ? ` ${side(first, firstN, firstKey)} ${side(second, secondN, secondKey)}` : '';
    const verdict = tr.band === 'Too few words' ? b.tooFewNote
      : firstN === secondN ? b.reasonTie
      : fill(b.reasonWinner, { x: b.listOf.replace('{x}', firstN > secondN ? first : second) });
    return `${count}${lists} ${verdict}`;
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
        const conf = tt.confidence
          ? `${this.esc(b.confidenceLevels[tt.confidence])} ${this.esc(b.confidenceLabel)}` : '';
        return `<tr><td>${this.esc(b.traitNames[tr])} (${tr})</td>
          <td>${this.esc(this.bandLabel(tt.band))}</td>
          <td>${this.esc(this.dictValue(tr, tt))}
            <div class="rat">${this.esc(this.dictExplain(tr, tt, d.lta.tokens, Infinity))}</div></td><td>${conf}</td></tr>`;
      }).join('');
      const vicsRows = this.vicsList().map((v) =>
        `<tr><td>${this.esc(v.code)}</td><td>${v.value.toFixed(2)}</td></tr>`).join('');
      word = `<h2>${this.esc(b.pdfWordHeading)}</h2>
        <p class="rat">${this.esc(b.wordBlockDesc)}</p>
        <h3>${this.esc(b.personalityHeading)}</h3>
        <p>${this.esc(b.textLengthLabel)}: ${d.lta.tokens}</p>
        <table>${traitRows}</table>
        <p>${this.esc(b.wordConfNote)}</p>
        <h3>${this.esc(b.politicsHeading)}</h3>
        ${d.vics_supported === false
          ? `<p>${this.esc(b.vicsEnglishOnly)}</p>` : `<table>${vicsRows}</table>`}`;
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
      const excerpt = l.excerpted ? `<p class="rat">${this.esc(this.excerptNote(l.excerpted))}</p>` : '';
      ai = `<h2>${this.esc(b.pdfAiHeading)}</h2>
        <p class="rat">${this.esc(b.aiBlockDesc)}</p>${excerpt}${style}${summ}${rows}`;
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
      stake = `<h2>${this.esc(b.stakeHeading)}${st.method === 'llm' ? ` (${this.esc(b.pdfAiHeading)})` : ''}</h2>
        <p>${this.esc(b.stakeIntro)}</p>
        ${st.excerpted ? `<p class="rat">${this.esc(this.excerptNote(st.excerpted))}</p>` : ''}${rows}`;
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
        .quote { white-space: pre-line; background: #f6f6f6; border: 1px solid #ddd;
          border-radius: 6px; padding: 10px 12px; font-size: 12px; line-height: 1.8; }
        .hl { padding: 0 1px 3px; border-radius: 2px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        .hl-legend { font-size: 11px; line-height: 2; margin: 6px 0; }
        .hl-legend .hl { margin-inline-end: 10px; }
        .ai-row { margin: 8px 0; }
        .rat { color: #333; font-size: 12px; margin: 2px 0 0; }
        .foot { margin-top: 28px; color: #888; font-size: 11px; }
      </style></head><body>
      <h1>${this.esc(b.pdfDocTitle)}</h1>
      <h2>${this.esc(b.pdfInputHeading)}</h2>
      ${this.inputLang() ? `<p>${this.esc(b.inputLangLabel)} ${this.esc(this.inputLang())}</p>` : ''}
      ${this.analyzedSpeech() ? `<p><strong>${this.esc(b.speakerLabel)}</strong> ${this.esc(this.analyzedSpeech())}</p>` : ''}
      ${this.analyzedMixed() ? `<p><strong>⚠ ${this.esc(b.mixedWarning)}</strong></p>` : ''}
      ${this.highlightLegend().some((l) => !l.hidden) ? `<p class="hl-legend">${this.highlightLegend()
        .filter((l) => !l.hidden)
        .map((l) => `<span class="hl" style="${l.style}">${this.esc(l.name)} (${l.count})</span>`).join('')}</p>
        <p class="rat">${this.esc(b.highlightKey)}</p>` : ''}
      <div class="quote" dir="auto">${this.highlightPieces().map((p) => p.style
        ? `<span class="hl" style="${p.style}">${this.esc(p.text)}</span>` : this.esc(p.text)).join('')}</div>
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
