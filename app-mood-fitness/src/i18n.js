/** UI locale = konuşma/STT dili (backend: turkish | english | arabic) */

export const UI_LANGUAGES = [
  { value: 'turkish', nativeLabel: 'Türkçe' },
  { value: 'english', nativeLabel: 'English' },
  { value: 'arabic', nativeLabel: 'العربية' },
];

const tr = {
  pageTitle: 'DiagVoice — Duygu ve mental fitness',
  headerSubtitle: 'Duygu durumu ve mental fitness',
  langSectionTitle: 'Dil',
  langSectionHint: 'Arayüz ve konuşma tanıma (STT) bu dilde çalışır.',
  micCardTitle: 'Mikrofon kaydı',
  fileCardTitle: 'Dosyadan ses',
  startRecord: 'Kaydı başlat',
  stopRecord: 'Kaydı durdur',
  play: 'Oynat',
  pause: 'Duraklat',
  micDenied: 'Mikrofon erişimi reddedildi veya bir hata oluştu.',
  selectedFile: 'Seçilen',
  audioUnsupported: 'Tarayıcınız ses oynatmayı desteklemiyor.',
  analyzingLoading: '"{{source}}" için analiz yapılıyor… Lütfen bekleyin.',
  fatalErrorPrefix: '"{{source}}" analizi sırasında bir hata oluştu:',
  unknownError: 'Bilinmeyen bir hata oluştu',
  emotionSectionTitle: 'Ses duygu durumu',
  prediction: 'Tahmin',
  intensity: 'Yoğunluk',
  noComponentResult: 'Bu bileşen için sonuç dönmedi.',
  mentalSectionTitle: 'Mental fitness ve konuşma metni',
  mentalFitnessHeading: 'Mental fitness',
  transcriptionTitle: 'Metin (STT)',
  emptyTranscript: '(boş)',
  transcriptLangLabel: 'Dil',
  mentalHint:
    'Çok tekrarlı veya anlamsız metin veya tutarsız tanıma çıktısı varsa mental fitness çalışmaz (sunucu: tekrar filtresi ve DeepSeek). Transkript boşsa yine ses üzerinden çalışır.',
  mentalClass: 'Sınıf',
  score: 'Skor',
  probsLabel: 'Olasılıklar',
  emotions: {
    sadness: 'Üzüntü',
    fear: 'Korku',
    happiness: 'Mutluluk',
    anger: 'Öfke',
  },
  mentalLabels: {
    healthy: 'Olumlu (healthy)',
    depression: 'Risk (depression)',
  },
  whisperLangDisplay: {
    turkish: 'Türkçe',
    english: 'İngilizce',
    arabic: 'Arapça',
  },
  sourceNewRecording: 'Yeni kayıt',
};

const en = {
  pageTitle: 'DiagVoice — Mood & mental fitness',
  headerSubtitle: 'Mood & mental fitness',
  langSectionTitle: 'Language',
  langSectionHint: 'UI and speech recognition (STT) use this language.',
  micCardTitle: 'Microphone recording',
  fileCardTitle: 'Audio from file',
  startRecord: 'Start recording',
  stopRecord: 'Stop recording',
  play: 'Play',
  pause: 'Pause',
  micDenied: 'Microphone access was denied or an error occurred.',
  selectedFile: 'Selected',
  audioUnsupported: 'Your browser does not support audio playback.',
  analyzingLoading: 'Analyzing "{{source}}"… Please wait.',
  fatalErrorPrefix: 'An error occurred while analyzing "{{source}}":',
  unknownError: 'An unknown error occurred',
  emotionSectionTitle: 'Voice emotion',
  prediction: 'Prediction',
  intensity: 'Intensity',
  noComponentResult: 'No result for this component.',
  mentalSectionTitle: 'Mental fitness & transcript',
  mentalFitnessHeading: 'Mental fitness',
  transcriptionTitle: 'Transcript (STT)',
  emptyTranscript: '(empty)',
  transcriptLangLabel: 'Language',
  mentalHint:
    'Mental fitness is skipped if the text is highly repetitive, meaningless, or garbled STT (server: repetition filter + DeepSeek). If the transcript is empty, analysis still runs on audio.',
  mentalClass: 'Class',
  score: 'Score',
  probsLabel: 'Probabilities',
  emotions: {
    sadness: 'Sadness',
    fear: 'Fear',
    happiness: 'Happiness',
    anger: 'Anger',
  },
  mentalLabels: {
    healthy: 'Healthy',
    depression: 'Depression risk',
  },
  whisperLangDisplay: {
    turkish: 'Turkish',
    english: 'English',
    arabic: 'Arabic',
  },
  sourceNewRecording: 'New recording',
};

const ar = {
  pageTitle: 'DiagVoice — المزاج واللياقة العقلية',
  headerSubtitle: 'المزاج واللياقة العقلية',
  langSectionTitle: 'اللغة',
  langSectionHint: 'الواجهة والتعرف على الكلام (STT) بهذه اللغة.',
  micCardTitle: 'تسجيل بالميكروفون',
  fileCardTitle: 'صوت من ملف',
  startRecord: 'بدء التسجيل',
  stopRecord: 'إيقاف التسجيل',
  play: 'تشغيل',
  pause: 'إيقاف مؤقت',
  micDenied: 'تم رفض الوصول إلى الميكروفون أو حدث خطأ.',
  selectedFile: 'المحدد',
  audioUnsupported: 'المتصفح لا يدعم تشغيل الصوت.',
  analyzingLoading: 'جارٍ تحليل «{{source}}»… يرجى الانتظار.',
  fatalErrorPrefix: 'حدث خطأ أثناء تحليل «{{source}}»:',
  unknownError: 'حدث خطأ غير معروف',
  emotionSectionTitle: 'مشاعر الصوت',
  prediction: 'التقدير',
  intensity: 'الشدة',
  noComponentResult: 'لا توجد نتيجة لهذا الجزء.',
  mentalSectionTitle: 'اللياقة العقلية والنص',
  mentalFitnessHeading: 'اللياقة العقلية',
  transcriptionTitle: 'النص (STT)',
  emptyTranscript: '(فارغ)',
  transcriptLangLabel: 'اللغة',
  mentalHint:
    'لا يُشغَّل تقييم اللياقة العقلية إذا كان النص مكررًا جدًا أو بلا معنى أو فاسدًا من التعرف على الكلام (الخادم: مرشح التكرار + DeepSeek). إذا كان النص فارغًا، يُحلَّل الصوت فقط.',
  mentalClass: 'الفئة',
  score: 'النتيجة',
  probsLabel: 'الاحتمالات',
  emotions: {
    sadness: 'حزن',
    fear: 'خوف',
    happiness: 'سعادة',
    anger: 'غضب',
  },
  mentalLabels: {
    healthy: 'سليم',
    depression: 'خطر اكتئاب',
  },
  whisperLangDisplay: {
    turkish: 'التركية',
    english: 'الإنجليزية',
    arabic: 'العربية',
  },
  sourceNewRecording: 'تسجيل جديد',
};

export const translations = {
  turkish: tr,
  english: en,
  arabic: ar,
};

export function getStrings(locale) {
  return translations[locale] || translations.turkish;
}

/** {{key}} yer tutuculu basit şablon */
export function interpolate(template, vars) {
  let s = template;
  Object.entries(vars).forEach(([k, v]) => {
    s = s.replaceAll(`{{${k}}}`, String(v));
  });
  return s;
}

export function htmlLangAttribute(locale) {
  if (locale === 'english') return 'en';
  if (locale === 'arabic') return 'ar';
  return 'tr';
}
