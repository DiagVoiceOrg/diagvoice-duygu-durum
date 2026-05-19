/**
 * Fusion kök host (proxy uçları bu origin altında).
 * Bu uygulama /analyze-fused kullanmaz.
 */
export function getFusionOrigin() {
  const direct = (import.meta.env.VITE_FUSION_ORIGIN || '').trim();
  if (direct) return direct.replace(/\/+$/, '');

  const fromApiUrl = (import.meta.env.VITE_API_URL || '').trim();
  if (fromApiUrl) {
    const stripped = fromApiUrl.replace(/\/?analyze-fused\/?$/i, '').replace(/\/+$/, '');
    if (stripped) return stripped;
  }

  return 'http://localhost:8085';
}
