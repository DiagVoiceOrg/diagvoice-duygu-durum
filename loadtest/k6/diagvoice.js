// DiagVoice yük testi — k6.
//
// Tek bir kademe (STAGE) çalıştırır; sıralı akış için loadtest/run.sh kullanın.
//
//   k6 run -e BASE_URL=https://aiapi.diagvoice.com -e STAGE=fused_10 loadtest/k6/diagvoice.js
//
// Kademe adları: <hedef>_<eşzamanlılık>[_burst]
//   hedef:  root  → GET /                     (model yok; nginx + uvicorn + audit katmanı)
//           text  → POST /analyze-text-sentiment (GPU BERT, kısa)
//           fused → POST /analyze-fused         (STT + tüm modeller, gerçek kullanım)
//           togg  → POST /togg-analyze          (ses emosyonu + WURSS; araç senaryosu)
//   _burst: her VU tek istek atar ve hepsi aynı anda başlar ("N eşzamanlı istek").
//   _seq:   1 VU dahil, DURATION boyunca art arda istek (tek kullanıcı gecikme dağılımı).
//   burst yoksa: N VU, DURATION boyunca (varsayılan 3m) art arda istek atar (sürekli yük).
//
// Ortam değişkenleri:
//   BASE_URL      (zorunlu)   ör. https://aiapi.diagvoice.com
//   STAGE         (zorunlu)   ör. fused_1, fused_100, root_50000_burst
//   DURATION      sürekli yük süresi, varsayılan 3m
//   TIMEOUT       istek zaman aşımı, varsayılan 900s (nginx proxy_read_timeout ile aynı)
//   AUDIO         fused için ses dosyası, varsayılan ../../diagvoice-backend/test-data/ornek-ses-kayitlari/bu-harika-bir-gun.m4a
//   ABORT_ERR     hata oranı bu değeri geçerse (30 sn sonra) kademe durdurulur, varsayılan 0.5

import http from 'k6/http';
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';

const BASE_URL = (__ENV.BASE_URL || '').replace(/\/+$/, '');
const STAGE = __ENV.STAGE || '';
const DURATION = __ENV.DURATION || '3m';
const TIMEOUT = __ENV.TIMEOUT || '900s';
const ABORT_ERR = parseFloat(__ENV.ABORT_ERR || '0.5');
const AUDIO_PATH =
  __ENV.AUDIO || '../../diagvoice-backend/test-data/ornek-ses-kayitlari/bu-harika-bir-gun.m4a';

if (!BASE_URL) throw new Error('BASE_URL gerekli');
const m = /^(root|text|fused|togg)_(\d+)(_burst|_seq)?$/.exec(STAGE);
if (!m) throw new Error(`Geçersiz STAGE: "${STAGE}" (ör. fused_10, root_50000_burst)`);
const TARGET = m[1];
const VUS = parseInt(m[2], 10);
const BURST = m[3] === '_burst' || (VUS === 1 && m[3] !== '_seq');

// Ses dosyası yalnızca ses kademelerinde okunur (init bağlamı her VU'da çalışır).
const AUDIO = TARGET === 'fused' || TARGET === 'togg' ? open(AUDIO_PATH, 'b') : null;

const TEXTS = [
  'Bugün kendimi çok iyi hissediyorum, her şey yolunda.',
  'Son zamanlarda çok yorgunum ve hiçbir şeyden zevk alamıyorum.',
  'Toplantı fena geçmedi ama biraz gerginim.',
];

const status2xx = new Counter('status_2xx');
const status4xx = new Counter('status_4xx');
const status5xx = new Counter('status_5xx');
const statusNet = new Counter('status_network_error'); // status 0: bağlantı reddi, reset, timeout
const statusPartial = new Counter('status_partial'); // togg: 200 ama audio_error/disease_error dolu
const okDuration = new Trend('ok_duration', true);

export const options = {
  scenarios: {
    main: BURST
      ? { executor: 'per-vu-iterations', vus: VUS, iterations: 1, maxDuration: '20m' }
      : { executor: 'constant-vus', vus: VUS, duration: DURATION, gracefulStop: '15m' },
  },
  thresholds: {
    // Yalnızca erken durdurma için; "geçti/kaldı" yorumu raporda yapılır.
    http_req_failed: [{ threshold: `rate<${ABORT_ERR}`, abortOnFail: true, delayAbortEval: '30s' }],
  },
  summaryTrendStats: ['min', 'med', 'avg', 'p(90)', 'p(95)', 'p(99)', 'max'],
  discardResponseBodies: true,
  userAgent: 'diagvoice-loadtest/1.0',
  tags: { stage: STAGE },
  // ORIGIN_IP verilirse domain doğrudan sunucuya çözülür (Cloudflare atlanır; SNI/sertifika aynı kalır).
  hosts: __ENV.ORIGIN_IP ? { [BASE_URL.replace(/^https?:\/\//, '').split(/[/:]/)[0]]: __ENV.ORIGIN_IP } : {},
  insecureSkipTLSVerify: false,
  noConnectionReuse: false,
};

function send() {
  const params = { timeout: TIMEOUT, tags: { target: TARGET } };
  if (TARGET === 'root') return http.get(`${BASE_URL}/`, params);
  if (TARGET === 'text') {
    const text = TEXTS[(__VU + __ITER) % TEXTS.length];
    return http.post(`${BASE_URL}/analyze-text-sentiment`, JSON.stringify({ text }), {
      ...params,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  if (TARGET === 'togg') {
    // Gövde okunur: uç, servis hatasında da 200 döner (audio_error / disease_error).
    return http.post(
      `${BASE_URL}/togg-analyze`,
      { file: http.file(AUDIO, 'loadtest.m4a', 'audio/mp4') },
      { ...params, responseType: 'text' },
    );
  }
  return http.post(
    `${BASE_URL}/analyze-fused`,
    { file: http.file(AUDIO, 'loadtest.m4a', 'audio/mp4'), speech_language: 'tr' },
    params,
  );
}

export default function () {
  const res = send();
  const s = res.status;
  if (s >= 200 && s < 300) {
    status2xx.add(1);
    okDuration.add(res.timings.duration);
    if (TARGET === 'togg') {
      let partial = true;
      try {
        const b = JSON.parse(res.body);
        partial = Boolean(b.audio_error || b.disease_error || !b.audio || !b.disease);
      } catch (e) {
        partial = true;
      }
      if (partial) statusPartial.add(1);
    }
  } else if (s >= 400 && s < 500) status4xx.add(1);
  else if (s >= 500) status5xx.add(1);
  else statusNet.add(1);
  check(res, { '2xx': (r) => r.status >= 200 && r.status < 300 });
}

export function handleSummary(data) {
  const out = __ENV.SUMMARY_OUT || `loadtest/results/${STAGE}.json`;
  const c = (k) => (data.metrics[k] ? data.metrics[k].values.count : 0);
  const d = data.metrics.http_req_duration ? data.metrics.http_req_duration.values : {};
  const ok = data.metrics.ok_duration ? data.metrics.ok_duration.values : {};
  const reqs = data.metrics.http_reqs ? data.metrics.http_reqs.values : {};
  const fmt = (v) => (v === undefined ? '-' : `${(v / 1000).toFixed(2)}s`);
  const line =
    `\n[${STAGE}] istek=${c('http_reqs')} rps=${(reqs.rate || 0).toFixed(2)} ` +
    `2xx=${c('status_2xx')} (kısmi=${c('status_partial')}) 4xx=${c('status_4xx')} 5xx=${c('status_5xx')} ağ_hatası=${c('status_network_error')}\n` +
    `  tüm süreler: med=${fmt(d.med)} p95=${fmt(d['p(95)'])} max=${fmt(d.max)}\n` +
    `  başarılılar: med=${fmt(ok.med)} p95=${fmt(ok['p(95)'])} max=${fmt(ok.max)}\n`;
  return { [out]: JSON.stringify(data, null, 2), stdout: line };
}
