/** UI locale = konuşma/STT dili (backend: turkish | english) */

export const UI_LANGUAGES = [
  { value: 'turkish', nativeLabel: 'Türkçe' },
  { value: 'english', nativeLabel: 'English' },
];

const tr = {
  pageTitle: 'DiagVoice — Duygu durumu',
  headerSubtitle: 'Ses duygu durumu analizi',
  langSectionTitle: 'Dil',
  langSectionHint: 'Arayüz dili ve API konuşma dili (speech_language) bu seçime göre ayarlanır.',
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
  transcriptionSectionTitle: 'Model transkripti',
  prediction: 'Tahmin',
  confidence: 'Güven',
  processingTime: 'İşlem süresi',
  noComponentResult: 'Bu bileşen için sonuç dönmedi.',
  transcriptionTitle: 'Metin',
  emptyTranscript: '(boş)',
  transcriptLangLabel: 'Dil',
  emotions: {
    sadness: 'Üzüntü',
    fear: 'Korku',
    happiness: 'Mutluluk',
    anger: 'Öfke',
  },
  whisperLangDisplay: {
    turkish: 'Türkçe',
    english: 'İngilizce',
  },
  sourceNewRecording: 'Yeni kayıt',
  legalNoticeTitle: 'Bilgilendirme',
  legalNoticePoints: [
    'Bu sayfa, DiagVoice’a ait ses analizi modellerinin yer aldığı bir web arayüzüdür.',
    'Kullanım ve sonuçlar üzerindeki haklar sınırlıdır; buradaki çıktılar tanı veya tedavi yerine kullanılmamalıdır.',
    'Modeller geliştirme aşamasındadır; gördüğünüz sonuçlar her zaman en güncel veya nihai sürümü temsil etmeyebilir.',
  ],
};

const en = {
  pageTitle: 'DiagVoice — Voice emotion',
  headerSubtitle: 'Voice emotion analysis',
  langSectionTitle: 'Language',
  langSectionHint: 'UI language and API speech_language follow this selection.',
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
  transcriptionSectionTitle: 'Model transcript',
  prediction: 'Prediction',
  confidence: 'Confidence',
  processingTime: 'Processing time',
  noComponentResult: 'No result for this component.',
  transcriptionTitle: 'Transcript',
  emptyTranscript: '(empty)',
  transcriptLangLabel: 'Language',
  emotions: {
    sadness: 'Sadness',
    fear: 'Fear',
    happiness: 'Happiness',
    anger: 'Anger',
  },
  whisperLangDisplay: {
    turkish: 'Turkish',
    english: 'English',
  },
  sourceNewRecording: 'New recording',
  legalNoticeTitle: 'Notice',
  legalNoticePoints: [
    'This page is a web interface that hosts DiagVoice audio analysis models.',
    'Rights regarding use and outcomes are limited; outputs must not replace medical diagnosis or treatment.',
    'Models are under development; what you see may not always reflect the latest or final release.',
  ],
};

export const translations = {
  turkish: tr,
  english: en,
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
  return locale === 'english' ? 'en' : 'tr';
}
