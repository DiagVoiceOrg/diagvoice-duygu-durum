/** VITE_API_URL genelde .../analyze-fused biter; proxy uçları kök host altında. */
export function getFusionOrigin() {
  const raw = (import.meta.env.VITE_API_URL || 'http://localhost:8085/analyze-fused').trim();
  const stripped = raw.replace(/\/?analyze-fused\/?$/i, '');
  return stripped || 'http://localhost:8085';
}
