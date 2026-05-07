# Türkçe psikolojik sinyal sınıflandırıcı

Bu klasör, Hugging Face Transformers ile fine-tune edilmiş **Türkçe psikolojik sinyal** metin sınıflandırma modelini ve HTTP servisini içerir. **`mental_fitness` (ses tabanlı skor) servisinden tamamen bağımsızdır**; farklı amaçlar için kullanılır.

**Önemli:** Bu model **`POST /analyze-fused` birleşik analiz akışına dahil değildir.** Kullanım, doğrudan mikro servis veya Fusion üzerindeki **ayrı proxy endpoint** ile yapılır.

---

## 1. Dağıtım dosyaları

Inference için gerekli dosyalar (bu klasör kökü):

| Dosya | Açıklama |
|--------|-----------|
| `config.json` | Model mimarisi ve `id2label` / `label2id` |
| `../models/mental-fitness-forgpt.safetensors` | Ağırlıklar (**Git’te takip edilmez**; `diagvoice-backend/models/` altına koy veya `TURKISH_PSYCH_WEIGHTS_PATH`) |
| `tokenizer.json` | Tokenizer |
| `tokenizer_config.json` | Tokenizer ayarları |
| `label_maps.json` | Eğitim/config ile uyumlu sınıf indeksi ↔ `label_id` string eşlemesi |

İsteğe bağlı:

- `psych_category_names_tr.json` — `label_id` (ör. `"10"`) → Türkçe okunabilir kategori adı. Servis bu dosyayı okur; tanımı olmayan etiketler için yanıtta yalnızca `label_id` ve `score` döner.
- `training_args.bin` — Yalnızca eğitim bilgisi; inference için gerekli değildir.

**Checkpoint klasörleri** (`checkpoint-*`) deploy paketine konmamalıdır; Docker imajında `.dockerignore` ile hariç tutulur.

---

## 2. Çalıştırma (mikro servis)

Varsayılan port: **8058** (`TURKISH_PSYCH_CLASSIFIER_PORT`).

Kök dizinden (veya `PYTHONPATH=/app` ile konteyner içinde):

```bash
export TURKISH_PSYCH_MODEL_DIR="$(pwd)/mental_fitness_turkish_psych_classifier"
export TURKISH_PSYCH_CLASSIFIER_PORT=8058
python mental_fitness_turkish_psych_classifier/app.py
```

### Ortam değişkenleri (özet)

| Değişken | Varsayılan / not |
|-----------|-------------------|
| `TURKISH_PSYCH_CLASSIFIER_PORT` | `8058` |
| `TURKISH_PSYCH_MODEL_DIR` | Config + tokenizer klasörü (`.../mental_fitness_turkish_psych_classifier`) |
| `TURKISH_PSYCH_WEIGHTS_PATH` | `mental-fitness-forgpt.safetensors` mutlak yolu (varsayılan: `diagvoice-backend/models/mental-fitness-forgpt.safetensors`) |
| `TURKISH_PSYCH_LABEL_MAPS` | `{MODEL_DIR}/label_maps.json` |
| `TURKISH_PSYCH_CATEGORY_NAMES_TR` | Bu klasörde `psych_category_names_tr.json` |
| `TURKISH_PSYCH_USE_INFER_LOCK` | `1` — eşzamanlı isteklerde tek iş parçacığı kuyruğu |
| `CORS_ALLOW_ORIGINS` | Diğer servislerle aynı kalıp (virgülle ayrılmış origin listesi) |

---

## 3. Doğrudan servis API’si

Base URL örnek: `http://127.0.0.1:8058`

### `GET /`

Servis özeti ve model dizini.

### `GET /health`

`{"ok": true|false, "model_dir": "..."}` — model pipeline yüklü mü.

### `POST /analyze`

**İçerik tipi:** `application/json`

**Gövde:**

```json
{
  "text": "Son zamanlarda çok bunaldım."
}
```

**Yanıt (özet şema):**

```json
{
  "text": "Son zamanlarda çok bunaldım.",
  "predictions": [
    {
      "label_raw": "LABEL_2",
      "label_id": "10",
      "score": 0.52,
      "category_name_tr": "Depresif Belirtiler / Öz Güven Kaybı"
    }
  ],
  "top_prediction": { }
}
```

- **`label_raw`:** Transformers’ın döndürdüğü ham etiket (ör. `LABEL_2`).
- **`label_id`:** `label_maps.json` / `config.json` ile uyumlu kanonik id (`"0"` … `"15"` stringleri).
- **`category_name_tr`:** Yalnızca `psych_category_names_tr.json` içinde tanımı varsa eklenir.
- **`predictions`:** Tüm sınıfların skorları, `score` azalan sırada.
- **`top_prediction`:** En yüksek skorlu satır (veya boş liste durumunda `null`).

**Hatalar:** Boş metin `400`; model yüklenemediyse `503`.

---

## 4. Fusion üzerinden proxy (önerilen dış kullanım)

Fusion ana birleşik endpoint **`/analyze-fused` bu modeli çağırmaz.** Dış istemciler için Fusion’da ayrı bir proxy tanımlıdır:

| Özellik | Değer |
|--------|--------|
| **Yöntem** | `POST` |
| **Yol** | `/analyze-turkish-psych-signals` |
| **Base** | Fusion’un public URL’si (ör. `https://aiapi.diagvoice.com`) |
| **İçerik tipi** | `application/json` |
| **Gövde** | `{"text": "..."}` (alan `text` zorunlu) |

Fusion, isteği iç ağdaki Türkçe psik servisine iletir; HTTP durumu ve JSON gövdesi upstream ile uyumludur (Fusion’daki diğer JSON proxy’ler gibi).

### Fusion ortamı

| Değişken | Açıklama |
|----------|-----------|
| `TURKISH_PSYCH_CLASSIFIER_URL` | Fusion’un `POST /analyze-turkish-psych-signals` proxy hedefi (örn. `http://127.0.0.1:8058/analyze`). **`/analyze-fused` bu değişkene bağlı değildir** — birleşik akışa dahil edilmez. **Boş string** = proxy kapalı (`503`). Dışarıda yalnızca `:8085` açıksa bu URL’nin dolu olması gerekir. |

Dockerfile / `supervisord` varsayılanında iç URL: `http://127.0.0.1:8058/analyze`.

### Örnek `curl` (Fusion proxy)

```bash
curl -sS -X POST "https://ORNEK_FUSION_HOST/analyze-turkish-psych-signals" \
  -H "Content-Type: application/json" \
  -d '{"text":"Son zamanlarda çok bunaldım."}'
```

### `GET /` (Fusion kök)

Yanıttaki `deps.turkish_psych_classifier` ve `proxy.turkish_psych_signals` alanları güncel upstream adresini ve kısa açıklamayı gösterir.

---

## 5. Türkçe kategori isimlerini genişletme

1. `psych_category_names_tr.json` dosyasını düzenle.
2. Anahtarlar **`label_id`** olmalı (model/config ile aynı stringler: `"0"`, `"1"`, `"10"` …).
3. Servisi yeniden başlat (dosya startup’ta okunur; ileride hot-reload eklenebilir).

Örnek:

```json
{
  "10": "Depresif Belirtiler / Öz Güven Kaybı",
  "3": "Diğer kategori açıklaması"
}
```

---

## 6. Mimari not

- **Supervisor program adı:** `turkish-psych-classifier` (Docker içi).
- **Port:** `8058` (diğer iç servisler 8050–8057 aralığında).
- Bu servis **`/analyze-fused` zincirine eklenmedi**; istenen yerde yalnızca `POST /analyze-turkish-psych-signals` veya doğrudan `POST ...:8058/analyze` çağrılır.

Sorular veya sözleşme değişiklikleri için Fusion tarafındaki `fusion_service/app.py` içinde `analyze-turkish-psych-signals` ve bu klasördeki `app.py` referans alınabilir.

## 7. Admin panel — model durumu

CMS endpoint’i `GET /admin/diagnostics/models-health` (admin JWT) bu servis için **`GET /health`** probu çalıştırır (`ok: true` ve HTTP 200 beklenir). Varsayılan URL: `http://127.0.0.1:8058/health` (`TURKISH_PSYCH_CLASSIFIER_PORT` ile uyumlu). Taramayı kapatmak için ortamda **`TURKISH_PSYCH_HEALTH_URL=`** (boş) bırakın. Özel URL için `TURKISH_PSYCH_HEALTH_URL` tam adres verin.
