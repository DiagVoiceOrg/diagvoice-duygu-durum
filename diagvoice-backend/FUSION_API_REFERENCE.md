# DiagVoice Fusion API Teknik Referansı

## 1. Doküman Kapsamı

Bu doküman, DiagVoice backend üzerinde yayınlanan Fusion API endpointlerini teknik ve resmi formatta tanımlar.

Fusion servisi şu görevleri üstlenir:

- İstemci uygulamalar için **tek giriş noktası** sağlamak
- İç model servislerine istek yönlendiren **proxy katmanı** olmak
- Birden fazla model çıktısını tek yanıt altında birleştiren **bileşik analiz** (`/analyze-fused`) sunmak

Temel URL:

- `https://aiapi.diagvoice.com`

Kullanılan içerik türleri:

- Ses dosyası yüklemeleri için `multipart/form-data`
- Metin tabanlı istekler için `application/json`

---

## 2. Genel Davranış

### 2.1 Proxy Endpoint Davranışı

Bu dokümandaki endpointlerin büyük bölümü proxy endpointtir. Bu endpointlerde:

- İstek Fusion tarafından ilgili iç servise iletilir
- Upstream yanıtı JSON ise olduğu gibi döndürülür
- Upstream HTTP durum kodu korunur
- Upstream JSON dışı gövde dönerse Fusion şu formatta yanıt verir:

```json
{
  "detail": "Upstream returned non-JSON"
}
```

### 2.2 Dosya Alan Adı Kuralı

Ses yüklemelerinde `multipart/form-data` kullanılır.

- Çoğu endpoint `file` alan adını bekler
- `POST /analyze-text-audio-fusion` endpointi `audio` alan adını bekler

### 2.3 Hata Yönetimi

Yaygın hata sınıfları:

- `400`: Geçersiz payload veya zorunlu alan eksikliği
- `500`: Upstream model servisinde iç hata
- `503`: İlgili fonksiyonun devre dışı olması (örn. benchmark servis URL’i tanımlı değilse)

### 2.4 OpenAPI (otomatik — FastAPI)

Fusion servisi **FastAPI** ile çalışır; OpenAPI 3 şeması ve etkileşimli dokümantasyon ek paket gerektirmeden üretilir:

| Kaynak | Yol | Açıklama |
|--------|-----|----------|
| Swagger UI | `GET /docs` | Tarayıcıda deneme (Try it out) |
| ReDoc | `GET /redoc` | Okunabilir referans |
| OpenAPI JSON | `GET /openapi.json` | Postman/Insomnia import, kod üretimi |

Yerel geliştirme (Docker compose, port 8085):

- http://localhost:8085/docs
- http://localhost:8085/openapi.json

`GET /` yanıtındaki `openapi` nesnesi bu yolları listeler (`openapi_json` = `/openapi.json`). Proxy endpoint yanıt şemaları upstream modele göre değişir; birleşik analiz (`/analyze-fused`, `/togg-analyze`) için Fusion’un kendi Pydantic şemaları şemada tanımlıdır. CMS route’ları (`/auth`, `/public`, `/admin/*`) admin/public tag grupları altında görünür.

Bu markdown dosyası iş kuralları ve örnek yanıtlar için tam referanstır; şema ayrıntısı için `/docs` veya `/openapi.json` kullanın.

### 2.5 Wellness Companion (landing sohbet)

| Özellik | Değer |
|---------|--------|
| Path | `POST /wellness/companion/chat` |
| Mod A (metin) | `application/json` — `{ "messages", "locale?", "session_id?" }` |
| Mod B (ses) | `multipart/form-data` — `file` + `messages` (JSON string) + `locale?` |
| Başarı (metin) | `200` — `{ "message": "..." }` |
| Başarı (ses) | `200` — `{ "message": "...", "transcript": "..." }` |
| Hata | `400` / `413` / `429` / `502` / `503` — `{ "error": "..." }` |
| LLM | Sunucuda `OPENAI_API_KEY` (asla frontend’e verilmez) |
| İç çağrılar (ses) | STT (`VOICE_TO_TEXT_URL`), `POST /analyze-mental-fitness`, `validate-transcript-meaning` |
| Tool (metin) | Gerektiğinde iç `POST /analyze-turkish-psych-signals` |

Ham `mental_fitness` / skor JSON’u yanıtta dönmez. Ortam: `.env.example` içindeki `WELLNESS_*`, `OPENAI_*`.

---

## 3. Endpoint Referansı

## 3.1 GET `/`

### Amaç

Fusion servisinin genel bilgilerini, bağımlı servis URL’lerini ve proxy haritasını döndürür.

### İstek

```bash
curl -X GET "https://aiapi.diagvoice.com/"
```

### Yanıt (örnek)

```json
{
  "message": "Fusion service. POST audio to /analyze-fused.",
  "deps": {
    "voice_to_text": "http://localhost:8051/transcribe",
    "text_to_sentiment": "http://localhost:8050/analyze",
    "voice_to_sentiment": "http://localhost:8052/analyze-audio",
    "disease_service": "http://localhost:8054/analyze-disease",
    "mental_fitness": "http://localhost:8055/analyze-mental",
    "age_gender": "http://localhost:8056/analyze-age-gender",
    "depression_service": "http://localhost:8057/analyze-depression",
    "benchmark_inference": "http://127.0.0.1:8053"
  }
}
```

### Yorumlama

- Servis ayakta mı ve bağımlı servis adresleri doğru mu kontrolü için kullanılmalıdır.
- `deps` altındaki değerler, Fusion’ın iç yönlendirme hedeflerini gösterir.

---

## 3.2 POST `/analyze-fused`

### Amaç

Birleşik (fused) analiz akışını çalıştırır ve çoklu model çıktısını tek yanıtta döndürür.

### İstek

İçerik türü: `multipart/form-data`

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `file` | file | Evet | Ses dosyası |

```bash
curl -X POST "https://aiapi.diagvoice.com/analyze-fused" \
  -F "file=@sample.wav"
```

### Yanıt (genel şema)

```json
{
  "text": "string|null",
  "text_error": "string|null",
  "audio": {},
  "audio_error": "string|null",
  "disease": {},
  "disease_error": "string|null",
  "mental_fitness": {},
  "mental_fitness_error": "string|null",
  "age_gender": {},
  "age_gender_error": "string|null",
  "depression": {},
  "depression_error": "string|null",
  "benchmark_v2": {},
  "benchmark_v2_error": "string|null",
  "text_sentiment": {},
  "text_sentiment_error": "string|null",
  "valence_text": 0.0,
  "valence_audio": 0.0,
  "confidence": {
    "text": 0.0,
    "audio": 0.0,
    "disagreement": 0.0,
    "dynamic_fusion": true
  },
  "fused": {
    "valence": 0.0,
    "label": "POSITIVE|NEGATIVE|null",
    "w_text": 0.0
  },
  "unified_emotion": {
    "pred_label": "happiness",
    "pred_id": 2,
    "probs": [0.08, 0.07, 0.72, 0.13],
    "agreement": "high|medium|low",
    "disagreement": 0.31,
    "w_text": 0.58,
    "sources": {
      "text": { "sentiment": "Positive", "score": 0.91, "probs": [0.05, 0.05, 0.85, 0.05] },
      "audio": { "pred_label": "sadness", "intensity": 0.6, "probs": [0.55, 0.15, 0.2, 0.1] }
    }
  }
}
```

### Yorumlama

- `*_error` alanları alt servis çağrısının hata durumunu taşır.
- `valence_*` alanları `[0,1]` aralığında normalize skorlardır.
- `fused.label`, `fused.valence` değerine göre türetilir (`>= 0.5 => POSITIVE`).
- `confidence.disagreement`, metin ve ses valence farkını gösterir.
- `unified_emotion`, metin duygu + ses emosyonunun **4 sınıf** (sadness, fear, happiness, anger) olasılık birleşimidir; `agreement` kaynak uyumunu gösterir.

---

## 3.2.1 POST `/analyze-emotion-fusion`

### Amaç

Metin duygu ve ses emosyonu sonuçlarını (STT/ses analizi çalıştırmadan) ortak 4-sınıf uzayında birleştirir. Kısmi CMS profilleri ve harici istemciler için.

### İstek

İçerik türü: `application/json`

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `text_sentiment.sentiment` | string | Koşullu* | Positive/Negative/Notr vb. |
| `text_sentiment.score` | float | Koşullu* | `[0,1]` model skoru |
| `audio.probs` | float[4] | Koşullu* | Ses emosyon olasılıkları (sıra: sadness, fear, happiness, anger) |
| `audio.intensity` | float | Hayır | Ses yoğunluğu |
| `audio.pred_label` | string | Hayır | Ses baskın etiketi |

\* En az `text_sentiment` veya `audio` gerekir; tam birleşim için ikisi de önerilir.

```bash
curl -X POST "https://aiapi.diagvoice.com/analyze-emotion-fusion" \
  -H "Content-Type: application/json" \
  -d '{
    "text_sentiment": { "sentiment": "Positive", "score": 0.91 },
    "audio": { "probs": [0.55, 0.15, 0.2, 0.1], "intensity": 0.6, "pred_label": "sadness" }
  }'
```

### Yanıt

```json
{
  "unified_emotion": {
    "pred_label": "happiness",
    "pred_id": 2,
    "probs": [0.08, 0.07, 0.72, 0.13],
    "agreement": "medium",
    "disagreement": 0.31,
    "w_text": 0.58,
    "sources": { "text": {}, "audio": {} }
  },
  "valence_text": 0.91,
  "valence_audio": 0.35,
  "confidence": {
    "text": 0.82,
    "audio": 0.71,
    "disagreement": 0.56,
    "dynamic_fusion": true
  },
  "fused": {
    "valence": 0.72,
    "label": "POSITIVE",
    "w_text": 0.58
  }
}
```

- Geriye uyumluluk: `valence_text`, `valence_audio`, `fused`, `confidence` alanları `/analyze-fused` ile aynı anlamdadır.
- Yalnızca tek modality verilirse `unified_emotion` o kaynaktan türetilir veya eksik kaynak `null` kalır.

---

## 3.3 POST `/analyze-depression`

### Amaç

Depresyon model servisine proxy olarak yönlendirme yapar.

### İstek

İçerik türü: `multipart/form-data`

| Alan | Tip | Zorunlu |
|---|---|---|
| `file` | file | Evet |

```bash
curl -X POST "https://aiapi.diagvoice.com/analyze-depression" \
  -F "file=@sample.wav"
```

### Yanıt (örnek)

```json
{
  "pred_id": 1,
  "pred_label": "depresyon",
  "risk_level": "yuksek",
  "final_prob_depression": 0.78,
  "reliability": "orta",
  "segment_count": 8,
  "threshold": 0.5,
  "segment_probs": [0.71, 0.82, 0.76],
  "labels": {
    "0": "saglikli",
    "1": "depresyon"
  }
}
```

### Yorumlama

- Ana karar metriği `final_prob_depression` alanıdır.
- `pred_id=1` / `pred_label=depresyon`, depresyon sınıfına atandığını gösterir.
- Karar mekanizmasında `reliability` ve `segment_probs` birlikte değerlendirilmelidir.

---

## 3.4 POST `/analyze-voice-to-text`

### Amaç

Konuşmadan metne dönüştürme (STT) servisine proxy yönlendirme yapar.

### İstek

İçerik türü: `multipart/form-data`

| Alan | Tip | Zorunlu |
|---|---|---|
| `file` | file | Evet |

```bash
curl -X POST "https://aiapi.diagvoice.com/analyze-voice-to-text" \
  -F "file=@sample.wav"
```

### Yanıt (örnek)

```json
{
  "text": "Bugun kendimi daha iyi hissediyorum."
}
```

### Yorumlama

- `text`, modelin transkripsiyon çıktısıdır.
- Bu metin downstream sentiment/NLP akışlarında kullanılabilir.

---

## 3.5 POST `/analyze-text-sentiment`

### Amaç

Metin duygu analizi modeline proxy yönlendirme yapar.

### İstek

İçerik türü: `application/json`

| Alan | Tip | Zorunlu |
|---|---|---|
| `text` | string | Evet |

```bash
curl -X POST "https://aiapi.diagvoice.com/analyze-text-sentiment" \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"Bugun kendimi iyi hissediyorum\"}"
```

### Yanıt (örnek)

```json
{
  "sentiment": "POSITIVE",
  "score": 0.99
}
```

### Yorumlama

- `sentiment`, sınıf etiketidir (`POSITIVE`/`NEGATIVE`).
- `score`, seçilen sınıfa ait güven skorudur.

---

## 3.6 POST `/analyze-voice-sentiment`

### Amaç

Ses duygu/sentiment modeline proxy yönlendirme yapar.

### İstek

İçerik türü: `multipart/form-data`

| Alan | Tip | Zorunlu |
|---|---|---|
| `file` | file | Evet |

```bash
curl -X POST "https://aiapi.diagvoice.com/analyze-voice-sentiment" \
  -F "file=@sample.wav"
```

### Yanıt (örnek)

```json
{
  "pred_id": 2,
  "pred_label": "happiness",
  "probs": [0.03, 0.08, 0.84, 0.05],
  "intensity": 0.77,
  "duration_sec": 9.8,
  "num_segments": 5
}
```

### Yorumlama

- `probs` dizisinin sınıf sırası, ilgili model servisinin sınıf haritasına bağlıdır.
- `intensity`, duygusal sinyalin şiddetini gösterir.

---

## 3.7 POST `/analyze-disease`

### Amaç

Hastalık sınıflandırma model servisine proxy yönlendirme yapar.

### İstek

İçerik türü: `multipart/form-data`

| Alan | Tip | Zorunlu |
|---|---|---|
| `file` | file | Evet |

```bash
curl -X POST "https://aiapi.diagvoice.com/analyze-disease" \
  -F "file=@sample.wav"
```

### Yanıt (örnek)

```json
{
  "pred_id": 0,
  "pred_label": "healthy",
  "probs": [0.81, 0.19],
  "labels": {
    "0": "healthy",
    "1": "sick"
  }
}
```

### Yorumlama

- `pred_id`/`pred_label`, nihai sınıf kararını ifade eder.
- `probs`, sınıflar arası olasılık dağılımını verir.

---

## 3.8 POST `/analyze-mental-fitness`

### Amaç

Mental fitness model servisine proxy yönlendirme yapar.

### İstek

İçerik türü: `multipart/form-data`

| Alan | Tip | Zorunlu |
|---|---|---|
| `file` | file | Evet |

```bash
curl -X POST "https://aiapi.diagvoice.com/analyze-mental-fitness" \
  -F "file=@sample.wav"
```

### Yanıt (örnek)

```json
{
  "pred_id": 0,
  "pred_label": "healthy",
  "probs": [0.73, 0.27],
  "mental_fitness_score": 73.0
}
```

### Yorumlama

- `mental_fitness_score`, tipik olarak yüzde ölçeğinde bir yorumlanabilir skordur.
- `pred_label`, birincil sınıflandırma sonucunu gösterir.

---

## 3.9 POST `/analyze-age-gender`

### Amaç

Yaş/cinsiyet model servisine proxy yönlendirme yapar.

### İstek

İçerik türü: `multipart/form-data`

| Alan | Tip | Zorunlu |
|---|---|---|
| `file` | file | Evet |

```bash
curl -X POST "https://aiapi.diagvoice.com/analyze-age-gender" \
  -F "file=@sample.wav"
```

### Yanıt (örnek)

```json
{
  "gender": {
    "pred_id": 1,
    "pred_label": "male",
    "probs": [0.21, 0.79],
    "source": "ready_model"
  },
  "agebin": {
    "pred_id": 2,
    "pred_label": "26-35",
    "probs": [0.05, 0.18, 0.62, 0.15]
  }
}
```

### Yorumlama

- `gender` ve `agebin` çıktıları bağımsız sınıflandırma çıktılarıdır.
- `source`, cinsiyet tahmininin hangi model yoluyla üretildiğini belirtir.

---

## 3.10 POST `/analyze-text-audio-fusion`

### Amaç

Text-sentiment servisinin metin+ses füzyon endpointine proxy yönlendirme yapar.

### İstek

İçerik türü: `multipart/form-data`

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `text` | text | Evet | Girdi metni |
| `audio` | file | Evet | Ses dosyası |
| `fusion_mode` | text | Hayır | `dynamic` (varsayılan) veya `fixed` |

```bash
curl -X POST "https://aiapi.diagvoice.com/analyze-text-audio-fusion" \
  -F "text=Kendimi biraz yorgun ama iyi hissediyorum." \
  -F "fusion_mode=dynamic" \
  -F "audio=@sample.wav"
```

### Yanıt (örnek)

```json
{
  "text": {
    "sentiment": "POSITIVE",
    "score": 0.93,
    "valence_text": 0.93
  },
  "audio": {
    "valence_audio": 0.44
  },
  "fusion": {
    "mode": "dynamic",
    "w_text": 0.91,
    "valence_fused": 0.88
  }
}
```

### Yorumlama

- `w_text`, metin skorunun birleşik skordaki ağırlığını belirtir.
- `valence_fused`, nihai ağırlıklı sonuçtur.
- `mode=dynamic`, güvene bağlı ağırlık ayarlaması yapar.

---

## 3.11 POST `/analyze-benchmark-v2`

### Amaç

İç benchmark inference endpointine proxy yönlendirme yapar.

### İstek

İçerik türü: `multipart/form-data`

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `file` | file | Evet | Ses dosyası (upstream tarafında `audio` alanına map edilir) |
| `transcript` | text | Hayır | Opsiyonel transkript |

```bash
curl -X POST "https://aiapi.diagvoice.com/analyze-benchmark-v2" \
  -F "file=@sample.wav" \
  -F "transcript=Bugun kendimi iyi hissediyorum"
```

### Yanıt (örnek)

```json
{
  "ok": true,
  "prediction": "string_or_object",
  "meta": {}
}
```

### Yorumlama

- Yanıt gövdesinin kesin şeması benchmark inference servisinin sözleşmesine bağlıdır.
- Benchmark devre dışı ise endpoint `503` ile şu yanıtı döndürür:

```json
{
  "detail": "benchmark_v2 disabled (INFERENCE_API_URL empty)"
}
```

---

## 4. Entegrasyon Önerileri

- Ses dosyası göndermeden önce istemci tarafında boyut ve mime-type doğrulaması yapılmalıdır.
- Ağ gecikmeleri için istemci tarafında timeout ve kontrollü retry politikası tanımlanmalıdır.
- Proxy zincirinde izlenebilirlik için korelasyon kimliği (request id) loglanmalıdır.
- Model çıktıları olasılıksal sinyal olarak ele alınmalı; deterministik tanı çıktısı gibi kullanılmamalıdır.

---

## 5. Sürüm Notu

Bu doküman, `fusion_service/app.py` içinde halihazırda tanımlı route’lara göre hazırlanmıştır.  
İç servis sözleşmeleri değiştiğinde proxy yanıt şemaları da değişebilir.

---

## 6. Frontend Gösterim Eşlemesi (Parametre Bazlı)

Bu bölüm, mevcut frontend implementasyonunda response alanlarının hangi görsel bileşenlere bağlandığını açıklar.

Referans dosyalar:

- `app/src/services/analyzeFused.js`
- `app/src/App.jsx`
- `app/src/components/ModelDetailsPage.jsx`

### 6.1 İstek Akışı (Frontend)

- Frontend şu anda analiz için doğrudan `POST /analyze-fused` çağırır.
- Çağrı `multipart/form-data` ile tek dosya alanı (`file`) gönderir.
- Endpoint bazlı diğer çağrılar (`/analyze-depression`, `/analyze-disease` vb.) frontend’de ayrı ayrı tetiklenmez; bu endpointler daha çok API tüketicileri ve Postman kullanımı içindir.

### 6.2 Aktif Ekranda Gösterilen Sonuçlar (Özet Sayfası)

#### A) İş Sağlığı kartı (`benchmark_v2` üzerinden)

Kullanılan alanlar:

- `benchmark_v2.positive_class_probability`
  - Kart başlığındaki durum rengini belirler.
  - Eşik karşılaştırması (`>= 0.5`) ile metin üretir:
    - `Tanılı riski`
    - `Sağlıklı profil`
  - Skor bar yüzdesi (`%`) olarak gösterilir.
- `benchmark_v2.mode`
  - Varsa “Model modu: ...” satırında gösterilir.
- `benchmark_v2.error` veya `benchmark_v2_error`
  - Kart içinde hata mesajı olarak gösterilir.

UI yorum kuralı:

- Nihai UI sınıflaması, `positive_class_probability` değerinin `0.5` eşiğine göre yapılır.

#### B) Depresyon kartı (`depression` üzerinden)

Kullanılan alanlar:

- `depression.pred_label`
  - `depresyon` ise “Durum: Depresyon Riski”
  - Diğer durumda “Durum: Sağlıklı”
- `depression.risk_level`
  - `dusuk|orta|yuksek` değerleri TR etikete çevrilir (`Düşük|Orta|Yüksek`)
  - Kart vurgu rengi risk seviyesinden üretilir.
  - Sadece `pred_label=depresyon` ise metinde “Risk seviyesi” satırı gösterilir.
- `depression.final_prob_depression`
  - “Skor” ilerleme barı ve yüzde değerinde kullanılır.

UI yorum kuralı:

- Kartın ana karar metni `pred_label` tabanlıdır.
- Nicel risk şiddeti `final_prob_depression` ve `risk_level` ile desteklenir.

### 6.3 Frontend’de State’e Alınan ama Aktif Ekranda Gizli Alanlar

Not: Aşağıdaki alanlar kodda state’e yazılır; ancak mevcut “Özet” ekranında kartları yorum satırına alındığı için görünmez.

#### A) Metin transkripsiyonu

- `text` -> `_transcribedText`
- Olası kullanım: “Çevrilen Metin” kartı (şu an kapalı)

#### B) Metin duygu analizi

- `text_sentiment.sentiment`, `text_sentiment.score` -> `_sentimentResult`
- Olası kullanım: Sentiment görselleştirici bileşeni (şu an kapalı)

#### C) Ses emosyonu

- `audio.pred_label`, `audio.probs`, `audio.intensity` -> `_audioEmotionResult`
- Olası kullanım: Emosyon etiketi, güven rozeti, dağılım barları (şu an kapalı)

#### D) Hastalık (WURSS) kartı

- `disease.pred_label`, `disease.probs` -> `_diseaseResult`
- Olası kullanım: Sağlıklı/Hasta kartı (şu an kapalı)

#### E) Mental fitness kartı

- `mental_fitness.pred_label`, `mental_fitness.mental_fitness_score` -> `_mentalFitnessResult`
- Olası kullanım: Mental fitness skor kartı (şu an kapalı)

#### F) Yaş-cinsiyet ve füzyon metrikleri (detay sekmesi)

- `age_gender` -> `_ageGenderResult`
- `age_gender_error` -> `_ageGenderError`
- `valence_text`, `valence_audio`, `fused` -> `_valenceResult`
- `unified_emotion` -> `_unifiedEmotionResult` (4-sınıf birleşik emosyon kartı)
- `confidence` -> `_confidenceResult`

Bu alanlar `ModelDetailsPage` içinde aşağıdaki kartlara karşılık gelir (detay sekmesi tekrar açılırsa):

- Yaş & Cinsiyet kartı (`age_gender.gender`, `age_gender.agebin`)
- Birleşik emosyon kartı (`unified_emotion.pred_label`, `probs`, `agreement`, `sources`)
- Fused Duygu kartı (`fused.valence`, `fused.label`, `fused.w_text`)
- Metin/Ses valence karşılaştırması (`valence_text`, `valence_audio`)
- Güven ve uyumsuzluk kartı (`confidence.text`, `confidence.audio`, `confidence.disagreement`, `confidence.dynamic_fusion`)

### 6.4 Endpoint Bazlı Frontend Kullanım Durumu

- `POST /analyze-fused`:
  - **Doğrudan kullanılıyor** (tam profil analiz akışı)
- `POST /analyze-emotion-fusion`:
  - **Kısmi profillerde kullanılıyor** (`analyzePartial.js`: sentiment + audio_emotion sonrası)
- `POST /analyze-depression`:
  - Frontend tarafından doğrudan çağrılmıyor; `/analyze-fused` içindeki `depression` alanı kullanılıyor.
- `POST /analyze-voice-to-text`:
  - Doğrudan çağrılmıyor; `/analyze-fused` içindeki `text` alanı kullanılabilir.
- `POST /analyze-text-sentiment`:
  - Doğrudan çağrılmıyor; `/analyze-fused` içindeki `text_sentiment` alanı kullanılabilir.
- `POST /analyze-voice-sentiment`:
  - Doğrudan çağrılmıyor; `/analyze-fused` içindeki `audio` alanı kullanılabilir.
- `POST /analyze-disease`:
  - Doğrudan çağrılmıyor; `/analyze-fused` içindeki `disease` alanı kullanılabilir.
- `POST /analyze-mental-fitness`:
  - Doğrudan çağrılmıyor; `/analyze-fused` içindeki `mental_fitness` alanı kullanılabilir.
- `POST /analyze-age-gender`:
  - Doğrudan çağrılmıyor; `/analyze-fused` içindeki `age_gender` alanı kullanılabilir.
- `POST /analyze-text-audio-fusion`:
  - Doğrudan çağrılmıyor.
- `POST /analyze-benchmark-v2`:
  - Doğrudan çağrılmıyor; `/analyze-fused` içindeki `benchmark_v2` alanı aktif kartta gösteriliyor.

### 6.5 Uygulama Notu (Dokümantasyon Tutarlılığı)

Frontend şu an ana senaryoda yalnızca `/analyze-fused` tükettiği için, ürün dokümantasyonunda:

- “Birincil istemci endpointi” olarak `/analyze-fused`
- “Servis seviyesinde teknik endpointler” olarak diğer proxy endpointler

ayrımı açıkça belirtilmelidir.

---

## 7. Proxy Endpoint Response Şemaları ve Alan Açıklamaları

Bu bölümde, her proxy endpoint için **beklenen response şeması** ve alanların işlevi tanımlanır.  
Not: Fusion proxy katmanı upstream yanıtını passthrough ettiği için, aşağıdaki şemalar “mevcut servis kontratına göre beklenen standart alanları” ifade eder.

## 7.1 `POST /analyze-depression`

### Standart başarı şeması

```json
{
  "pred_id": 0,
  "pred_label": "saglikli|depresyon",
  "risk_level": "dusuk|orta|yuksek",
  "final_prob_depression": 0.0,
  "mean_prob_depression": 0.0,
  "median_prob_depression": 0.0,
  "trimmed_mean_prob_depression": 0.0,
  "std_prob_depression": 0.0,
  "min_prob_depression": 0.0,
  "max_prob_depression": 0.0,
  "reliability": "dusuk|orta|yuksek",
  "is_unstable": false,
  "segment_count": 0,
  "threshold": 0.5,
  "segment_probs": [0.0],
  "labels": {
    "0": "saglikli",
    "1": "depresyon"
  }
}
```

### Alan açıklamaları

- `pred_id`: Nihai sınıf id’si (`0` sağlıklı, `1` depresyon).
- `pred_label`: Nihai sınıf etiketi.
- `risk_level`: Final olasılığa göre risk seviyesi.
- `final_prob_depression`: Ana karar olasılığı (depresyon olasılığı).
- `mean_prob_depression`: Segment olasılıklarının ortalaması.
- `median_prob_depression`: Segment olasılıklarının medyanı.
- `trimmed_mean_prob_depression`: Aykırı değer kırpılmış ortalama.
- `std_prob_depression`: Segmentler arası oynaklık (belirsizlik göstergesi).
- `min_prob_depression` / `max_prob_depression`: Segment bazlı alt/üst sınır.
- `reliability`: Tahmin güvenilirlik etiketi.
- `is_unstable`: Segment tahminleri yüksek varyanslı mı.
- `segment_count`: Değerlendirilen segment sayısı.
- `threshold`: Karar eşiği.
- `segment_probs`: Segment bazında depresyon olasılıkları.
- `labels`: Sınıf haritası.

## 7.2 `POST /analyze-voice-to-text`

### Standart başarı şeması

```json
{
  "text": "string"
}
```

### Alan açıklamaları

- `text`: Konuşmadan metne dönüştürülmüş transkript.

## 7.3 `POST /analyze-text-sentiment`

### Standart başarı şeması

```json
{
  "sentiment": "POSITIVE|NEGATIVE",
  "score": 0.0
}
```

### Alan açıklamaları

- `sentiment`: Tahmin edilen duygu sınıfı.
- `score`: Seçilen sınıfa ait güven skoru (`0..1`).

## 7.4 `POST /analyze-voice-sentiment`

### Standart başarı şeması

```json
{
  "pred_id": 0,
  "pred_label": "sadness|fear|happiness|anger",
  "probs": [0.0, 0.0, 0.0, 0.0],
  "intensity": 0.0,
  "sample_rate": 16000,
  "duration_sec": 0.0,
  "num_segments": 1,
  "labels": {
    "0": "sadness",
    "1": "fear",
    "2": "happiness",
    "3": "anger"
  }
}
```

### Alan açıklamaları

- `pred_id`: En yüksek olasılıklı emosyon sınıfının id’si.
- `pred_label`: En yüksek olasılıklı emosyon etiketi.
- `probs`: Sınıf olasılık dağılımı (sıra `labels` ile eşleşir).
- `intensity`: Duygusal şiddet skoru (`0..1`).
- `sample_rate`: İşlenen ses örnekleme hızı.
- `duration_sec`: Analiz edilen ses süresi (saniye).
- `num_segments`: Çoklu crop/segment sayısı.
- `labels`: Sınıf haritası.

## 7.5 `POST /analyze-disease`

### Standart başarı şeması

```json
{
  "pred_id": 0,
  "pred_label": "healthy|sick",
  "probs": [0.0, 0.0],
  "labels": {
    "0": "healthy",
    "1": "sick"
  }
}
```

### Alan açıklamaları

- `pred_id`: Nihai sınıf id’si.
- `pred_label`: Nihai sınıf etiketi.
- `probs`: İkili sınıf olasılık dağılımı.
- `labels`: Sınıf haritası.

## 7.6 `POST /analyze-mental-fitness`

### Standart başarı şeması

```json
{
  "pred_id": 0,
  "pred_label": "healthy|depression",
  "probs": [0.0, 0.0],
  "mental_fitness_score": 0.0
}
```

### Alan açıklamaları

- `pred_id`: Nihai sınıf id’si (model sınıflarına göre).
- `pred_label`: Nihai sınıf etiketi.
- `probs`: Sınıf olasılıkları (model `predict_proba` destekliyorsa).
- `mental_fitness_score`: Sağlıklılık/uygunluk skoru (genellikle `%` ölçeğinde yorumlanır).

## 7.7 `POST /analyze-age-gender`

### Standart başarı şeması

```json
{
  "gender": {
    "pred_id": 0,
    "pred_label": "female|male",
    "probs": [0.0, 0.0],
    "source": "ready_model|multitask_fallback"
  },
  "agebin": {
    "pred_id": 0,
    "pred_label": "string",
    "probs": [0.0]
  }
}
```

### Alan açıklamaları

- `gender.pred_id`: Cinsiyet sınıf id’si.
- `gender.pred_label`: Cinsiyet etiketi.
- `gender.probs`: Cinsiyet sınıf olasılıkları.
- `gender.source`: Cinsiyet çıktısının hangi model yolundan geldiği.
- `agebin.pred_id`: Yaş grubu sınıf id’si.
- `agebin.pred_label`: Yaş grubu etiketi.
- `agebin.probs`: Yaş grubu sınıf olasılık dağılımı.

## 7.8 `POST /analyze-text-audio-fusion`

### Standart başarı şeması

```json
{
  "text": {
    "sentiment": "POSITIVE|NEGATIVE",
    "score": 0.0,
    "valence_text": 0.0
  },
  "audio": {
    "valence_audio": 0.0
  },
  "fusion": {
    "mode": "dynamic|fixed",
    "w_text": 0.0,
    "valence_fused": 0.0
  }
}
```

### Alan açıklamaları

- `text.sentiment`: Metin duygu sınıfı.
- `text.score`: Metin duygu model güven skoru.
- `text.valence_text`: Metinden türetilmiş valence (`0..1`).
- `audio.valence_audio`: Sesten türetilmiş valence (`0..1`).
- `fusion.mode`: Ağırlıklandırma modu.
- `fusion.w_text`: Metin ağırlığı (`0..1`).
- `fusion.valence_fused`: Nihai füzyon valence skoru (`0..1`).

## 7.9 `POST /analyze-benchmark-v2`

### Standart başarı şeması

```json
{
  "mode": "scalar_only|scalar_hgb|scalar_embed_pca",
  "positive_class_probability": 0.0,
  "threshold_tuned": 0.5,
  "threshold_objective": "balanced_accuracy",
  "predicted_class": 0,
  "class_names_hint": "0: sağlıklı, 1: tanılı (eğitim etiketine bağlı — benchmark ile doğrulayın)"
}
```

### Alan açıklamaları

- `mode`: Model bundle çalışma modu.
- `positive_class_probability`: Pozitif sınıf olasılığı (`P(class=1)`).
- `threshold_tuned`: Sınıflandırma için kullanılan karar eşiği.
- `threshold_objective`: Eşik optimizasyon hedef metriği.
- `predicted_class`: Eşik sonrası nihai sınıf (`0/1`).
- `class_names_hint`: Sınıf yorumlama notu.

### Hata şemaları

```json
{
  "error": "string"
}
```

veya:

```json
{
  "error": "string",
  "mode": "string"
}
```

Ayrıca Fusion tarafında servis devre dışı ise:

```json
{
  "detail": "benchmark_v2 disabled (INFERENCE_API_URL empty)"
}
```

## 7.10 `POST /analyze-fused` (Bileşik yanıt şeması)

`/analyze-fused`, yukarıdaki alt model çıktılarının birleşik gövdesini döndürür.

### Standart bileşik şema

```json
{
  "text": "string|null",
  "text_error": "string|null",
  "audio": {},
  "audio_error": "string|null",
  "disease": {},
  "disease_error": "string|null",
  "mental_fitness": {},
  "mental_fitness_error": "string|null",
  "age_gender": {},
  "age_gender_error": "string|null",
  "depression": {},
  "depression_error": "string|null",
  "benchmark_v2": {},
  "benchmark_v2_error": "string|null",
  "text_sentiment": {},
  "text_sentiment_error": "string|null",
  "valence_text": 0.0,
  "valence_audio": 0.0,
  "confidence": {
    "text": 0.0,
    "audio": 0.0,
    "disagreement": 0.0,
    "dynamic_fusion": true
  },
  "fused": {
    "valence": 0.0,
    "label": "POSITIVE|NEGATIVE|null",
    "w_text": 0.0
  },
  "unified_emotion": {
    "pred_label": "happiness",
    "pred_id": 2,
    "probs": [0.08, 0.07, 0.72, 0.13],
    "agreement": "high|medium|low",
    "disagreement": 0.31,
    "w_text": 0.58,
    "sources": { "text": {}, "audio": {} }
  }
}
```

### Alan açıklamaları (özet)

- `text` / `text_error`: STT sonucu ve hata bilgisi.
- `audio` / `audio_error`: Ses duygu sonucu ve hata bilgisi.
- `unified_emotion`: Metin+ses 4-sınıf birleşik emosyon (`sadness`, `fear`, `happiness`, `anger`); `sources` altında kaynak dağılımları.
- `disease` / `disease_error`: Hastalık modeli sonucu ve hata bilgisi.
- `mental_fitness` / `mental_fitness_error`: Mental fitness sonucu ve hata bilgisi.
- `age_gender` / `age_gender_error`: Yaş-cinsiyet sonucu ve hata bilgisi.
- `depression` / `depression_error`: Depresyon sonucu ve hata bilgisi.
- `benchmark_v2` / `benchmark_v2_error`: Benchmark sonucu ve hata bilgisi.
- `text_sentiment` / `text_sentiment_error`: Metin duygu sonucu ve hata bilgisi.
- `valence_text`: Metinden normalize valence.
- `valence_audio`: Sesten normalize valence.
- `confidence.text`: Metin valence güveni.
- `confidence.audio`: Ses valence güveni.
- `confidence.disagreement`: Metin ve ses valence farkı.
- `confidence.dynamic_fusion`: Dinamik füzyon aktifliği.
- `fused.valence`: Nihai birleşik valence.
- `fused.label`: Nihai sınıf etiketi.
- `fused.w_text`: Nihai hesapta kullanılan metin ağırlığı.

