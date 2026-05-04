/** Demo / ön yüz dili: TR / EN / AR seçici ve metinler */

/** @typedef {'tr'|'en'|'ar'} DemoLang */

/** Üst bardaki dil butonları: Türkçe, English, العربية */
export const DEMO_LANGS = [
  { id: 'tr', label: 'Türkçe' },
  { id: 'en', label: 'English' },
  { id: 'ar', label: 'العربية' },
];

const STORAGE_KEY = 'diagvoice-demo-lang';

const TR = {
  headerAdmin: 'Admin',
  navPagesAria: 'Sayfalar',
  languageSwitchAria: 'Dil seçimi',
  logoAlt: 'DiagVoice Logo',
  tabSummary: 'Özet',
  tabDetails: 'Model Detayları',
  loadingAnalyzing: '“{{source}}” için analiz yapılıyor… Lütfen bekleyin.',
  errorUnknown: 'Bilinmeyen bir hata oluştu',
  errorAnalyzing: '“{{source}}” analizi sırasında bir hata oluştu: {{message}}',
  sourceNewRecording: 'Yeni kayıt',
  confidenceBadge: 'Güven',

  recorderTitle: 'Mikrofon kaydı',
  recorderStart: 'Kaydı başlat',
  recorderStop: 'Kaydı durdur',
  recorderPlay: 'Oynat',
  recorderPause: 'Durdur',
  recorderMicDenied: 'Mikrofon erişimi reddedildi veya bir hata oluştu.',

  sampleTitle: 'Örnek sesler',
  sampleHint: 'Bir örnek seçin; aynı alandan dinleyip analizi başlatabilirsiniz.',
  sampleListAria: 'Örnek ses listesi',
  sampleAnalyzeSep: '— Analiz et',
  sampleLoadError: 'Örnek ses dosyası yüklenirken bir hata oluştu.',

  filePickTitle: 'Bilgisayardan ses',
  fileSelected: 'Seçilen',
  browserNoAudio: 'Tarayıcınız ses oynatmayı desteklemiyor.',

  diseaseHealthy: 'Sağlıklı',
  diseaseSick: 'Hasta',
  probHealthy: 'Sağlıklı',
  probSick: 'Hasta',

  diagRiskUi: 'Tanılı riski',
  diagHealthyProf: 'Sağlıklı profil',
  thresholdLabel: 'Eşik',
  pDiagLabel: 'P(tanılı)',
  modelModeLabel: 'Model modu',

  mentalOk: 'Sağlıklı profil',
  mentalReview: 'Değerlendirme gerekli',
  vocalHealthScore: 'Ses sağlığı skoru',

  depRisk: 'Depresyon riski',
  depOk: 'Sağlıklı',
  statusPrefix: 'Durum:',
  riskLevelPrefix: 'Risk seviyesi:',
  scoreLabel: 'Skor',

  emotionSadness: 'Üzüntü',
  emotionFear: 'Korku',
  emotionHappiness: 'Mutluluk',
  emotionAnger: 'Öfke',
  emotionHappyAlt: 'Mutlu',
  emotionSadAlt: 'Üzgün',
  emotionAngryAlt: 'Sinirli',
  emotionFearfulAlt: 'Korkulu',

  depRiskLow: 'Düşük',
  depRiskMid: 'Orta',
  depRiskHigh: 'Yüksek',

  classN: 'Sınıf {{n}}',

  pageLoading: 'Sayfa yükleniyor…',
  cms404Error:
    'Bu slug için yayımlanmış bir sayfa yok. Admin’den slug ve “Yayında” alanını kontrol et.',
  cmsWarnHome:
    'Demo ayarları yüklenemedi (CMS kapalı olabilir); varsayılan kart sırası kullanılıyor.',
  cmsWarnPage: 'Sayfa ayarları yüklenemedi; varsayılan davranış kullanılıyor.',

  genderMale: 'Erkek',
  genderFemale: 'Kadın',
  mdEmotionDistrib: 'Ses duygusu — olasılık dağılımı',
  mdEmotionDistribSrc:
    'Kaynak: ses duygusu modelinin sınıf bazlı olasılık çıktıları',
  mdAgeGender: 'Yaş ve cinsiyet',
  mdGenderGuess: 'Cinsiyet tahmini',
  mdAgeGroupGuess: 'Yaş grubu tahmini',
  mdDistribution: 'Dağılım (olasılıklar)',
  fusedEmotionPrefix: 'Birleşik duygu:',
  valencePct: 'Valence: {{p}}%',
  valenceUnavailable: 'Valence hesaplanamadı',
  textWeight: 'Metin ağırlığı: {{p}}%',
  mdValenceCompare: 'Ses duygusu — metin ile ses valence karşılaştırması',
  mdValenceCompareSrc:
    'Kaynak: metin duygusu ile sesden hesaplanan valence karşılaştırması',
  labelTextShort: 'Metin',
  labelAudioShort: 'Ses',
  mdFusionConfTitle: 'Ses duygusu — güven ve dinamik füzyon',
  mdFusionConfSrc: 'Kaynak: ses duygusu ile metin duygusu birleştirme',
  confTextLbl: 'Metin güveni',
  confTextSub: 'Valence (metne göre)',
  confAudioLbl: 'Ses güveni',
  confAudioSub: 'Ses güvenilirliği (entropiye göre)',
  mdMismatchHeading: 'Uyumsuzluk ve model ayarı',
  disagreementLbl: 'Disagreement',
  dynamicFusionLbl: 'Dynamic Fusion',
  on: 'Açık',
  off: 'Kapalı',
};

const EN = {
  headerAdmin: 'Admin',
  navPagesAria: 'Pages',
  languageSwitchAria: 'Language selection',
  logoAlt: 'DiagVoice Logo',
  tabSummary: 'Summary',
  tabDetails: 'Model details',
  loadingAnalyzing: 'Analyzing “{{source}}”… Please wait.',
  errorUnknown: 'An unknown error occurred',
  errorAnalyzing: 'Analysis error for “{{source}}”: {{message}}',
  sourceNewRecording: 'New recording',
  confidenceBadge: 'Confidence',

  recorderTitle: 'Microphone recording',
  recorderStart: 'Start recording',
  recorderStop: 'Stop recording',
  recorderPlay: 'Play',
  recorderPause: 'Pause',
  recorderMicDenied: 'Microphone access was denied or an error occurred.',

  sampleTitle: 'Sample audio',
  sampleHint: 'Pick a sample; listen here and run analysis.',
  sampleListAria: 'Sample audio list',
  sampleAnalyzeSep: '— Analyze',
  sampleLoadError: 'Could not load the sample audio file.',

  filePickTitle: 'Audio from computer',
  fileSelected: 'Selected',
  browserNoAudio: 'Your browser does not support audio playback.',

  diseaseHealthy: 'Healthy',
  diseaseSick: 'Unwell',
  probHealthy: 'Healthy',
  probSick: 'Unwell',

  diagRiskUi: 'Risk profile',
  diagHealthyProf: 'Healthy profile',
  thresholdLabel: 'Threshold',
  pDiagLabel: 'P(case)',
  modelModeLabel: 'Model mode',

  mentalOk: 'Healthy profile',
  mentalReview: 'Review suggested',
  vocalHealthScore: 'Vocal health score',

  depRisk: 'Depression risk',
  depOk: 'Healthy',
  statusPrefix: 'Status:',
  riskLevelPrefix: 'Risk level:',
  scoreLabel: 'Score',

  emotionSadness: 'Sadness',
  emotionFear: 'Fear',
  emotionHappiness: 'Happiness',
  emotionAnger: 'Anger',
  emotionHappyAlt: 'Happy',
  emotionSadAlt: 'Sad',
  emotionAngryAlt: 'Angry',
  emotionFearfulAlt: 'Fearful',

  depRiskLow: 'Low',
  depRiskMid: 'Medium',
  depRiskHigh: 'High',

  classN: 'Class {{n}}',

  pageLoading: 'Loading page…',
  cms404Error: 'No published page for this slug. Check slug and Published in Admin.',
  cmsWarnHome:
    'Could not load demo settings (CMS may be offline); default card order is used.',
  cmsWarnPage: 'Could not load page settings; defaults are used.',

  genderMale: 'Male',
  genderFemale: 'Female',
  mdEmotionDistrib: 'Speech emotion — probability distribution',
  mdEmotionDistribSrc: 'Source: class probabilities from the speech emotion model',
  mdAgeGender: 'Age and gender',
  mdGenderGuess: 'Predicted gender',
  mdAgeGroupGuess: 'Predicted age group',
  mdDistribution: 'Distribution (probabilities)',
  fusedEmotionPrefix: 'Fused sentiment:',
  valencePct: 'Valence: {{p}}%',
  valenceUnavailable: 'Valence could not be computed',
  textWeight: 'Text weight: {{p}}%',
  mdValenceCompare: 'Speech emotion — text vs audio valence',
  mdValenceCompareSrc: 'Source: text sentiment vs audio-derived valence',
  labelTextShort: 'Text',
  labelAudioShort: 'Audio',
  mdFusionConfTitle: 'Speech emotion — confidence and dynamic fusion',
  mdFusionConfSrc: 'Source: speech emotion + text sentiment fusion',
  confTextLbl: 'Text confidence',
  confTextSub: 'Based on text valence',
  confAudioLbl: 'Audio confidence',
  confAudioSub: 'From audio entropy',
  mdMismatchHeading: 'Mismatch and model settings',
  disagreementLbl: 'Disagreement',
  dynamicFusionLbl: 'Dynamic fusion',
  on: 'On',
  off: 'Off',
};

const AR = {
  headerAdmin: 'الإدارة',
  navPagesAria: 'الصفحات',
  languageSwitchAria: 'اختيار اللغة',
  logoAlt: 'شعار DiagVoice',
  tabSummary: 'ملخص',
  tabDetails: 'تفاصيل النموذج',
  loadingAnalyzing: 'جارٍ تحليل «{{source}}»… يُرجى الانتظار.',
  errorUnknown: 'حدث خطأ غير معروف',
  errorAnalyzing: 'خطأ أثناء تحليل «{{source}}»: {{message}}',
  sourceNewRecording: 'تسجيل جديد',
  confidenceBadge: 'الثقة',

  recorderTitle: 'تسجيل الميكروفون',
  recorderStart: 'بدء التسجيل',
  recorderStop: 'إيقاف التسجيل',
  recorderPlay: 'تشغيل',
  recorderPause: 'إيقاف مؤقت',
  recorderMicDenied: 'تم رفض الوصول إلى الميكروفون أو حدث خطأ.',

  sampleTitle: 'عينات صوتية',
  sampleHint: 'اختر عينة؛ استمع وابدأ التحليل من هنا.',
  sampleListAria: 'قائمة العينات الصوتية',
  sampleAnalyzeSep: '— تحليل',
  sampleLoadError: 'تعذّر تحميل ملف العينة الصوتية.',

  filePickTitle: 'صوت من الجهاز',
  fileSelected: 'المحدد',
  browserNoAudio: 'المتصفح لا يدعم تشغيل الصوت.',

  diseaseHealthy: 'سليم',
  diseaseSick: 'مرض',
  probHealthy: 'سليم',
  probSick: 'مرض',

  diagRiskUi: 'احتمال تشخيص',
  diagHealthyProf: 'ملف سليم',
  thresholdLabel: 'العتبة',
  pDiagLabel: 'P(تشخيص)',
  modelModeLabel: 'وضع النموذج',

  mentalOk: 'ملف سليم',
  mentalReview: 'يُستحسن التقييم',
  vocalHealthScore: 'درجة الصحة الصوتية',

  depRisk: 'خطر الاكتئاب',
  depOk: 'سليم',
  statusPrefix: 'الحالة:',
  riskLevelPrefix: 'مستوى الخطر:',
  scoreLabel: 'النتيجة',

  emotionSadness: 'حزن',
  emotionFear: 'خوف',
  emotionHappiness: 'سعادة',
  emotionAnger: 'غضب',
  emotionHappyAlt: 'سعيد',
  emotionSadAlt: 'حزين',
  emotionAngryAlt: 'منزعج',
  emotionFearfulAlt: 'خائف',

  depRiskLow: 'منخفض',
  depRiskMid: 'متوسط',
  depRiskHigh: 'مرتفع',

  classN: 'الصنف {{n}}',

  pageLoading: 'جاري تحميل الصفحة…',
  cms404Error: 'لا توجد صفحة منشورة لهذا المعرف. راجع المعرف وحقل النشر من الإدارة.',
  cmsWarnHome:
    'تعذّر تحميل إعدادات العرض؛ قد يكون نظام المحتوى غير متاح. يتم استخدام ترتيب البطاقات الافتراضي.',
  cmsWarnPage: 'تعذّر تحميل إعدادات الصفحة؛ يتم السلوك الافتراضي.',

  genderMale: 'ذكر',
  genderFemale: 'أنثى',
  mdEmotionDistrib: 'المشاعر من الصوت — توزيع الاحتمالات',
  mdEmotionDistribSrc: 'المصدر: احتمالات الأصناف من نموذج مشاعر الصوت',
  mdAgeGender: 'العمر والجنس',
  mdGenderGuess: 'توقع الجنس',
  mdAgeGroupGuess: 'توقع الفئة العمرية',
  mdDistribution: 'التوزيع (احتمالات)',
  fusedEmotionPrefix: 'المشاعر المدمجة:',
  valencePct: 'الانطباعية (Valence): {{p}}%',
  valenceUnavailable: 'تعذّر حساب الانطباعية',
  textWeight: 'وزن النص: {{p}}%',
  mdValenceCompare: 'المشاعر من الصوت — مقارنة انطباعية النص والصوت',
  mdValenceCompareSrc: 'المصدر: تحليل نص الصوت ومقارنة الانطباعية',
  labelTextShort: 'نص',
  labelAudioShort: 'صوت',
  mdFusionConfTitle: 'المشاعر من الصوت — الثقة والدمج الديناميكي',
  mdFusionConfSrc: 'المصدر: دمج مشاعر الصوت وتحليل نص الصوت',
  confTextLbl: 'ثقة النص',
  confTextSub: 'حسب انطباعية النص',
  confAudioLbl: 'ثقة الصوت',
  confAudioSub: 'حسب إنتروبيا الصوت',
  mdMismatchHeading: 'التناقض وإعداد النموذج',
  disagreementLbl: 'التباعد',
  dynamicFusionLbl: 'دمج ديناميكي',
  on: 'مفعّل',
  off: 'معطّل',
};

const LOCALES = /** @type {Record<DemoLang, typeof TR>} */ ({
  tr: TR,
  en: EN,
  ar: AR,
});

/**
 * @param {DemoLang} lang
 * @param {keyof typeof TR} key
 * @param {Record<string, string>} [vars]
 */
export function demoT(lang, key, vars) {
  const lg = normalizeDemoLang(lang);
  const L = LOCALES[lg];
  /** @type {string | undefined} */
  let s = L[key] ?? LOCALES.tr[key] ?? LOCALES.en[key];
  if (s === undefined || s === null) return String(key);
  if (!vars) return s;
  return Object.keys(vars).reduce(
    (acc, k) => acc.replace(new RegExp(`\\{\\{${k}\\}\\}`, 'g'), vars[k]),
    s,
  );
}

export function normalizeDemoLang(v) {
  const s = typeof v === 'string' ? v.trim().toLowerCase().slice(0, 3) : '';
  if (s === 'en' || s === 'ar') return /** @type {DemoLang} */ (s);
  return 'tr';
}

export function readStoredDemoLang() {
  try {
    return normalizeDemoLang(localStorage.getItem(STORAGE_KEY) || '');
  } catch {
    return 'tr';
  }
}

/** @param {DemoLang} lang */
export function writeStoredDemoLang(lang) {
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* ignore */
  }
}

/** @param {DemoLang} lang */
export function syncDocumentDemoLang(lang) {
  const L = normalizeDemoLang(lang);
  if (typeof document === 'undefined') return;
  document.documentElement.lang = L === 'ar' ? 'ar' : L === 'en' ? 'en' : 'tr';
  document.documentElement.dir = L === 'ar' ? 'rtl' : 'ltr';
}

export function emotionUiLabel(lang, predLabel) {
  const L = LOCALES[normalizeDemoLang(lang)];
  const m = {
    sadness: L.emotionSadness,
    fear: L.emotionFear,
    happiness: L.emotionHappiness,
    anger: L.emotionAnger,
    happy: L.emotionHappyAlt,
    sad: L.emotionSadAlt,
    angry: L.emotionAngryAlt,
    fearful: L.emotionFearfulAlt,
  };
  return m[predLabel] || predLabel;
}

export function depressionRiskUiLabel(lang, riskKey) {
  const k = normalizeDemoLang(lang);
  const map = /** @type {Record<string, Record<string, string>>} */ ({
    tr: { dusuk: TR.depRiskLow, orta: TR.depRiskMid, yuksek: TR.depRiskHigh },
    en: { dusuk: EN.depRiskLow, orta: EN.depRiskMid, yuksek: EN.depRiskHigh },
    ar: { dusuk: AR.depRiskLow, orta: AR.depRiskMid, yuksek: AR.depRiskHigh },
  });
  const row = map[k] || map.tr;
  return row[riskKey] ?? '—';
}

export function genderUiLabel(lang, pred) {
  const L = LOCALES[normalizeDemoLang(lang)];
  if (pred === 'male') return L.genderMale;
  if (pred === 'female') return L.genderFemale;
  return pred || '-';
}

export { STORAGE_KEY as DEMO_LANG_STORAGE_KEY };
