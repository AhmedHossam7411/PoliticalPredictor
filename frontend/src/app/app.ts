import { Component, inject, signal, computed, effect } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgTemplateOutlet } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { LANGS, Lang } from './i18n';

// Backend URL. Overridden in production by setting window.__API_URL__ in
// index.html (to the deployed backend); defaults to the local dev server.
declare global {
  interface Window { __API_URL__?: string }
}
const API = window.__API_URL__ || 'http://127.0.0.1:8000';
// Seven clearly different hues, so no two traits look alike in the text.
const TRAIT_COLORS: Record<string, string> = {
  BACE: '#2563eb', PWR: '#dc2626', CC: '#9333ea', SC: '#f59e0b',
  TASK: '#16a34a', DIS: '#db2777', IGB: '#0891b2',
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

/** Solid fill = high/problem-solving/one-list word; striped fill = low/relationship.
 *  Every list adds a thick underline in its colour, so a word on two lists has two. */
const SKIPPED = new Set(['other', 'denied']);
const isSkipped = (label: string) => SKIPPED.has(label.split(':')[1]);

function highlightStyle(labels: string[]): string {
  // A BACE/PWR word the scorer left out: dashed outline only, no fill.
  const counted = labels.filter((l) => !isSkipped(l));
  if (!counted.length) {
    const c = TRAIT_COLORS[labels[0].split(':')[0]];
    return `background:transparent;box-shadow:none;outline:1.5px dashed ${c};outline-offset:-1px;opacity:.75;`;
  }
  labels = counted;
  const [trait, pole] = labels[0].split(':');
  const c = TRAIT_COLORS[trait];
  const lines = labels.map((l, i) => `inset 0 ${-3 * (i + 1)}px 0 ${TRAIT_COLORS[l.split(':')[0]]}`);
  const fill = pole === 'low'
    ? `background:repeating-linear-gradient(135deg,${c}55 0 3px,${c}14 3px 6px);`
    : `background:${c}4d;`;
  return `${fill}box-shadow:${lines.join(',')};`;
}

interface DictTrait { kind: string; value: number; band: string; count?: number;
  high?: number; low?: number; task?: number; group?: number;
  // Evidence weighting: band uses `adjusted`; confidence = how much text backs it.
  adjusted?: number; raw_band?: string; confidence?: 'low' | 'medium' | 'high';
  percent?: number; hits?: number;
  // BACE/PWR words on the list but not counted: someone else acts, or it's denied.
  skipped?: { other: number; denied: number };
  skipped_matches?: { other: Record<string, number>; denied: Record<string, number> };
  // Words found: {word: count}, or per list for the two-list traits.
  matches?: Record<string, number> | Record<string, Record<string, number>>; }
// One counted word: character offsets (code points) and lists, e.g. "CC:high".
interface WordSpan { start: number; end: number; labels: string[]; }
// One speaker's text from a document holding several ("chair" = the chair's short remarks).
interface Speech { id: string; speaker: string; title: string | null; spoke_in: string | null;
  kind: 'speech' | 'chair'; words: number; text: string; }
interface HighlightPiece { text: string; style: string; title: string; ent?: boolean; }
// A highlight with its context-check state: left out, or a country/organization name.
interface MarkSpan extends WordSpan { ignored?: boolean; ent?: string; }
type Tone = 'positive' | 'negative' | 'mixed' | 'neutral';
interface EntityRef { key: string; name: string; name_ar: string;
  kind: 'country' | 'organization' | 'continent' | 'region' | 'sea' | 'strait' | 'route'; }
interface EntitySpan { start: number; end: number; key: string; }
interface EntityStatement { sentence: number; text: string; tone: Tone; source: string;
  speech?: string; added?: string | null; }
interface EntitySummary extends EntityRef { count: number; tone: Tone; counts: Record<Tone, number>;
  statements: EntityStatement[]; }
// Context check: sentences with marked words or names, and the decisions about them.
interface ReviewHit { id: number; start: number; end: number; word: string; labels: string[]; counted: boolean; }
interface ReviewEntity extends EntityRef { start: number; end: number; tone: Tone; }
interface ReviewSentence { i: number; start: number; end: number; text: string;
  hits: ReviewHit[]; entities: ReviewEntity[]; }
interface Review { sentences: ReviewSentence[]; hit_count: number; language: string; total_sentences: number; }
interface ToneDecision { sentence: number; entity: string; tone: string; source?: string; }
// A trait added for a whole sentence, or (with start/end/text) for one part of it.
interface AddDecision { sentence: number; label: string; start?: number; end?: number; text?: string; }
interface Decisions { ignore: number[]; count: number[]; confirm: number[]; add: AddDecision[];
  tones: ToneDecision[]; noWhole?: number[]; }
interface AiJob { id: string; status: 'running' | 'done' | 'failed' | 'cancelled'; done: number; total: number;
  decisions: { ignore: number[]; count?: number[]; confirm?: number[]; add: AddDecision[]; tones: ToneDecision[] };
  // reused: sentences filled in from saved decisions; examples: saved sentences shown to Karnak.
  reviewed: number[]; reused?: number[]; examples?: number; error: string; }
interface SentencePiece { text: string; hit?: ReviewHit; ent?: ReviewEntity; }
// What a stakeholder thinks of a country/organization the analyzed text names.
interface View extends EntityRef { tone: Tone; source: 'speeches' | 'profile'; statements?: number; note?: string; }
interface InputInfo { language: 'en' | 'ar'; dialect: 'msa' | 'egyptian' | 'mixed' | null; }
interface DictResult {
  input?: InputInfo; vics_supported?: boolean;
  lta: { tokens: number; traits: Record<string, DictTrait> };
  spans?: WordSpan[];
  entities?: EntitySpan[]; entity_summary?: EntitySummary[];
  context?: { ignored: number; counted: number; added: number; toned: number };
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
  confidence: number; reasoning: string; response: string; views?: View[]; }
interface StakeResult { reactions: Reaction[]; method: string; model?: string;
  calibrated?: boolean; fallback_reason?: string; excerpted?: Excerpted | null;
  read_in_parts?: { parts: number; total_words: number } | null; }
interface PublicStakeholder { id: string; name: string; role: string; scope?: string;
  personality?: string; values: string[]; supports: string[]; opposes: string[];
  concerns: string[]; custom: boolean; }
interface SpeechOpt { id: string; label: string; }
interface NewsItem { title: string; url: string; source: string; domain: string; published: string; }
// A partner or rival; `country` is set when it is a country the user can click.
interface Relation { label: string; country: string | null; country_name: string | null; }
interface DossierProfile { country: string; cc: string; name_local: string;
  official: { name: string; url: string }[]; background: string; leadership_style: string;
  personality_type: string[]; memberships: string[]; partners: Relation[]; frictions: Relation[]; }
// The word scorer run on this person's own speeches: one result per language.
interface WordProfileResult { language: 'en' | 'ar'; speeches: number; tokens: number;
  traits: Record<string, { band: string; percent: number; confidence?: string }>; }
interface WordProfile { results: WordProfileResult[];
  speeches: { id: string; title: string; words: number; language: string; removable: boolean }[]; }
interface Dossier { id: string; person: PublicStakeholder; profile: DossierProfile | null;
  news: { domestic: NewsItem[]; international: NewsItem[]; speeches: NewsItem[] };
  errors: string[]; word_profile: WordProfile; entities?: EntitySummary[]; }
interface Mention extends NewsItem { tone: Tone; cues: string[]; place: string | null; }
interface Mentions { country: string; country_name: string; country_name_ar: string;
  items: Mention[]; total: number; counts: Record<Tone, number>; errors: string[]; }

// Context check: the codes for a word list (pole included) and back.
const LABEL_OF_CODE: Record<string, string> = {
  BACE: 'BACE:high', PWR: 'PWR:high', 'SC+': 'SC:high', 'SC-': 'SC:low', 'CC+': 'CC:high',
  'CC-': 'CC:low', TASK: 'TASK:high', REL: 'TASK:low', DIS: 'DIS:high', IGB: 'IGB:high' };
const CODE_OF_LABEL: Record<string, string> = Object.fromEntries(
  Object.entries(LABEL_OF_CODE).map(([code, label]) => [code, label]).map(([c, l]) => [l, c]));
const IGNORED_STYLE = 'background:transparent;box-shadow:none;text-decoration:line-through;opacity:.5;';
const noDecisions = (): Decisions => ({ ignore: [], count: [], confirm: [], add: [], tones: [] });
const toggled = (list: number[], id: number) => list.includes(id) ? list.filter((x) => x !== id) : [...list, id];

@Component({
  selector: 'app-root',
  imports: [FormsModule, NgTemplateOutlet],
  host: { '(document:keydown.escape)': 'onEscape()' },
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
  removedStakeholders = signal<{ id: string; name: string }[]>([]);
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
  /** Says the AI read a long document whole, part by part. */
  partsNote(p?: { parts: number; total_words: number } | null): string {
    if (!p) return '';
    return this.t().aiPartsNote.replace('{parts}', String(p.parts))
      .replace('{total}', p.total_words.toLocaleString('en-US'));
  }

  excerptNote(excerpted?: Excerpted | null): string {
    if (!excerpted) return '';
    const fmt = (n: number) => n.toLocaleString('en-US');
    return this.t().aiExcerptNote.replace('{read}', fmt(excerpted.read_words)).replace('{total}', fmt(excerpted.total_words));
  }

  /** Display name of a word list, e.g. "Conceptual Complexity: High list". */
  private listName(label: string): string {
    const b = this.t();
    const [trait, pole] = label.split(':');
    if (pole === 'other') return `${b.traitNames[trait]}: ${b.skippedOther}`;
    if (pole === 'denied') return `${b.traitNames[trait]}: ${b.skippedDenied}`;
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
    return this.traits.flatMap((tr) => [`${tr}:high`, `${tr}:low`, `${tr}:other`, `${tr}:denied`])
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
    const same = this.dictText() === text;
    const ign = this.ignoredSet(), cnt = this.countedSet(), ids = this.hitIdAt();
    const spans: MarkSpan[] = (same ? this.dict()?.spans ?? [] : []).map((s): MarkSpan => {
      const id = ids.get(`${s.start}:${s.end}`);
      if (id !== undefined && ign.has(id)) return { ...s, labels: [], ignored: true };
      // A left-out BACE/PWR word someone chose to count shows as counted.
      const labels = id !== undefined && cnt.has(id)
        ? s.labels.map((l) => isSkipped(l) ? `${l.split(':')[0]}:high` : l) : s.labels;
      return { ...s, labels: labels.filter((l) => !hidden.has(l)) };
    }).filter((s) => s.labels.length || s.ignored);
    if (same && !hidden.has('ENT')) {
      for (const e of this.dict()?.entities ?? []) spans.push({ start: e.start, end: e.end, labels: [], ent: e.key });
    }
    const cuts = [...new Set([0, chars.length, ...spans.flatMap((s) => [s.start, s.end])])].sort((a, b) => a - b);
    // Walk the cuts in order, tracking which spans are open: a long document has
    // thousands of them, and checking every span at every cut freezes the page.
    const ordered = [...spans].sort((a, b) => a.start - b.start);
    let open: MarkSpan[] = [];
    let next = 0;
    return cuts.slice(0, -1).map((start, i) => {
      const end = cuts[i + 1];
      open = open.filter((s) => s.end > start);
      while (next < ordered.length && ordered[next].start <= start) open.push(ordered[next++]);
      const labels = [...new Set(open.flatMap((s) => s.labels))];
      const ent = open.find((s) => s.ent)?.ent;
      const ignored = !labels.length && open.some((s) => s.ignored);
      const names = labels.map((l) => this.listName(l));
      if (ent) names.unshift(this.entName(this.entityRef(ent)));
      if (ignored) names.push(this.t().cx['wordOff']);
      return { text: chars.slice(start, end).join(''), ent: !!ent,
               style: labels.length ? highlightStyle(labels) : ignored ? IGNORED_STYLE : '',
               title: names.join('\n') };
    });
  });

  // --- Context check ---------------------------------------------------------
  review = signal<Review | null>(null);
  decisions = signal<Decisions>(noDecisions());
  fromAi = signal<ReadonlySet<string>>(new Set());   // decisions Karnak made: 'i:3', 'a:5:SC:high', 't:5:UN'
  touched = signal<ReadonlySet<number>>(new Set());  // sentences a person changed; Karnak leaves them alone
  aiJob = signal<AiJob | null>(null);
  cxShown = signal(20);
  cxFilter = signal<'all' | 'changed' | 'names'>('all');
  cxMsg = signal('');
  cxCodes = Object.keys(LABEL_OF_CODE);
  readonly Math = Math;
  readonly tones4: Tone[] = ['positive', 'negative', 'mixed', 'neutral'];
  entOpen = signal('');
  saveSid = signal(''); saveMsg = signal(''); saveBusy = signal(false);
  private aiTimer: ReturnType<typeof setTimeout> | null = null;
  private rescoreSeq = 0;

  ignoredSet = computed(() => new Set(this.decisions().ignore));
  countedSet = computed(() => new Set(this.decisions().count));
  private hitSentence = computed(() => {
    const m = new Map<number, number>();
    for (const s of this.review()?.sentences ?? []) for (const h of s.hits) m.set(h.id, s.i);
    return m;
  });
  hitIdAt = computed(() => {
    const m = new Map<string, number>();
    for (const s of this.review()?.sentences ?? []) for (const h of s.hits) m.set(`${h.start}:${h.end}`, h.id);
    return m;
  });
  changedSentences = computed(() => {
    const d = this.decisions(), hs = this.hitSentence(), out = new Set<number>();
    for (const id of [...d.ignore, ...d.count]) { const si = hs.get(id); if (si !== undefined) out.add(si); }
    for (const a of d.add) out.add(a.sentence);
    for (const t of d.tones) out.add(t.sentence);
    return out;
  });
  cxList = computed(() => {
    const f = this.cxFilter(), changed = this.changedSentences();
    return (this.review()?.sentences ?? []).filter((s) =>
      f === 'all' || (f === 'changed' ? changed.has(s.i) : s.entities.length > 0));
  });
  cxPieces = computed(() => {
    // Key `${sentence}:${hit}`: the sentence with only that word marked ('-' = no word).
    const out = new Map<string, SentencePiece[]>();
    for (const s of this.review()?.sentences ?? []) {
      for (const one of s.hits.length ? s.hits : [null]) out.set(`${s.i}:${one ? one.id : '-'}`, this.piecesOf(s, one));
    }
    return out;
  });

  private piecesOf(s: ReviewSentence, one: ReviewHit | null): SentencePiece[] {
    {
      const chars = Array.from(s.text);
      const marks = [
        ...(one ? [{ start: one.start - s.start, end: one.end - s.start, hit: one, ent: undefined }] : []),
        ...s.entities.map((e) => ({ start: e.start - s.start, end: e.end - s.start, hit: undefined, ent: e })),
      ].sort((a, b) => a.start - b.start);
      const pieces: SentencePiece[] = [];
      let pos = 0;
      for (const m of marks) {
        if (m.start < pos) continue;
        if (m.start > pos) pieces.push({ text: chars.slice(pos, m.start).join('') });
        pieces.push({ text: chars.slice(m.start, m.end).join(''), hit: m.hit, ent: m.ent });
        pos = m.end;
      }
      if (pos < chars.length) pieces.push({ text: chars.slice(pos).join('') });
      return pieces;
    }
  }

  /** The word lists the first reading put this word on, e.g. "Conceptual Complexity: Low list". */
  initialOf(h: ReviewHit): string { return h.labels.map((l) => this.listName(l)).join(' + '); }

  /** 'right' = ticked as correct; 'wrong' = the first reading was overturned; '' = not decided. */
  verdict(h: ReviewHit): 'right' | 'wrong' | '' {
    const d = this.decisions();
    if (d.confirm.includes(h.id)) return 'right';
    if (h.counted ? d.ignore.includes(h.id) : d.count.includes(h.id) && !d.ignore.includes(h.id)) return 'wrong';
    return '';
  }

  markRight(s: ReviewSentence, h: ReviewHit) {
    const again = this.verdict(h) === 'right';
    this.change(s.i, (d) => ({ ...d,
      confirm: again ? d.confirm.filter((x) => x !== h.id) : [...new Set([...d.confirm, h.id])],
      ignore: d.ignore.filter((x) => x !== h.id), count: d.count.filter((x) => x !== h.id) }));
  }

  markWrong(s: ReviewSentence, h: ReviewHit) {
    const again = this.verdict(h) === 'wrong';
    this.change(s.i, (d) => {
      const base = { ...d, confirm: d.confirm.filter((x) => x !== h.id),
                     ignore: d.ignore.filter((x) => x !== h.id), count: d.count.filter((x) => x !== h.id) };
      if (again) return base;
      return h.counted ? { ...base, ignore: [...base.ignore, h.id] } : { ...base, count: [...base.count, h.id] };
    });
  }

  // --- A part of a sentence, selected with the mouse ---------------------------
  partSel = signal<{ si: number; start: number; end: number; text: string } | null>(null);

  pickPart(s: ReviewSentence, ev: Event) {
    const el = ev.currentTarget as HTMLElement;
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    const r = sel.getRangeAt(0);
    if (!el.contains(r.startContainer) || !el.contains(r.endContainer)) return;
    const pre = document.createRange();
    pre.selectNodeContents(el);
    pre.setEnd(r.startContainer, r.startOffset);
    const picked = r.toString();
    // The paragraph shows exactly the sentence's text; fall back to a search if not.
    let at = (el.textContent ?? '') === s.text ? pre.toString().length : s.text.indexOf(picked);
    if (at < 0 || !picked.trim()) return;
    const lead = picked.length - picked.trimStart().length;
    const text = picked.trim();
    at += lead;
    // Offsets count code points, like the server's.
    const start = s.start + Array.from(s.text.slice(0, at)).length;
    this.partSel.set({ si: s.i, start, end: start + Array.from(text).length, text });
  }

  addPart(s: ReviewSentence, code: string) {
    const part = this.partSel(), label = LABEL_OF_CODE[code];
    if (!part || part.si !== s.i || !label) return;
    this.change(s.i, (d) => ({ ...d, add: [...d.add, { sentence: s.i, label, start: part.start, end: part.end, text: part.text }] }));
    this.partSel.set(null);
    window.getSelection()?.removeAllRanges();
  }

  partsOf(s: ReviewSentence) { return this.decisions().add.filter((a) => a.sentence === s.i && a.start !== undefined); }

  removePart(s: ReviewSentence, part: AddDecision) {
    this.change(s.i, (d) => ({ ...d, add: d.add.filter((a) => a !== part) }));
  }

  aiStatus = computed(() => {
    const j = this.aiJob(), cx = this.t().cx;
    if (!j) return this.meta()?.llm_available === false ? cx['aiOff'] : '';
    if (j.status === 'running') return j.total ? cx['aiRunning'].replace('{done}', String(j.done)).replace('{total}', String(j.total)) : cx['aiStarting'];
    if (j.status === 'failed') return cx['aiFailed'].replace('{err}', j.error || '?');
    if (j.status === 'cancelled') return cx['aiCancelled'];
    return cx['aiDone'].replace('{ignored}', String(j.decisions.ignore.length))
      .replace('{added}', String(j.decisions.add.length)).replace('{toned}', String(j.decisions.tones.length));
  });
  contextNote = computed(() => {
    const c = this.dict()?.context;
    if (!c || !(c.ignored || c.counted || c.added)) return '';
    return this.t().cx['applied'].replace('{ignored}', String(c.ignored))
      .replace('{counted}', String(c.counted)).replace('{added}', String(c.added));
  });

  private loadReview(text: string) {
    this.stopAi(true);
    this.review.set(null);
    this.decisions.set(noDecisions());
    this.fromAi.set(new Set()); this.touched.set(new Set());
    this.cxShown.set(20); this.cxFilter.set('all'); this.cxMsg.set(''); this.saveMsg.set('');
    this.partSel.set(null);
    this.http.post<Review>(`${API}/context/review`, { text }).subscribe({
      next: (r) => {
        if (this.dictText() !== text) return;
        this.review.set(r);
        if (r.sentences.length && this.meta()?.llm_available !== false) this.startAi(text);
        else this.releaseAi();
      },
      error: () => this.releaseAi(),  // the plain word-scorer result still stands
    });
  }

  startAi(text: string = this.dictText()) {
    this.stopAi(true);
    this.aiJob.set({ id: '', status: 'running', done: 0, total: 0,
      decisions: { ignore: [], add: [], tones: [] }, reviewed: [], error: '' });
    this.http.post<{ job: string }>(`${API}/context/ai`, { text }).subscribe({
      next: ({ job }) => { this.aiJob.update((j) => j && { ...j, id: job }); this.pollAi(job, text, 1500); },
      error: (e) => { this.aiJob.update((j) => j && { ...j, status: 'failed', error: this.msg(e) }); this.releaseAi(); },
    });
  }

  private pollAi(id: string, text: string, wait = 4000) {
    this.aiTimer = setTimeout(() => {
      this.http.get<AiJob>(`${API}/context/ai/${id}`).subscribe({
        next: (j) => {
          if (this.dictText() !== text || this.aiJob()?.id !== id) return;
          this.aiJob.set(j);
          this.mergeAi(j.decisions);
          if (j.status === 'running') this.pollAi(id, text);
          else this.releaseAi();
        },
        error: (e) => { this.aiJob.update((j) => j && { ...j, status: 'failed', error: this.msg(e) }); this.releaseAi(); },
      });
    }, wait);
  }

  stopAi(cancelOnServer = false) {
    if (this.aiTimer) { clearTimeout(this.aiTimer); this.aiTimer = null; }
    const j = this.aiJob();
    if (j?.status === 'running') {
      if (cancelOnServer && j.id) this.http.delete(`${API}/context/ai/${j.id}`).subscribe({ error: () => {} });
      this.aiJob.set({ ...j, status: 'cancelled' });
    }
    // Stopping the check by hand lets the AI traits and reactions start now.
    if (cancelOnServer && this.dictText() === this.aiQueued()) this.releaseAi();
  }

  /** Take in Karnak's new decisions, except on sentences a person already changed. */
  private mergeAi(ai: AiJob['decisions']) {
    const d = this.decisions(), touched = this.touched(), hs = this.hitSentence();
    const mark = new Set(this.fromAi());
    const next: Decisions = { ignore: [...d.ignore], count: [...d.count], confirm: [...d.confirm],
                              add: [...d.add], tones: [...d.tones] };
    let changed = false;
    const takeIds = (ids: number[] | undefined, kind: 'ignore' | 'count' | 'confirm', tag: string) => {
      for (const id of ids ?? []) {
        const si = hs.get(id), k = `${tag}:${id}`;
        if (si === undefined || touched.has(si) || mark.has(k)) continue;
        mark.add(k);
        if (!next[kind].includes(id)) { next[kind].push(id); changed = true; }
      }
    };
    takeIds(ai.ignore, 'ignore', 'i');
    takeIds(ai.count, 'count', 'c');
    takeIds(ai.confirm, 'confirm', 'r');
    for (const a of ai.add) {
      const k = `a:${a.sentence}:${a.label}:${a.start ?? ''}`;
      if (touched.has(a.sentence) || mark.has(k)) continue;
      if (a.start === undefined && next.noWhole?.includes(a.sentence)) continue;
      mark.add(k);
      if (!next.add.some((x) => x.sentence === a.sentence && x.label === a.label && x.start === a.start)) {
        next.add.push(a); changed = true;
      }
    }
    for (const t of ai.tones) {
      const k = `t:${t.sentence}:${t.entity}`;
      if (touched.has(t.sentence) || mark.has(k)) continue;
      mark.add(k);
      next.tones = [...next.tones.filter((x) => !(x.sentence === t.sentence && x.entity === t.entity)),
                    { ...t, source: 'ai' }];
      changed = true;
    }
    this.fromAi.set(mark);
    if (changed) { this.decisions.set(next); this.rescore(); }
  }

  /** Score the text again with the decisions; the newest request wins. */
  private rescore() {
    const text = this.dictText(), seq = ++this.rescoreSeq;
    this.http.post<DictResult>(`${API}/context/rescore`, { text, decisions: this.decisions() }).subscribe({
      next: (r) => { if (seq === this.rescoreSeq && this.dictText() === text) this.dict.set(r); },
      error: (e) => this.error.set(this.msg(e)),
    });
  }

  private change(si: number, update: (d: Decisions) => Decisions) {
    this.touched.set(new Set([...this.touched(), si]));
    this.decisions.set(update(this.decisions()));
    this.rescore();
  }

  hitOn(h: ReviewHit): boolean {
    return h.counted ? !this.ignoredSet().has(h.id) : this.countedSet().has(h.id) && !this.ignoredSet().has(h.id);
  }

  hitStyle(h: ReviewHit): string {
    if (!this.hitOn(h)) return h.counted ? IGNORED_STYLE : highlightStyle(h.labels);
    return highlightStyle(h.labels.map((l) => isSkipped(l) ? `${l.split(':')[0]}:high` : l));
  }

  hitTitle(h: ReviewHit): string {
    const cx = this.t().cx;
    const lists = h.labels.map((l) => this.listName(l)).join(', ');
    return `${lists}\n${this.hitOn(h) ? cx['wordOn'] : h.counted ? cx['wordOff'] : cx['wordSkipped']}`;
  }

  sentenceIgnored(s: ReviewSentence): boolean {
    const counted = s.hits.filter((h) => h.counted);
    return counted.length > 0 && counted.every((h) => this.ignoredSet().has(h.id));
  }

  toggleSentence(s: ReviewSentence) {
    const ids = s.hits.filter((h) => h.counted).map((h) => h.id);
    const all = s.hits.map((h) => h.id);
    const off = this.sentenceIgnored(s);
    this.change(s.i, (d) => off
      ? { ...d, ignore: d.ignore.filter((x) => !ids.includes(x)) }
      : { ...d, ignore: [...new Set([...d.ignore, ...ids])], count: d.count.filter((x) => !all.includes(x)),
          confirm: d.confirm.filter((x) => !all.includes(x)), add: d.add.filter((a) => a.sentence !== s.i) });
  }

  /** The whole-sentence option is off for this sentence: only word and part choices count. */
  wholeOff(s: ReviewSentence): boolean { return !!this.decisions().noWhole?.includes(s.i); }

  dropWhole(s: ReviewSentence) {
    this.change(s.i, (d) => ({ ...d, noWhole: [...new Set([...(d.noWhole ?? []), s.i])],
      add: d.add.filter((a) => !(a.sentence === s.i && a.start === undefined)) }));
  }

  undoWhole(s: ReviewSentence) {
    this.change(s.i, (d) => ({ ...d, noWhole: (d.noWhole ?? []).filter((x) => x !== s.i) }));
  }

  kindName(kind: string): string { return this.t().cx['kind_' + kind] ?? ''; }

  addsOf(s: ReviewSentence) { return this.decisions().add.filter((a) => a.sentence === s.i && a.start === undefined); }

  addTrait(s: ReviewSentence, code: string) {
    const label = LABEL_OF_CODE[code];
    if (!label) return;
    this.change(s.i, (d) => d.add.some((a) => a.sentence === s.i && a.label === label && a.start === undefined) ? d
      : { ...d, add: [...d.add, { sentence: s.i, label }] });
  }

  removeAdd(s: ReviewSentence, label: string) {
    this.change(s.i, (d) => ({ ...d, add: d.add.filter((a) => !(a.sentence === s.i && a.label === label && a.start === undefined)) }));
  }

  codeName(label: string): string {
    const code = CODE_OF_LABEL[label] ?? label;
    return `${code} · ${this.t().cxCodes[code] ?? ''}`;
  }

  toneAt(si: number, key: string, fallback: string): string {
    return this.decisions().tones.find((t) => t.sentence === si && t.entity === key)?.tone ?? fallback;
  }

  setTone(si: number, key: string, tone: string) {
    this.change(si, (d) => ({ ...d, tones: [...d.tones.filter((t) => !(t.sentence === si && t.entity === key)),
                                            { sentence: si, entity: key, tone, source: 'person' }] }));
  }

  /** Karnak made this decision and nobody has changed the sentence since. */
  byAi(key: string, si: number): boolean { return this.fromAi().has(key) && !this.touched().has(si); }

  sentenceByAi(s: ReviewSentence): boolean {
    if (this.touched().has(s.i)) return false;
    const m = this.fromAi();
    if (this.aiJob()?.reused?.includes(s.i)) return false;
    return s.hits.some((h) => m.has(`i:${h.id}`) && this.ignoredSet().has(h.id))
      || this.addsOf(s).some((a) => m.has(`a:${s.i}:${a.label}:`))
      || this.decisions().tones.some((t) => t.sentence === s.i && t.source === 'ai');
  }

  /** This sentence was decided before and its saved decisions were applied again. */
  sentenceReused(s: ReviewSentence): boolean {
    return !this.touched().has(s.i) && !!this.aiJob()?.reused?.includes(s.i);
  }

  memoryNote = computed(() => {
    const j = this.aiJob();
    if (!j || !(j.reused?.length || j.examples)) return '';
    return this.t().cx['memory'].replace('{reused}', String(j.reused?.length ?? 0))
      .replace('{examples}', String(j.examples ?? 0));
  });

  saveLabels() {
    const source = this.fromAi().size ? (this.touched().size ? 'ai+person' : 'ai') : 'person';
    this.http.post<{ saved: number; total: number }>(`${API}/context/labels`,
      { text: this.dictText(), decisions: this.decisions(), source }).subscribe({
      next: (r) => this.cxMsg.set(this.t().cx['savedLabels'].replace('{n}', String(r.saved)).replace('{total}', String(r.total))),
      error: (e) => this.cxMsg.set(this.msg(e)),
    });
  }

  saveToFile() {
    const sid = this.saveSid();
    const who = this.stakeholders().find((s) => s.id === sid);
    if (!who) return;
    this.saveBusy.set(true); this.saveMsg.set('');
    this.http.post(`${API}/stakeholders/${encodeURIComponent(sid)}/speeches`,
      { text: this.dictText(), title: this.analyzedSpeech() || this.uploadedName() || '', context: this.decisions() }).subscribe({
      next: () => { this.saveBusy.set(false); this.saveMsg.set(this.t().cx['savedTo'].replace('{name}', who.name)); },
      error: (e) => { this.saveBusy.set(false); this.saveMsg.set(e?.error?.detail || this.msg(e)); },
    });
  }

  // --- Countries and organizations ---------------------------------------------
  entName(e: { name: string; name_ar: string } | null | undefined): string {
    if (!e) return '';
    return this.lang() === 'ar' ? e.name_ar : e.name;
  }

  entityRef(key: string): EntityRef | null {
    const all = [...(this.dict()?.entity_summary ?? [])];
    return all.find((e) => e.key === key) ?? null;
  }

  entTimes(n: number): string { return this.t().cx['entTimes'].replace('{n}', String(n)); }

  toneSource(src: string): string { return this.t().cx['src' + src] ?? ''; }

  viewTitle(v: View): string {
    const cx = this.t().cx;
    return v.source === 'speeches' ? cx['viewSpeeches'].replace('{n}', String(v.statements ?? 0))
      : cx['viewProfile'].replace('{note}', v.note ?? '');
  }

  // What one stakeholder said about one country/organization, from their speeches on file.
  entModal = signal<{ who: string; data: EntitySummary } | null>(null);
  entModalLoading = signal(false);
  entModalError = signal('');

  openEntity(sid: string, who: string, key: string) {
    this.entModal.set(null); this.entModalError.set(''); this.entModalLoading.set(true);
    this.http.get<EntitySummary>(`${API}/stakeholders/${encodeURIComponent(sid)}/entities/${encodeURIComponent(key)}`).subscribe({
      next: (data) => { this.entModal.set({ who, data }); this.entModalLoading.set(false); },
      error: (e) => { this.entModalError.set(e?.error?.detail || this.msg(e)); this.entModalLoading.set(false); },
    });
  }

  closeEntity() { this.entModal.set(null); this.entModalError.set(''); this.entModalLoading.set(false); }

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
    return d ? this.bandSummary(d.lta.traits) : '';
  });

  /** "Higher than usual: … Lower than usual: … Task focus: …" from the bands. */
  bandSummary(traits: Record<string, { band: string }>): string {
    const b = this.t();
    const highs = this.traits.filter((tr) => traits[tr]?.band === 'High');
    const lows = this.traits.filter((tr) => traits[tr]?.band === 'Low');
    const name = (tr: string) => b.traitNames[tr];
    const parts: string[] = [];
    if (highs.length) parts.push(`${b.higher} ${highs.map(name).join(', ')}.`);
    if (lows.length) parts.push(`${b.lower} ${lows.map(name).join(', ')}.`);
    const task = traits['TASK']?.band;
    if (task && task !== 'Balanced' && task !== 'Too few words') parts.push(`${name('TASK')}: ${this.bandLabel(task)}.`);
    return parts.join(' ') || b.wpUsual;
  }

  constructor() {
    // Resume an existing session if a token is already stored.
    effect(() => this.saveState());
    if (sessionStorage.getItem('pp_token')) {
      this.authed.set(true);
      this.loadInitialData();
      this.restoreState();
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
    this.http.get<{ stakeholders: PublicStakeholder[]; removed: { id: string; name: string }[] }>(
      `${API}/stakeholders`).subscribe({
      next: (r) => { this.stakeholders.set(r.stakeholders); this.removedStakeholders.set(r.removed); },
      error: () => {},
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

  // --- Stakeholder profile pop-up -----------------------------------------
  dossierOpen = signal(false);
  dossierName = signal('');
  dossier = signal<Dossier | null>(null);
  dossierLoading = signal(false);
  dossierError = signal('');
  private dossierFor = '';

  openDossier(id: string, name: string) {
    this.dossierFor = id;
    this.dossierName.set(name);
    this.dossier.set(null); this.dossierError.set(''); this.dossierLoading.set(true);
    this.wpFormOpen.set(false); this.wpText.set(''); this.wpTitle.set(''); this.wpError.set('');
    this.dossierOpen.set(true);
    document.body.style.overflow = 'hidden';
    setTimeout(() => document.getElementById('dz-close')?.focus());
    this.http.get<Dossier>(`${API}/stakeholders/${encodeURIComponent(id)}/dossier`,
      { params: { language: this.lang() } }).subscribe({
      next: (d) => { if (this.dossierFor === id) { this.dossier.set(d); this.dossierLoading.set(false); } },
      error: (e) => { if (this.dossierFor === id) { this.dossierError.set(this.msg(e)); this.dossierLoading.set(false); } },
    });
  }

  // --- Word-scorer profile from the person's own speeches --------------------
  wpFormOpen = signal(false);
  wpText = signal('');
  wpTitle = signal('');
  wpBusy = signal(false);
  wpError = signal('');

  wpBasis(r: WordProfileResult): string {
    return this.t().wpBasis.replace('{n}', String(r.speeches))
      .replace('{words}', r.tokens.toLocaleString('en-US'))
      .replace('{lang}', r.language === 'ar' ? this.t().langAr : this.t().langEn);
  }

  private setWordProfile(wp: WordProfile) {
    const d = this.dossier();
    if (d) this.dossier.set({ ...d, word_profile: wp });
  }

  saveProfileSpeech() {
    const sid = this.dossierFor;
    if (!sid) return;
    this.wpBusy.set(true); this.wpError.set('');
    this.http.post<WordProfile>(`${API}/stakeholders/${encodeURIComponent(sid)}/speeches`,
      { text: this.wpText(), title: this.wpTitle() }).subscribe({
      next: (wp) => {
        this.setWordProfile(wp); this.wpBusy.set(false);
        this.wpText.set(''); this.wpTitle.set(''); this.wpFormOpen.set(false);
      },
      error: (e) => { this.wpError.set(this.msg(e)); this.wpBusy.set(false); },
    });
  }

  removeProfileSpeech(speechId: string) {
    const sid = this.dossierFor;
    if (!sid || !window.confirm(this.t().wpConfirmRemove)) return;
    this.http.delete<WordProfile>(`${API}/stakeholders/${encodeURIComponent(sid)}/speeches/${encodeURIComponent(speechId)}`)
      .subscribe({ next: (wp) => this.setWordProfile(wp), error: (e) => this.wpError.set(this.msg(e)) });
  }

  /** Read a PDF or text file into the speech box (the same reader as the main upload). */
  wpUploadFile(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    this.wpBusy.set(true); this.wpError.set('');
    this.http.post<{ text: string }>(`${API}/extract-text`, file, {
      params: { filename: file.name }, headers: { 'Content-Type': 'application/octet-stream' },
    }).subscribe({
      next: (r) => {
        this.wpText.set(r.text);
        if (!this.wpTitle()) this.wpTitle.set(file.name.replace(/\.[^.]+$/, ''));
        this.wpBusy.set(false);
      },
      error: (e) => {
        const errors = this.t().uploadErrors;
        this.wpError.set(errors[e?.error?.detail] ?? errors['file-unreadable']);
        this.wpBusy.set(false);
      },
    });
  }

  // --- What the stakeholder said about one country -------------------------
  readonly toneOrder: Tone[] = ['positive', 'negative', 'mixed', 'neutral'];
  mentionsOpen = signal(false);
  mentions = signal<Mentions | null>(null);
  mentionsLoading = signal(false);
  mentionsError = signal('');
  mentionsTitle = signal('');
  private mentionsFor = '';

  openMentions(country: string, countryName: string) {
    const sid = this.dossierFor;
    if (!sid) return;
    const key = `${sid}:${country}`;
    this.mentionsFor = key;
    this.mentionsTitle.set(this.t().mzTitle.replace('{name}', this.dossierName()).replace('{country}', countryName));
    this.mentions.set(null); this.mentionsError.set(''); this.mentionsLoading.set(true);
    this.mentionsOpen.set(true);
    setTimeout(() => document.getElementById('mz-close')?.focus());
    this.http.get<Mentions>(`${API}/stakeholders/${encodeURIComponent(sid)}/mentions/${encodeURIComponent(country)}`)
      .subscribe({
        next: (m) => { if (this.mentionsFor === key) { this.mentions.set(m); this.mentionsLoading.set(false); } },
        error: (e) => { if (this.mentionsFor === key) { this.mentionsError.set(this.msg(e)); this.mentionsLoading.set(false); } },
      });
  }

  closeMentions() {
    this.mentionsOpen.set(false);
    this.mentionsFor = '';
    setTimeout(() => document.getElementById('dz-close')?.focus());
  }

  /** Esc closes the top window first. */
  onEscape() {
    if (this.entModal() || this.entModalLoading() || this.entModalError()) { this.closeEntity(); return; }
    if (this.mentionsOpen()) this.closeMentions();
    else this.closeDossier();
  }

  closeDossier() {
    if (!this.dossierOpen()) return;
    this.mentionsOpen.set(false);
    this.dossierOpen.set(false);
    this.dossierFor = '';
    document.body.style.overflow = '';
  }

  initials(name: string): string {
    return name.split(/\s+/).filter((w) => /^\p{Lu}/u.test(w)).slice(0, 2).map((w) => w[0]).join('')
      || name.slice(0, 1);
  }

  shortDate(iso: string): string {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d.getTime()) ? '' : d.toLocaleDateString(this.lang() === 'ar' ? 'ar-EG' : 'en-GB',
      { day: 'numeric', month: 'short', year: 'numeric' });
  }

  deleteStakeholder(s: PublicStakeholder) {
    const ask = s.custom ? this.t().confirmDeleteCustom : this.t().confirmDeleteBuiltin;
    if (!window.confirm(ask.replace('{name}', s.name))) return;
    this.addError.set(''); this.addMsg.set('');
    this.http.delete(`${API}/stakeholders/${encodeURIComponent(s.id)}`).subscribe({
      next: () => { this.loadStakeholders(); this.loadSpeeches(); },
      error: (e) => { this.addError.set(this.msg(e)); },
    });
  }

  restoreStakeholder(id: string) {
    this.addError.set(''); this.addMsg.set('');
    this.http.post(`${API}/stakeholders/${encodeURIComponent(id)}/restore`, {}).subscribe({
      next: () => this.loadStakeholders(),
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
    sessionStorage.removeItem(App.STATE_KEY);
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
    this.aiQueued.set('');
    this.llmJob.set(''); this.stakeJob.set('');
    this.llmLoading.set(false); this.stakeLoading.set(false);
    this.stopAi(true);
    this.review.set(null);
    this.decisions.set(noDecisions());
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
    if (this.meta()?.llm_available === false) {
      this.runDictionary(snapshot);
      this.runStakeholders(snapshot);
      return;
    }
    // Karnak answers one request at a time: let the context check go first, so the
    // word scorer is corrected within minutes; the AI traits and reactions follow.
    this.aiQueued.set(snapshot);
    this.runDictionary(snapshot);
  }

  /** Text waiting for the AI trait scores and stakeholder reactions until the context check ends. */
  aiQueued = signal('');

  private releaseAi() {
    const text = this.aiQueued();
    if (!text) return;
    this.aiQueued.set('');
    this.runLlm(text);
    this.runStakeholders(text);
  }

  runStakeholders(text: string = this.text()) {
    if (!text.trim()) return;
    this.stanceFilter.set('All');
    this.stakeLoading.set(true); this.error.set('');
    this.http.post<{ job: string }>(`${API}/jobs/stakeholders`, { text, language: this.lang() }).subscribe({
      next: ({ job }) => { this.stakeJob.set(job); this.pollJob<StakeResult>(job, 'stake', text); },
      error: (e) => { this.error.set(this.msg(e)); this.stakeLoading.set(false); },
    });
  }

  runDictionary(text: string = this.text()) {
    if (!text.trim()) return;
    this.dictLoading.set(true); this.error.set('');
    this.http.post<DictResult>(`${API}/analyze`, { text }).subscribe({
      next: (r) => { this.dict.set(r); this.dictText.set(text); this.dictLoading.set(false); this.loadReview(text); },
      error: (e) => { this.error.set(this.msg(e)); this.dictLoading.set(false); this.releaseAi(); },
    });
  }

  runLlm(text: string = this.text()) {
    if (!text.trim()) return;
    this.llmLoading.set(true); this.error.set('');
    this.http.post<{ job: string }>(`${API}/jobs/llm`, { text, language: this.lang() }).subscribe({
      next: ({ job }) => { this.llmJob.set(job); this.pollJob<LlmResult>(job, 'llm', text); },
      error: (e) => { this.error.set(this.msg(e)); this.llmLoading.set(false); },
    });
  }

  // Server jobs for the AI traits and reactions; their ids survive a page refresh.
  llmJob = signal('');
  stakeJob = signal('');

  private pollJob<T>(id: string, which: 'llm' | 'stake', text: string, wait = 3000) {
    setTimeout(() => {
      const current = which === 'llm' ? this.llmJob() : this.stakeJob();
      if (current !== id || this.submittedText() !== text) return;  // replaced by a newer run
      this.http.get<{ status: string; result: T | null; error: string; code: number }>(`${API}/jobs/${id}`).subscribe({
        next: (j) => {
          if (j.status === 'running') { this.pollJob<T>(id, which, text); return; }
          const failed = j.status !== 'done';
          if (which === 'llm') {
            if (!failed) this.llm.set(j.result as LlmResult);
            this.llmLoading.set(false); this.llmJob.set('');
          } else {
            const r = j.result as StakeResult | null;
            if (!failed && r) this.stake.set(r.reactions.length ? r : null);
            this.stakeLoading.set(false); this.stakeJob.set('');
          }
          if (failed) this.error.set(this.msg({ status: j.code, error: { detail: j.error } }));
        },
        error: (e) => {
          if (which === 'llm') { this.llmLoading.set(false); this.llmJob.set(''); }
          else { this.stakeLoading.set(false); this.stakeJob.set(''); }
          this.error.set(this.msg(e));
        },
      });
    }, wait);
  }

  // --- Keep the analysis across page refreshes (this browser tab only) -------
  private static readonly STATE_KEY = 'cortex_state';
  private restoring = false;

  private saveState() {
    if (this.restoring) return;
    const state = {
      text: this.text(), submitted: this.submittedText(), page: this.page(),
      speech: this.analyzedSpeech(), mixed: this.analyzedMixed(), uploaded: this.uploadedName(),
      llm: this.llm(), stake: this.stake(), llmJob: this.llmJob(), stakeJob: this.stakeJob(),
      decisions: this.decisions(), fromAi: [...this.fromAi()], touched: [...this.touched()],
      aiJob: this.aiJob(), aiQueued: this.aiQueued(),
    };
    try { sessionStorage.setItem(App.STATE_KEY, JSON.stringify(state)); }
    catch { /* too big or storage off: the analysis still works, it just won't survive a refresh */ }
  }

  /** After a refresh: put the analysis back and pick up whatever was still running. */
  private restoreState() {
    let st: any = null;
    try { st = JSON.parse(sessionStorage.getItem(App.STATE_KEY) || 'null'); } catch { st = null; }
    if (!st?.submitted) { if (st?.text) this.text.set(st.text); if (st?.page) this.page.set(st.page); return; }
    this.restoring = true;
    const text: string = st.submitted;
    this.text.set(st.text ?? text); this.submittedText.set(text); this.page.set(st.page ?? 'analyze');
    this.analyzedSpeech.set(st.speech ?? ''); this.analyzedMixed.set(!!st.mixed); this.uploadedName.set(st.uploaded ?? '');
    this.llm.set(st.llm ?? null); this.stake.set(st.stake ?? null);
    this.decisions.set({ ...noDecisions(), ...(st.decisions ?? {}) });
    this.fromAi.set(new Set(st.fromAi ?? [])); this.touched.set(new Set(st.touched ?? []));
    this.aiJob.set(st.aiJob ?? null); this.aiQueued.set(st.aiQueued ?? '');
    this.restoring = false;
    // The word scorer and the review are quick to redo; the decisions are kept.
    this.dictText.set(text); this.dictLoading.set(true);
    this.http.post<DictResult>(`${API}/analyze`, { text }).subscribe({
      next: (r) => {
        this.dict.set(r); this.dictLoading.set(false);
        this.http.post<Review>(`${API}/context/review`, { text }).subscribe({
          next: (rv) => {
            this.review.set(rv);
            this.rescore();
            const j = this.aiJob();
            if (j?.status === 'running' && j.id) this.pollAi(j.id, text, 500);
            else this.releaseAi();
          },
        });
      },
      error: (e) => { this.dictLoading.set(false); this.error.set(this.msg(e)); },
    });
    if (st.llmJob) { this.llmJob.set(st.llmJob); this.llmLoading.set(true); this.pollJob<LlmResult>(st.llmJob, 'llm', text, 500); }
    if (st.stakeJob) { this.stakeJob.set(st.stakeJob); this.stakeLoading.set(true); this.pollJob<StakeResult>(st.stakeJob, 'stake', text, 500); }
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
      const skip = (n: number | undefined, words: Record<string, number> | undefined, text: string) =>
        n ? ' ' + fill(text, { n, words: this.wordsFound(words ?? {}, limit) }) : '';
      const skipped = skip(tr.skipped?.other, tr.skipped_matches?.other, b.reasonSkippedOther)
        + skip(tr.skipped?.denied, tr.skipped_matches?.denied, b.reasonSkippedDenied);
      return `${share}${skipped} ${verdict}`;
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
        ${st.read_in_parts && !st.excerpted ? `<p class="rat">${this.esc(this.partsNote(st.read_in_parts))}</p>` : ''}
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
        .hl { padding: 1px 2px 4px; border-radius: 3px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
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
