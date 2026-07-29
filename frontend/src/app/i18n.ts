// UI translations. Add a language by adding a Bundle to LANGS.
export type Lang = 'en' | 'ar';

export interface TraitInfo { what: string; high: string; low: string; }

export interface Bundle {
  dir: 'ltr' | 'rtl';
  langName: string;          // this language's own name
  switchTo: string;          // label shown on the toggle (the OTHER language)
  subtitle: string;
  guideShow: string; guideHide: string;
  howItWorks: string; howIntro: string;
  wordScorerName: string; wordScorerDesc: string;
  aiScorerName: string; aiScorerDesc: string;
  howToRead: string; howToReadBody: string;
  traitsHeading: string; higher: string; lower: string;
  opCodeHeading: string; opCodeIntro: string;
  trySample: string; chooseOne: string; placeholder: string;
  analyze: string; analyzing: string; runNote: string; aiOffNote: string;
  wordPanelTag: string; wordPanelNote: string;
  personalityHeading: string; politicsHeading: string;
  aiPanelTag: string; aiReading: string; overallStyle: string; whyScore: string;
  wordScorerTitle: string; aiScorerTitle: string;
  // Login gate
  loginTitle: string; loginSub: string; userLabel: string; passLabel: string;
  loginBtn: string; loginErr: string; logout: string;
  // Split results view + PDF
  yourTextHeading: string; summaryHeading: string; noSummary: string;
  pdfMore: string; summaryWait: string; seePdf: string; leadershipLabel: string;
  pdfPromptTitle: string; pdfPromptSub: string; confirm: string; cancel: string;
  pdfWrongPass: string; pasteBtn: string; clearBtn: string;
  pdfDocTitle: string; pdfInputHeading: string; pdfWordHeading: string;
  pdfAiHeading: string; pdfGenerated: string;
  // Stakeholder reactions
  stakeHeading: string; stakeIntro: string; stakeWait: string; calibratedTag: string;
  likelyResponse: string; confidenceLabel: string;
  filterAll: string; coalitionLabel: string;
  // Add-stakeholder panel
  navAnalyze: string; navGuide: string;
  panelHeading: string; addStakeholder: string;
  fldName: string; fldRole: string; fldValues: string; fldSupports: string;
  fldOpposes: string; fldConcerns: string; csvHint: string;
  baselineLabel: string; speechNew: string; speechExisting: string; speechNone: string;
  chooseSpeech: string; save: string; saving: string;
  addedOk: string; addedCalibrated: string; nameRequired: string; removeStakeholder: string;
  stances: Record<string, string>;
  bands: Record<string, string>;
  traitNames: Record<string, string>;
  info: Record<string, TraitInfo>;
  vicsInfo: Record<string, string>;
  errReach: string; errOff: string; errGeneric: string;
}

const en: Bundle = {
  dir: 'ltr', langName: 'English', switchTo: 'العربية',
  subtitle: "Reads a political leader's speech and estimates their leadership personality — how they think, decide, and deal with others — from the words and ideas they use.",
  guideShow: '▸ What do these results mean? (read me first)',
  guideHide: '▾ Hide the guide',
  howItWorks: 'How it works',
  howIntro: 'Paste a speech (or pick a sample) and analyze it two ways:',
  wordScorerName: 'Word scorer',
  wordScorerDesc: 'counts the kinds of words used and compares them with a set of sample leaders. Fast and fully transparent, but it can miss meaning: a leader who sounds aggressive without using aggressive words may score low.',
  aiScorerName: 'AI scorer (Groq)',
  aiScorerDesc: 'an AI reads the whole speech and judges its meaning, the way a human analyst would. Better with tone and nuance, and it gives a reason for every score (0–100, where about 50 is average for a world leader).',
  howToRead: 'How to read the labels',
  howToReadBody: 'High / Moderate / Low compares this leader with other leaders — it does not mean good or bad, just stronger or weaker than average on that trait. The word scorer compares against the sample speeches; the AI scorer gives a 0–100 number instead.',
  traitsHeading: 'The seven personality traits',
  higher: 'Higher:', lower: 'Lower:',
  opCodeHeading: 'The "operational code" indices (how they view politics & strategy)',
  opCodeIntro: 'A second, separate method describing how the leader sees the political world and how they pursue goals. Each line below explains its number.',
  trySample: 'Try a sample speech:', chooseOne: '— choose one —',
  placeholder: "Paste a political leader's speech or interview here…",
  analyze: 'Analyze speech', analyzing: 'Analyzing…',
  runNote: 'Runs both the Word scorer and the AI scorer.',
  aiOffNote: ' (AI scorer is off on the server)',
  wordScorerTitle: 'Word scorer', wordPanelTag: 'counts word patterns',
  wordPanelNote: 'Labels compare this speech with the sample leaders.',
  personalityHeading: 'Personality traits',
  politicsHeading: 'How they view politics & strategy',
  aiScorerTitle: 'AI scorer', aiPanelTag: 'reads the meaning',
  aiReading: 'Reading the speech and judging its meaning… this takes a few seconds.',
  overallStyle: 'Overall style:', whyScore: 'Why this score:',
  loginTitle: 'Sign in', loginSub: 'Enter your username and password to use PoliticalPredictor.',
  userLabel: 'Username', passLabel: 'Password',
  loginBtn: 'Sign in', loginErr: 'Wrong username or password.', logout: 'Sign out',
  yourTextHeading: 'Your text', summaryHeading: 'Summary',
  noSummary: 'No summary available for this text.',
  pdfMore: 'Open the PDF for the full analysis, including reasons for each score and the politics & strategy indices.',
  summaryWait: 'Reading the speech and preparing the summary…',
  seePdf: 'See full analysis (PDF)', leadershipLabel: 'Leadership style:',
  pdfPromptTitle: 'Confirm your password',
  pdfPromptSub: 'Re-enter your password to open the full analysis.',
  confirm: 'Confirm', cancel: 'Cancel', pdfWrongPass: 'Wrong password.',
  pasteBtn: 'Paste', clearBtn: 'Clear',
  pdfDocTitle: 'PoliticalPredictor — Full Analysis',
  pdfInputHeading: 'Analyzed text', pdfWordHeading: 'Word scorer',
  pdfAiHeading: 'AI scorer', pdfGenerated: 'Generated by PoliticalPredictor',
  stakeHeading: 'Stakeholder reactions',
  stakeIntro: 'How each stakeholder is likely to react to this speech or policy.',
  stakeWait: 'Predicting how each stakeholder reacts…',
  calibratedTag: 'calibrated on baseline speeches',
  likelyResponse: 'Likely response:', confidenceLabel: 'confidence',
  filterAll: 'All', coalitionLabel: 'Coalition:',
  navAnalyze: 'Analyze', navGuide: 'Guide',
  panelHeading: 'Stakeholder panel', addStakeholder: 'Add stakeholder',
  fldName: 'Name', fldRole: 'Role / title', fldValues: 'Values', fldSupports: 'Usually supports',
  fldOpposes: 'Usually opposes', fldConcerns: 'Main concerns', csvHint: 'comma-separated',
  baselineLabel: 'Baseline speech (for calibration)',
  speechNew: 'Paste a new speech', speechExisting: 'Reuse an existing speech',
  speechNone: 'No speech (use fields only)', chooseSpeech: '— choose a speech —',
  save: 'Save stakeholder', saving: 'Saving…',
  addedOk: 'Stakeholder added.', addedCalibrated: 'Calibrated from the speech.',
  nameRequired: 'Please enter a name.', removeStakeholder: 'Remove',
  stances: { Support: 'Support', Oppose: 'Oppose', Mixed: 'Mixed', Neutral: 'Neutral' },
  bands: { High: 'High', Moderate: 'Moderate', Low: 'Low' },
  traitNames: {
    BACE: 'Belief in Ability to Control Events', PWR: 'Need for Power',
    CC: 'Conceptual Complexity', SC: 'Self-Confidence', TASK: 'Task Focus',
    DIS: 'Distrust of Others', IGB: 'In-Group Bias',
  },
  info: {
    BACE: { what: 'Does the leader feel they can steer events, or feel swept along by them?',
      high: 'Takes charge and initiates — "we decide our own destiny".',
      low: 'Reacts to events and waits; lets others or circumstances lead.' },
    PWR: { what: 'How much the leader wants to control and influence other people.',
      high: 'Dominates, asserts authority, outmaneuvers rivals.',
      low: 'Shares influence and prefers cooperation over control.' },
    CC: { what: "How black-and-white versus nuanced the leader's thinking is.",
      high: 'Sees shades of grey and many angles — "it depends".',
      low: 'Sees things as right/wrong, certain and simple.' },
    SC: { what: 'How sure the leader is of themselves and their own judgment.',
      high: 'Self-assured; trusts their own view — "I know what to do".',
      low: 'Self-doubting; looks to others and the situation for cues.' },
    TASK: { what: 'What drives the leader: getting the job done, or holding people together.',
      high: 'Focused on goals, problems and results.',
      low: 'Focused on people, relationships, morale and feelings.' },
    DIS: { what: 'How suspicious the leader is of other people and groups.',
      high: 'Sees enemies, threats and hidden motives.',
      low: 'Tends to trust others and treat them as potential partners.' },
    IGB: { what: "How strongly the leader divides the world into 'us' and 'them'.",
      high: 'Strong national/group pride; outsiders seen as a threat.',
      low: 'Inclusive; sees common ground with other groups.' },
  },
  vicsInfo: {
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
  },
  errReach: 'Cannot reach the analyzer at {api} — make sure the backend is running.',
  errOff: 'The AI scorer is not switched on (the server is missing its GROQ_API_KEY).',
  errGeneric: 'Something went wrong with the request.',
};

const ar: Bundle = {
  dir: 'rtl', langName: 'العربية', switchTo: 'English',
  subtitle: 'يحلّل خطاب أحد القادة السياسيين ويقدّر شخصيته القيادية — كيف يفكّر ويتّخذ القرارات ويتعامل مع الآخرين — انطلاقًا من الكلمات والأفكار التي يستخدمها.',
  guideShow: '▸ ماذا تعني هذه النتائج؟ (اقرأ هذا أولًا)',
  guideHide: '▾ إخفاء الدليل',
  howItWorks: 'كيف يعمل',
  howIntro: 'الصق خطابًا (أو اختر نموذجًا) وحلّله بطريقتين:',
  wordScorerName: 'أداة تحليل الكلمات',
  wordScorerDesc: 'تُحصي أنواع الكلمات المستخدمة وتقارنها بمجموعة من القادة المرجعيين. سريعة وشفّافة تمامًا، لكنها قد تُغفل المعنى: فالقائد الذي تبدو لهجته عدائية دون أن يستخدم كلمات عدائية قد يحصل على درجة منخفضة.',
  aiScorerName: 'أداة الذكاء الاصطناعي (Groq)',
  aiScorerDesc: 'يقرأ الذكاء الاصطناعي الخطاب كاملًا ويحكم على معناه كما يفعل المحلّل البشري. أفضل في فهم النبرة والفروق الدقيقة، ويقدّم سببًا لكل درجة (من 0 إلى 100، حيث 50 تقريبًا هو المتوسط لقائد عالمي).',
  howToRead: 'كيف تقرأ التصنيفات',
  howToReadBody: 'عالٍ / متوسط / منخفض يقارن هذا القائد بقادة آخرين — وهو لا يعني جيّدًا أو سيّئًا، بل فقط أقوى أو أضعف من المتوسط في تلك السمة. أداة الكلمات تقارن بخطابات العيّنة، بينما تعطي أداة الذكاء الاصطناعي رقمًا من 0 إلى 100.',
  traitsHeading: 'السمات الشخصية السبع',
  higher: 'أعلى:', lower: 'أدنى:',
  opCodeHeading: 'مؤشّرات «الشيفرة التشغيلية» (كيف يرى السياسة والاستراتيجية)',
  opCodeIntro: 'طريقة ثانية مستقلّة تصف كيف يرى القائد العالم السياسي وكيف يسعى لتحقيق أهدافه. كلّ سطر أدناه يشرح معنى رقمه.',
  trySample: 'جرّب خطابًا نموذجيًا:', chooseOne: '— اختر —',
  placeholder: 'الصق هنا خطاب أو مقابلة لأحد القادة السياسيين…',
  analyze: 'حلّل الخطاب', analyzing: 'جارٍ التحليل…',
  runNote: 'يشغّل أداة الكلمات وأداة الذكاء الاصطناعي معًا.',
  aiOffNote: ' (أداة الذكاء الاصطناعي متوقّفة على الخادم)',
  wordScorerTitle: 'أداة تحليل الكلمات', wordPanelTag: 'تُحصي أنماط الكلمات',
  wordPanelNote: 'التصنيفات تقارن هذا الخطاب بالقادة المرجعيين.',
  personalityHeading: 'السمات الشخصية',
  politicsHeading: 'كيف يرى السياسة والاستراتيجية',
  aiScorerTitle: 'أداة الذكاء الاصطناعي', aiPanelTag: 'تقرأ المعنى',
  aiReading: 'جارٍ قراءة الخطاب والحكم على معناه… يستغرق هذا بضع ثوانٍ.',
  overallStyle: 'النمط العام:', whyScore: 'سبب هذه الدرجة:',
  loginTitle: 'تسجيل الدخول', loginSub: 'أدخل اسم المستخدم وكلمة المرور لاستخدام PoliticalPredictor.',
  userLabel: 'اسم المستخدم', passLabel: 'كلمة المرور',
  loginBtn: 'دخول', loginErr: 'اسم المستخدم أو كلمة المرور غير صحيحة.', logout: 'تسجيل الخروج',
  yourTextHeading: 'النص الذي أدخلته', summaryHeading: 'الملخّص',
  noSummary: 'لا يوجد ملخّص متاح لهذا النص.',
  pdfMore: 'افتح ملف PDF للحصول على التحليل الكامل، بما في ذلك أسباب كل درجة ومؤشّرات السياسة والاستراتيجية.',
  summaryWait: 'جارٍ قراءة الخطاب وتحضير الملخّص…',
  seePdf: 'عرض التحليل الكامل (PDF)', leadershipLabel: 'النمط القيادي:',
  pdfPromptTitle: 'أكّد كلمة المرور',
  pdfPromptSub: 'أعد إدخال كلمة المرور لفتح التحليل الكامل.',
  confirm: 'تأكيد', cancel: 'إلغاء', pdfWrongPass: 'كلمة المرور غير صحيحة.',
  pasteBtn: 'لصق', clearBtn: 'مسح',
  pdfDocTitle: 'PoliticalPredictor — التحليل الكامل',
  pdfInputHeading: 'النص المُحلَّل', pdfWordHeading: 'أداة تحليل الكلمات',
  pdfAiHeading: 'أداة الذكاء الاصطناعي', pdfGenerated: 'أُنشئ بواسطة PoliticalPredictor',
  stakeHeading: 'ردود أصحاب المصلحة',
  stakeIntro: 'كيف يُرجَّح أن يتفاعل كل صاحب مصلحة مع هذا الخطاب أو السياسة.',
  stakeWait: 'جارٍ التنبّؤ بكيفية تفاعل كل صاحب مصلحة…',
  calibratedTag: 'مُعايَر على الخطابات المرجعية',
  likelyResponse: 'الاستجابة المرجّحة:', confidenceLabel: 'مستوى الثقة',
  filterAll: 'الكل', coalitionLabel: 'الاصطفاف:',
  navAnalyze: 'التحليل', navGuide: 'الدليل',
  panelHeading: 'لوحة أصحاب المصلحة', addStakeholder: 'إضافة صاحب مصلحة',
  fldName: 'الاسم', fldRole: 'الدور / المنصب', fldValues: 'القيم', fldSupports: 'يؤيّد عادةً',
  fldOpposes: 'يعارض عادةً', fldConcerns: 'الاهتمامات الرئيسية', csvHint: 'مفصولة بفواصل',
  baselineLabel: 'الخطاب المرجعي (للمعايرة)',
  speechNew: 'لصق خطاب جديد', speechExisting: 'إعادة استخدام خطاب موجود',
  speechNone: 'بدون خطاب (الحقول فقط)', chooseSpeech: '— اختر خطابًا —',
  save: 'حفظ صاحب المصلحة', saving: 'جارٍ الحفظ…',
  addedOk: 'تمت إضافة صاحب المصلحة.', addedCalibrated: 'تمت المعايرة من الخطاب.',
  nameRequired: 'يرجى إدخال الاسم.', removeStakeholder: 'إزالة',
  stances: { Support: 'مؤيّد', Oppose: 'معارض', Mixed: 'متباين', Neutral: 'محايد' },
  bands: { High: 'عالٍ', Moderate: 'متوسط', Low: 'منخفض' },
  traitNames: {
    BACE: 'الاعتقاد بالقدرة على التحكّم في الأحداث', PWR: 'الحاجة إلى السلطة',
    CC: 'التعقيد المفاهيمي', SC: 'الثقة بالنفس', TASK: 'التركيز على المهمّة',
    DIS: 'عدم الثقة بالآخرين', IGB: 'التحيّز للجماعة',
  },
  info: {
    BACE: { what: 'هل يشعر القائد بأنّه يوجّه الأحداث، أم بأنّها تجرفه؟',
      high: 'يتولّى زمام الأمور ويبادر — «نحن من يقرّر مصيرنا».',
      low: 'يتفاعل مع الأحداث وينتظر؛ يترك القيادة للآخرين أو للظروف.' },
    PWR: { what: 'مدى رغبة القائد في التحكّم في الآخرين والتأثير فيهم.',
      high: 'يهيمن ويفرض سلطته ويتفوّق على منافسيه.',
      low: 'يتشارك النفوذ ويفضّل التعاون على السيطرة.' },
    CC: { what: 'مدى كون تفكير القائد قاطعًا (أبيض وأسود) أو دقيقًا ومتدرّجًا.',
      high: 'يرى تدرّجات رماديّة وزوايا متعدّدة — «الأمر يعتمد على السياق».',
      low: 'يرى الأمور صوابًا أو خطأً، بشكل قاطع وبسيط.' },
    SC: { what: 'مدى ثقة القائد بنفسه وبحكمه الشخصي.',
      high: 'واثق من نفسه ويثق برأيه — «أعرف ما يجب فعله».',
      low: 'يشكّك في نفسه؛ يستند إلى الآخرين والموقف لمعرفة ما يفعل.' },
    TASK: { what: 'ما الذي يحرّك القائد: إنجاز المهمّة، أم تماسك الناس معًا.',
      high: 'يركّز على الأهداف والمشكلات والنتائج.',
      low: 'يركّز على الناس والعلاقات والمعنويات والمشاعر.' },
    DIS: { what: 'مدى ارتياب القائد من الأشخاص والجماعات الأخرى.',
      high: 'يرى أعداءً وتهديدات ودوافع خفيّة.',
      low: 'يميل إلى الثقة بالآخرين واعتبارهم شركاء محتملين.' },
    IGB: { what: 'مدى تقسيم القائد للعالم إلى «نحن» و«هم».',
      high: 'اعتزاز قومي/جماعي قوي؛ يُنظر إلى الغرباء كتهديد.',
      low: 'منفتح وشامل؛ يرى أرضيّة مشتركة مع الجماعات الأخرى.' },
  },
  vicsInfo: {
    'P-1': 'هل يرى القائد العالم السياسي ودّيًّا أم معاديًا؟ قرب +1 = ودّي وتعاوني؛ قرب −1 = مهدِّد.',
    'P-2': 'مدى تفاؤل القائد بتحقيق أهدافه السياسية. أعلى = أكثر تفاؤلًا.',
    'P-3': 'مدى اعتقاد القائد بإمكانية التنبّؤ بالسياسة. أعلى = يرى المستقبل أكثر قابليّة للمعرفة.',
    'P-4': 'مدى شعور القائد بأنّه — لا الآخرون أو القدر — يتحكّم في مجرى التاريخ. أعلى = تحكّم شخصي أكبر.',
    'P-5': 'مدى اعتقاد القائد بأنّ الحظّ والصدفة يحرّكان الأحداث. أعلى = أمور أكثر متروكة للصدفة.',
    'I-1': 'هل يميل نهج القائد العام إلى التعاون (موجب) أم المواجهة (سالب).',
    'I-2': 'مدى ليونة أو شدّة التكتيكات — من المكافآت/الوعود (موجب) إلى التهديدات/العقاب (سالب).',
    'I-3': 'مدى استعداد القائد للمخاطرة. أعلى = أكثر استعدادًا للمجازفة.',
    'I-4a': 'مدى تنقّل القائد بين الخطوات التعاونيّة والمواجهة. أعلى = أكثر توازنًا ومرونة.',
    'I-4b': 'مدى تنقّل القائد بين الأقوال والأفعال. أعلى = أكثر توازنًا.',
    'I-5': 'مزيج التكتيكات المستخدمة (مكافآت، وعود، تهديدات، إلخ).',
    'Summary': 'انطباع عام حول ما إذا كان القائد ينسب الفضل لنفسه (موجب) أم للآخرين (سالب).',
  },
  errReach: 'تعذّر الوصول إلى المحلّل على {api} — تأكّد من تشغيل الخادم الخلفي.',
  errOff: 'أداة الذكاء الاصطناعي غير مفعّلة (يفتقر الخادم إلى مفتاح GROQ_API_KEY).',
  errGeneric: 'حدث خطأ ما في الطلب.',
};

export const LANGS: Record<Lang, Bundle> = { en, ar };
