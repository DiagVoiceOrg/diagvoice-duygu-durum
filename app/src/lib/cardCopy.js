import { CARD_REGISTRY } from './cardRegistry';

/** Teknik kart kimlikleri — CMS ui_profiles.cards[].id ile eşleşir */
export const CARD_IDS = CARD_REGISTRY.map((r) => r.id);

/** CMS yokken kullanılan sıra ve varsayılan başlıklar */
export const DEFAULT_CARD_ORDER = [...CARD_IDS];

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
