/**
 * Demo kart tipleri — tek kaynak.
 * Yeni model: bu diziye { id, defaultTitle, description } eklemen yeterli;
 * admin “Kart ekle” listesinde ve varsayılan başlıklarda otomatik görünür.
 */
export const CARD_REGISTRY = [
  { id: 'transcript', defaultTitle: 'Çevrilen Metin', description: 'Konuşmanın metne çevrilmiş hali' },
  { id: 'sentiment', defaultTitle: 'Metin Duygusu', description: 'Metin duygu analizi (Positive/Negative/Notr)' },
  { id: 'audio_emotion', defaultTitle: 'Ses Emosyonu', description: 'Yalnızca ses — 4 sınıf duygu tahmini' },
  {
    id: 'unified_emotion',
    defaultTitle: 'Birleşik Emosyon',
    description: 'Metin + ses birleşimi — semantik + emosyon (4 sınıf)',
    analysisCard: false,
  },
  { id: 'disease', defaultTitle: 'WURSS', description: 'WURSS / hastalık skoru' },
  { id: 'benchmark_v2', defaultTitle: 'İş Sağlığı', description: 'İş sağlığı benchmark' },
  { id: 'mental_fitness', defaultTitle: 'Mental Fitness', description: 'Mental fitness skoru' },
  { id: 'depression', defaultTitle: 'Depresyon', description: 'Depresyon modeli' },
];

const byId = Object.fromEntries(CARD_REGISTRY.map((r) => [r.id, r]));

export function getCardRegistryEntry(id) {
  return byId[id] ?? null;
}
