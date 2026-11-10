# DiagVoice — Prod'a Geçiş Planı

> Durum: taslak v2 · Tarih: 2026-11-09
> Hedef ortam: **tek VM, AWS g4dn.xlarge** (4 vCPU, 16 GB RAM, 1× NVIDIA T4 16 GB, 125 GB NVMe geçici disk)
> Kapsam (bu tur): API key/auth/rate limit, model registry, konteyner yapısı, Redis kuyruk, frontend.
> Sonraki tur: yük testi, izleme/metrik ayrıntıları.

## 0. Başlangıç noktası

| Konu | Şu an | Sorun |
|---|---|---|
| Erişim | `/analyze-*` uçlarında auth yok, sadece CORS | Kontrollü erişim veremiyoruz |
| Rate limit | Sadece wellness'ta, IP bazlı, bellek içi | Key bazlı değil |
| Model yolları | Her serviste ayrı env, farklı varsayılan; Dockerfile + supervisord + .env + kod 4 yerde tekrar | Hangi model hangi sürüm belli değil |
| Dağıtım | 10 servis tek konteyner, supervisord, modeller image'a `COPY` | Model değişince rebuild; izolasyon yok |
| GPU | Kod CUDA varsa kullanıyor (`torch.cuda.is_available()`), ama 8 ayrı torch süreci var | Her süreç ayrı CUDA context (~300–500 MB VRAM) ve ~1 GB+ RAM harcar; 16 GB RAM'de sıkışır |
| Ses çözme | Aynı dosya her serviste ayrı ayrı ffmpeg/librosa ile çözülüyor | 4 vCPU'da en pahalı israf |
| Eşzamanlılık | Her serviste `threading.Lock`; fusion `httpx` ile bekliyor | Yük altında istekler bağlantıda asılı kalıyor (FE timeout 600 sn) |
| Sırlar | `admin123`, `change-me-in-production` varsayılanları | Env eksikse zayıf değerle başlıyor |
| Bağımlılıklar | `requirements.txt` sürüm sabitlemiyor | Her build farklı torch/transformers gelebilir |
| Test | Yok | Refactor'da model çıktısı kayarsa fark etmeyiz |

Kullanıcılar: TOGG (geliştirme aşamasında, yeni API dokümanı verilecek) ve kendi uygulamalarımız. **Uzun bir geriye uyumluluk dönemine gerek yok**; doğrudan `/v1` API'ye geçiyoruz.

## 1. Hedef mimari (tek VM)

```
 İnternet ──443──▶ Caddy (TLS, otomatik sertifika)
                        │
                        ▼
                 ┌─────────────────────────────┐
                 │ gateway (FastAPI)            │  ~0.5 GB RAM, 1 vCPU
                 │ auth · rate limit · kota     │
                 │ ses ön işleme (1 kez decode) │
                 │ pipeline orkestrasyonu       │
                 │ CMS/admin API · audit        │
                 └──────┬────────────┬──────────┘
                        │            │
                 ┌──────▼─────┐   ┌──▼──────────────┐
                 │ Redis      │   │ MongoDB (harici, │
                 │ kuyruk,    │   │ mevcut): keys,   │
                 │ limit,     │   │ logs, CMS        │
                 │ sonuç      │   └──────────────────┘
                 └──┬──────┬──┘
                    │      │
        ┌───────────▼──┐ ┌─▼─────────────────┐
        │ worker-gpu    │ │ worker-cpu         │
        │ TEK süreç,    │ │ sklearn / opensmile│
        │ TEK CUDA ctx  │ │ / librosa özellik  │
        │ tüm torch     │ │ tabanlı modeller   │
        │ modelleri T4'te│ │ 2 vCPU            │
        └───────────────┘ └────────────────────┘
           ortak volume'lar: /models (salt okunur) · /data/uploads · /cache/hf
```

### Neden model başına konteyner değil

İlk taslakta her modele ayrı konteyner vardı. g4dn.xlarge'da bu kötü sonuç verir:
- **RAM:** 8 torch süreci × ~1–1.5 GB = 8–12 GB. 16 GB'ın neredeyse tamamı, OS ve diğerlerine yer kalmaz.
- **VRAM:** 8 CUDA context × ~0.4 GB = ~3 GB boşa gider.
- **GPU zaten tek.** Aynı anda 8 süreç GPU'ya iş vermesi hızlandırmaz, sadece çekişme yaratır.

Bu yüzden **torch modelleri tek bir GPU worker sürecinde** toplanır. Ağırlık toplamı (Whisper turbo fp16 ~1.6 GB + ~380 MB'lık 5 model + psikoloji sınıflandırıcı ~440 MB + metin duygusu + cinsiyet modeli + sentence-transformer) T4'ün 16 GB'ına rahat sığar.

**Model ekleme kolaylığı korunur:** her model registry'de kendi kaydı ve kendi adapter'ı ile durur, sadece `worker_group: gpu | cpu | dedicated` alanı hangi süreçte çalışacağını söyler. İleride bir model ağırlaşırsa ya da ikinci GPU gelirse `dedicated` yapılıp ayrı konteynere alınır. Kod değişmez.

### Kaynak bütçesi (hedef)

| Bileşen | RAM | vCPU | VRAM |
|---|---|---|---|
| OS + Docker + Caddy | ~1.5 GB | — | — |
| gateway | ~0.5 GB | 1 | — |
| Redis | ~0.3 GB | paylaşımlı | — |
| worker-gpu | ~5–6 GB | 1 | ~7–9 GB |
| worker-cpu | ~2 GB | 2 | — |
| **Toplam** | **~10 GB** (≈6 GB pay) | 4 | **~9 GB** (≈7 GB pay) |

Her konteynere `mem_limit`. Ek güvenlik için 4 GB swap dosyası. Kesin rakamlar yük testinde ölçülecek.

## 2. Fazlar

| Faz | İçerik | Bağımlılık | Tahmini süre |
|---|---|---|---|
| F0 | Güvenlik ağı: golden testler, bağımlılık sabitleme | — | 0.5 gün |
| F1 | API key + auth + rate limit + kota + `/v1` API | F0 | 1–1.5 gün |
| F2 | Model registry + adapter'lar + GPU/CPU worker | F0 | 2 gün |
| F3 | Konteyner yapısı + VM kurulumu (CUDA, Caddy) | F2 | 1 gün |
| F4 | Redis kuyruk + job API | F2, F3 | 1.5–2 gün |
| F5 | Frontend yeniden tasarım | F1 | 2–3 gün |
| — | *Sonraki tur:* yük testi, metrik/izleme | hepsi | — |

Toplam: kabaca **8–10 iş günü**. F5, F2–F4 ile paralel yürüyebilir.

---

### F0 — Güvenlik ağı

- `test-data/ornek-ses-kayitlari` örnekleriyle **mevcut** sistemin tüm uçlarına istek atıp çıktıları `tests/golden/*.json` olarak kaydet. Bunu GPU sunucusunda yap; CPU ve GPU (fp16) çıktıları küçük farklar verir, referans prod ortamı olmalı.
- `tests/test_golden.py`: yeni sistemin çıktısını karşılaştırır. Sayısal alanlarda tolerans (ör. `abs < 1e-3`, fp16 için), etiketlerde birebir.
- `togg_diversify` gibi bilinçli rastgelelik içeren yerlerde seed sabitlenir veya alan hariç tutulur.
- `requirements.txt` → sürümleri sabitlenmiş `requirements.lock` (mevcut çalışan ortamdan `pip freeze`). Torch CUDA 12 wheel'i açıkça belirtilir.
- Çalışma dalı: `feat/prod-hardening`, her faz ayrı PR.

**Bitti sayılır:** golden testler mevcut sistemde yeşil, build tekrarlanabilir.

---

### F1 — API key, auth, rate limit, kota

#### Key türleri

| Tür | Önek | Kim kullanır | Kısıt |
|---|---|---|---|
| Secret | `dv_sk_` | Sunucudan sunucuya: TOGG, ileride diğer firmalar | Gizli tutulur, tarayıcıya konmaz |
| Publishable | `dv_pk_` | Kendi web arayüzlerimiz (demo, landing, emosyon, algoritmalar, yolarkadaşım…) | Sadece izinli origin'lerden çalışır, düşük limit, sadece izinli modeller |

Format: `dv_sk_<8 karakter key_id>_<32 karakter rastgele>`. Tam key **sadece oluşturulduğu anda bir kez** gösterilir.

Not (TOGG mobil uygulama ise): Mobil uygulamaya secret key gömülürse çıkarılabilir. TOGG'un istekleri kendi backend'inden yapması önerilir; dokümana bu not eklenecek.

#### Mongo koleksiyonları

```text
clients     { _id, name, contact_email, status, notes, created_at }
api_keys    { _id, key_id (unique), type: sk|pk, client_id, name,
              secret_hash,             # HMAC-SHA256(API_KEY_PEPPER, secret)
              scopes: ["analyze:fused", "model:stt", "model:emotion_audio", ...],
              allowed_origins: [...],  # sadece pk
              limits: { rpm, max_concurrent, monthly_quota },
              status: active|revoked, expires_at, last_used_at,
              created_by, created_at, revoked_at }
usage_daily { key_id, client_id, date, route, count, audio_seconds, errors }
```

`fusion_api_logs` kayıtlarına `key_id` ve `client_id` eklenir.

#### İstek akışı

1. `Authorization: Bearer dv_...` veya `X-API-Key`. Yoksa 401.
2. `key_id` ile Redis cache (60 sn) → yoksa Mongo. Hash sabit zamanlı karşılaştırma.
3. Durum, süre, scope, (pk ise) `Origin` kontrolü → uymazsa 403.
4. Rate limit: Redis'te key başına GCRA → `429` + `Retry-After` + `X-RateLimit-*`.
5. Eşzamanlılık limiti: key başına aynı anda en fazla N iş.
6. Aylık kota: Redis sayaç, periyodik olarak `usage_daily`'ye yazılır.
7. `request.state.client` doldurulur, audit log'a geçer.

Açık uçlar: `/health`, `/ready`, `/docs`, `/openapi.json`, CMS public okuma uçları.

#### `/v1` API (yeni ve tek resmi API)

| Uç | Açıklama |
|---|---|
| `POST /v1/analyze/fused` | Tam pipeline (bugünkü `/analyze-fused`) |
| `POST /v1/analyze/{model_id}` | Tek model (registry'den otomatik: `stt`, `emotion_audio`, `depression`, …) |
| `POST /v1/analyze/togg` | TOGG profili (bugünkü `/togg-analyze`: emosyon + WURSS) |
| `POST /v1/jobs`, `GET /v1/jobs/{id}` | Asenkron iş (F4) |
| `GET /v1/models` | Key'in erişebildiği modeller ve sürümleri |

- Tutarlı hata formatı: `{ "error": { "code": "rate_limited", "message": "...", "request_id": "..." } }`.
- Eski uçlar (`/analyze-*`, `/togg-analyze`) kendi FE'miz `/v1`'e geçene kadar aynı sürümde kalır, ardından **kaldırılır**. TOGG'a doğrudan `/v1` dokümanı verilir.
- OpenAPI şeması `/v1` için temizlenir; `docs/API_V1.md` (TOGG'a verilecek doküman: auth, uçlar, örnek istek/yanıt, hata kodları, limitler, webhook) bu fazda yazılır.

#### Admin tarafı

- `POST/GET/PATCH /admin/clients`, `POST /admin/clients/{id}/keys`, `POST /admin/keys/{id}/revoke`, `POST /admin/keys/{id}/rotate`, `GET /admin/keys/{id}/usage`.
- `JWT_SECRET`, `CMS_ADMIN_PASSWORD`, `API_KEY_PEPPER` yoksa veya zayıfsa **uygulama başlamaz**.
- Wellness'taki bellek içi IP limiti aynı Redis limiter'ına taşınır.

**Bitti sayılır:** key'siz istek 401, scope dışı 403, limit aşımı 429; admin'den key üretilip curl ile `/v1` çağrılabiliyor; golden testler yeşil.

---

### F2 — Model registry, adapter'lar, worker'lar

#### Dizin düzeni (EBS üzerinde, git dışında)

```text
/srv/diagvoice/models/
  stt_whisper/large-v3-turbo/          # HF snapshot, önceden indirilmiş
  text_sentiment/v1/                   # kaixkhazaki/turkish-sentiment snapshot
  emotion_audio/v6/wavlm_v6_multicrop_ema_best.pt
  emotion_v2/v1/final_multimodal_stacking_model.joblib
  depression/v1/depresyon.pt
  disease_wurss/v1/{config.json, model.safetensors, preprocessor_config.json}   # eski "usye"
  mental_fitness/v1/extratreesclassifier.joblib
  turkish_psych/v1/mental-fitness-forgpt.safetensors
  age_gender/v1/model.pt
  occupational_health/v1/is-sagligi.joblib
  _hf/                                  # backbone'lar: wavlm-base-plus, wav2vec2-base, ...
```

Kök dizindeki `model.pt`, `labels.json`, `audio_valence_model.joblib` gibi dosyaların hangi modele ait olduğu taşıma sırasında netleştirilir; kullanılmayanlar arşive alınır.

**Prod'da internetten model indirilmez.** HF backbone'ları da `_hf/` altına önceden indirilir, worker'lar `HF_HUB_OFFLINE=1` ile çalışır. Başlangıç süresi ve HF kesintilerine bağımlılık ortadan kalkar.

#### Tek kaynak: `models/registry.yaml` (git'te)

```yaml
models:
  emotion_audio:
    display_name: "Ses emosyonu (WavLM)"
    version: v6
    worker_group: gpu            # gpu | cpu | dedicated
    adapter: workers.adapters.emotion_audio:EmotionAudioAdapter
    artifacts:
      checkpoint:
        path: emotion_audio/v6/wavlm_v6_multicrop_ema_best.pt
        sha256: "…"
    hf_dependencies: [_hf/microsoft--wavlm-base-plus]
    input: { type: audio, sample_rate: 16000, max_seconds: 300 }
    runtime: { precision: fp16, timeout_sec: 120 }
    scope: model:emotion_audio
    enabled: true

pipelines:
  fused:   [stt, text_sentiment, emotion_audio, depression, disease_wurss, age_gender]
  togg:    [emotion_audio, disease_wurss]
```

- Kod model yolunu **sadece registry'den** okur. Env'de yalnızca `MODEL_ROOT`, `REGISTRY_PATH`.
- Başlangıçta SHA256 doğrulanır; uyuşmazsa model yüklenmez ve `/ready` bunu raporlar.
- Pipeline'lar da registry'de tanımlı; yeni bir profil (ör. sadece depresyon + yaş) kod yazmadan eklenir.

#### Ortak paket: `diagvoice-backend/dv_worker/`

```python
class ModelAdapter(Protocol):
    model_id: str
    def load(self, artifacts: dict[str, Path], device: torch.device, cfg: dict) -> None: ...
    def predict(self, audio: PreparedAudio | None, params: dict) -> dict: ...
```

`dv_worker` sağlar:
- Registry'yi okuyup kendi `worker_group`'una ait modelleri **tek süreçte** yükleme.
- Kuyruk tüketici döngüsü (F4).
- `PreparedAudio`: gateway'in bir kez çözdüğü 16 kHz mono float32 dizi. Her model aynı veriyi kullanır, tekrar decode yok.
- GPU'da sıralı yürütme (tek CUDA stream, gerekirse model başına küçük batch), `torch.inference_mode()`, fp16 nerede güvenliyse.
- `/health`, `/ready` (hangi modeller yüklü), JSON log, iş zaman aşımı, hata sınıflandırma.

Mevcut servisler **tek tek** adapter'a taşınır: içerideki model kodu korunur, sadece FastAPI sarmalayıcısı ve `threading.Lock` kalkar. Her taşımadan sonra golden test.

Yük dağılımı:

| worker-gpu | worker-cpu |
|---|---|
| stt (Whisper), text_sentiment, emotion_audio, emotion_v2 (derin kısım), depression, disease_wurss, age_gender, turkish_psych | mental_fitness (ExtraTrees), occupational_health (benchmark), emotion_v2 opensmile özellikleri |

#### Yeni model ekleme süreci (hedef: yarım gün)

1. `python scripts/new_model.py --id voice_fatigue --group gpu` → iskelet üretir: `workers/adapters/voice_fatigue.py`, registry'ye taslak kayıt, `tests/golden/voice_fatigue/`.
2. Ağırlıkları `models/voice_fatigue/v1/` altına koy; `python scripts/hash_models.py` SHA256'yı registry'ye yazar.
3. Adapter'da `load()` ve `predict()` doldur.
4. Golden örnekleri ekle, `pytest`.
5. `docker compose restart worker-gpu`. Gateway registry'den `/v1/analyze/voice_fatigue` ucunu ve `model:voice_fatigue` scope'unu otomatik açar; admin'de model listesinde görünür.

Sürüm yükseltme: `v2` klasörü + registry'de `version: v2` + worker restart. Geri dönüş: registry'yi `v1`'e çekmek.

Adımlar `docs/ADDING_A_MODEL.md` dosyasında anlatılır.

**Bitti sayılır:** tüm modeller registry'den, tek GPU süreci ve tek CPU sürecinde yükleniyor; env'de model yolu kalmadı; golden testler yeşil; örnek bir dummy model iskelet scriptiyle eklenebiliyor.

---

### F3 — Konteyner yapısı ve VM kurulumu

#### VM

- AMI: Ubuntu 22.04/24.04 + NVIDIA sürücüsü (AWS "Deep Learning Base GPU AMI" pratik) + Docker + `nvidia-container-toolkit`.
- **Kalıcı veri EBS'te** (gp3): `/srv/diagvoice/{models,uploads,redis}`. g4dn'in 125 GB NVMe diski **geçicidir** (instance durunca silinir); sadece HF cache ve geçici dosyalar için kullanılır.
- 4 GB swap dosyası; Docker log rotasyonu (`max-size`, `max-file`).
- Güvenlik grubu: sadece 443 (ve 80 → 443 yönlendirme) ve yönetim için 22 (IP kısıtlı). Redis ve worker portları dışarı açık değil.
- Mongo harici kalır (mevcut); bağlantı TLS ile.

#### Image'lar

| Image | Taban | İçerik |
|---|---|---|
| `diagvoice-gateway` | `python:3.11-slim` | FastAPI, CMS, ffmpeg (ön işleme için), torch **yok** |
| `diagvoice-worker` | CUDA 12 runtime + torch (cu12) | `dv_worker`, tüm adapter'lar; aynı image hem `worker-gpu` hem `worker-cpu` olarak farklı `WORKER_GROUP` ile çalışır |

Modeller image'a girmez; volume ile bağlanır. Image boyutu ve build süresi ciddi düşer.

#### `docker-compose.prod.yml`

```text
caddy        : 80/443 dışarı, TLS otomatik, gateway'e reverse proxy, büyük upload limiti
gateway      : mem 1g, cpus 1, healthcheck /ready
redis        : AOF açık, mem 512m, sadece iç ağ
worker-gpu   : gpus: all, mem 7g, WORKER_GROUP=gpu, healthcheck
worker-cpu   : mem 3g, cpus 2, WORKER_GROUP=cpu, OMP/MKL thread = 2
```

- `restart: always`, `depends_on: condition: service_healthy`.
- `supervisord.conf` ve tek-konteyner Dockerfile kaldırılır.
- Geliştirme için `docker-compose.yml` ayrı kalır (GPU'suz makinede CPU'ya düşer).
- Dağıtım: `scripts/deploy.sh` (git pull → build → `up -d` → `/ready` kontrolü). CI/CD şimdilik yok, tek VM için yeterli.

---

### F4 — Redis kuyruk ve job API

#### Seçim

`arq` (asyncio, Redis üstünde, retry, sonuç saklama, kuyruk adına göre tüketici). Celery bu iş için ağır; kendi Redis Streams katmanımızı yazmak gereksiz risk.

Kuyruklar worker grubuna göre: `q:gpu`, `q:cpu`. (Model başına kuyruk, `dedicated` modeller için.)

#### Akış

1. Gateway dosyayı alır, boyut/süre/format kontrolü yapar (`ffprobe`), **bir kez** 16 kHz mono'ya çözer, `/data/uploads/<job_id>/audio.npy` (+ orijinal dosya, audit için) olarak yazar. Ses Redis'e konmaz.
2. Pipeline registry'den okunur. Alt işler kuyruklara atılır: ses tabanlı modeller paralel; STT bitince metin duygusu; hepsi bitince fusion birleştirmesi gateway'de yapılır.
3. Worker işi alır, sonucu Redis'e yazar (TTL 1 saat). Kalıcı özet Mongo audit'e gider.
4. Geçici dosyalar iş bitince silinir; audit için saklanan orijinal ses saklama süresine tabi.

#### İstemci API'si

| Uç | Davranış |
|---|---|
| `POST /v1/analyze/fused?wait=30` | İş `wait` saniye içinde biterse **200 + sonuç**. Bitmezse **202 + `job_id`** |
| `POST /v1/jobs` | Her zaman 202 + `job_id`. İsteğe bağlı `webhook_url` |
| `GET /v1/jobs/{id}` | `queued / running / succeeded / failed` + kuyruktaki sıra + sonuç |
| `GET /v1/jobs/{id}/events` | SSE ile ilerleme (FE'de canlı ilerleme için) |
| Webhook | İş bitince POST, `X-DiagVoice-Signature` HMAC imzalı |

#### Geri basınç ve dayanıklılık

- Kuyruk başına maksimum uzunluk; dolarsa `503 + Retry-After`.
- Key başına eşzamanlı iş limiti kuyruğa girmeden uygulanır (F1).
- İş zaman aşımı + en fazla 2 yeniden deneme. GPU OOM yakalanırsa `torch.cuda.empty_cache()` ve iş tekrar denenir; tekrar olursa `failed`.
- Öncelik (ileride): `q:gpu:high` (TOGG/ücretli) ve `q:gpu` (demo). Worker önce yüksek öncelikli kuyruğa bakar.
- Worker çökerse `restart: always`; yarım kalan iş arq tarafından tekrar kuyruğa alınır.

**Bitti sayılır:** eşzamanlı yükte istekler bağlantıda asılı kalmıyor, ya sonuç ya `job_id` dönüyor; kuyruk derinliği admin'de görünüyor; golden testler kuyruk üzerinden de yeşil.

---

### F5 — Frontend yeniden tasarım (`app/`)

#### Teknoloji

React 19 + Vite kalır. Eklenenler: **Tailwind CSS v4 + shadcn/ui** (Radix tabanlı, erişilebilir), **TanStack Query**, **Recharts**, **react-hook-form + zod**. 1770 satırlık `App.css` aşamalı olarak kaldırılır. Açık/koyu tema. Tüm API çağrıları tek bir `/v1` istemcisinden (`services/api.ts`).

#### Admin konsolu

| Sayfa | İçerik |
|---|---|
| Genel bakış | İstek/dk, hata oranı, p95 gecikme, kuyruk derinliği, GPU bellek, en çok kullanan key'ler |
| Müşteriler | Liste, detay, iletişim, durum |
| API key'ler | Oluştur (tür, scope, limit, origin, süre), **tek seferlik gösterim** + kopyala, iptal, rotate, son kullanım |
| Kullanım | Key/müşteri/route filtreli loglar, günlük grafik, CSV dışa aktarım, log detayı + ses dinleme |
| Modeller | Registry'den: sürüm, durum, hangi worker'da, ortalama süre |
| Sayfalar / Profiller | Mevcut CMS ekranları yeni tasarımla |

#### Demo sayfası

Görsel yenileme, kayıt/yükleme akışı sadeleştirme, job tabanlı canlı ilerleme (SSE), sonuç kartlarının yeniden tasarımı. `dv_pk_` key ile çalışır.

Tasarım yönü için önce 2–3 ekranın taslağı çıkarılıp onaylanacak, ardından tüm sayfalara yayılacak.

---

## 3. Sonraki tur (şimdilik kapsam dışı)

- **Yük testi** (k6, ayrı makineden): smoke, model başına baz, rampa, spike, 1 saat soak, limit doğrulama. Çıktı: kapasite raporu ve hedefler.
- **İzleme:** Prometheus metrikleri, Grafana, `nvidia-smi` exporter, alarm.
- **Performans seçenekleri** (yük testi sonucuna göre): Whisper için `faster-whisper` (CTranslate2, T4'te belirgin hızlanma; golden test ile doğrulanmalı), GPU'da batch, ortak backbone paylaşımı (WavLM/wav2vec2 birden çok modelde tekrar yükleniyor).
- Ses saklama politikası ve otomatik temizlik, yedekleme.

Bu turda bunlar için sadece altyapı hazırlanır: her istekte `X-Request-ID`, JSON log, `/health` ve `/ready`.

## 4. Riskler

| Risk | Önlem |
|---|---|
| Refactor'da model çıktısı kayar | F0 golden testleri GPU'da, her taşımada |
| Tek süreçte bir model çökerse diğerleri de etkilenir | Adapter hataları iş seviyesinde yakalanır; süreç çökerse `restart: always`; sorunlu model `dedicated` yapılabilir |
| 16 GB RAM yetmez | Ön işleme tek sefer, tek GPU süreci, `mem_limit` + swap; yük testinde ölçülecek. Yetmezse g4dn.2xlarge (32 GB) |
| Tek VM = tek hata noktası | EBS snapshot (günlük), `deploy.sh` ile hızlı kurulum; çoklu sunucu bu turun kapsamı dışında |
| Redis çökmesi | AOF kalıcılık; Redis yoksa gateway `/ready` false, 503 döner |
| Secret key mobil uygulamaya gömülür | API dokümanında açıkça uyarı; TOGG'a backend üzerinden çağırma önerisi |
| Sağlık verisi (ses kayıtları) | Saklama süresi, rol bazlı erişim; KVKK metni hukuk tarafında |

## 5. Açık sorular

1. TOGG entegrasyonu mobil uygulamadan doğrudan mı, yoksa TOGG backend'inden mi çağıracak?
2. Mongo nerede barınıyor (Atlas mı, başka sunucu mu)? Gecikme ve bağlantı limiti için önemli.
3. API için domain: `api.diagvoice.com` uygun mu? (Caddy sertifikası için DNS kaydı gerekecek.)
4. Admin paneline sen dışında kimler girecek? (Rol ihtiyacı: admin / sadece görüntüleme.)
