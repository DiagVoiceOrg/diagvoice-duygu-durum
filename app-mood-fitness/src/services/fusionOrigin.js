/**
 * Fusion kök host (proxy uçları bu origin altında).
 * Bu uygulama /analyze-fused KULLANMAZ — yalnızca ihtiyaç duyulan proxy path'leri çağrılır.
 */
export function getFusionOrigin() {
  const direct = (import.meta.env.VITE_FUSION_ORIGIN || '').trim();
  if (direct) return direct.replace(/\/+$/, '');

  // Ana app ile uyum: VITE_API_URL .../analyze-fused ise kök host'a indir.
  const fromApiUrl = (import.meta.env.VITE_API_URL || '').trim();
  if (fromApiUrl) {
    const stripped = fromApiUrl.replace(/\/?analyze-fused\/?$/i, '').replace(/\/+$/, '');
    if (stripped) return stripped;
  }

  return 'http://localhost:8085';
}
