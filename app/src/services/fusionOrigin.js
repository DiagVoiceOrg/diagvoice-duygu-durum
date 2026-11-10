/**
 * Backend (Fusion + CMS) taban adresi.
 *
 * Prod (Coolify): VITE_API_BASE=https://aiapi.diagvoice.com (app/Dockerfile varsayılanı).
 * Geliştirme: VITE_API_BASE boş → `/api`; Vite proxy (`vite.config.js`) /api/* → yerel backend.
 * (Geriye dönük: eski VITE_API_URL=.../analyze-fused hâlâ okunur.)
 */
export function getFusionOrigin() {
  const base = (import.meta.env.VITE_API_BASE || '').trim();
  if (base) return base.replace(/\/+$/, '');

  const legacy = (import.meta.env.VITE_API_URL || '').trim();
  if (legacy) return legacy.replace(/\/?analyze-fused\/?$/i, '').replace(/\/+$/, '');

  return '/api';
}
