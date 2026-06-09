import { CARD_REGISTRY } from './cardRegistry';

/** analyze-fused / kısmi analizde API çağrısı tetikleyen kartlar (unified_emotion hariç) */
export const CARD_IDS = CARD_REGISTRY.filter((r) => r.analysisCard !== false).map((r) => r.id);

/** CMS yokken kullanılan sıra — karşılaştırma için metin → ses → birleşik */
export const DEFAULT_CARD_ORDER = [
  'transcript',
  'sentiment',
  'audio_emotion',
  'unified_emotion',
  'disease',
  'benchmark_v2',
  'mental_fitness',
  'depression',
];

const FALLBACK_TITLE = Object.fromEntries(CARD_REGISTRY.map((r) => [r.id, r.defaultTitle]));

/**
 * @param {string} cardId
 * @param {Array<{ id: string, displayTitle?: string, subtitle?: string, footnote?: string, badge?: string, period?: { label?: string, from?: string, to?: string } }>|null|undefined} profileCards
 */
export function mergeCardCopy(cardId, profileCards) {
  const row = profileCards?.find((c) => c.id === cardId);
  const periodLabel = row?.period?.label ?? null;
  return {
    displayTitle: row?.displayTitle ?? FALLBACK_TITLE[cardId] ?? cardId,
    subtitle: row?.subtitle ?? null,
    footnote: row?.footnote ?? null,
    badge: row?.badge ?? null,
    periodLabel,
  };
}

/**
 * Profilde tanımlı sıra; yoksa varsayılan tam liste.
 * @param {Array<{ id: string }>|null|undefined} profileCards
 */
export function resolveCardOrder(profileCards) {
  if (!profileCards?.length) return [...DEFAULT_CARD_ORDER];
  return profileCards.map((c) => c.id).filter(Boolean);
}

/**
 * Birleşik emosyon kartı için kullanıcıya gösterilecek uyarı (analiz sonrası, sonuç yokken).
 * @param {string} lang
 * @param {(lang: string, key: string, vars?: object) => string} t
 */
export function resolveUnifiedEmotionWarn(
  lang,
  t,
  {
    order,
    analyzed,
    isLoading = false,
    unifiedEmotionResult,
    unifiedEmotionError,
    textSttError,
    sentimentPipelineError,
    audioEmotionError,
  },
) {
  if (!order.includes('unified_emotion') || unifiedEmotionResult?.probs?.length) {
    return null;
  }
  if (isLoading || !analyzed) {
    return null;
  }
  if (unifiedEmotionError) {
    return unifiedEmotionError;
  }
  if (textSttError) {
    return `${t(lang, 'mdSttErrorTitle')}: ${textSttError}`;
  }
  if (sentimentPipelineError) {
    return sentimentPipelineError;
  }
  if (audioEmotionError) {
    return audioEmotionError;
  }
  if (!order.includes('sentiment') && !order.includes('audio_emotion')) {
    return t(lang, 'unifiedEmotionProfileNeed');
  }
  return t(lang, 'unifiedEmotionFusionFail');
}
