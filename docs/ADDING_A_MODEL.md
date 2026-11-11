# Yeni model ekleme

Hedef: yeni bir modeli yarım günde, gateway koduna dokunmadan yayına almak.

## Nasıl çalışıyor

- **`diagvoice-backend/registry.yaml`** tüm modellerin tek kaynağıdır: dosya yolu, SHA256, hangi worker'da (gpu | cpu) çalışacağı, servis modülü.
- **Worker** (`dv_worker`) açılışta kendi grubundaki modelleri tek süreçte yükler, SHA256'yı doğrular ve her servisi `/<model_id>` altına bağlar. Durum: `GET http://127.0.0.1:8060/ready` (gpu), `:8061/ready` (cpu).
- **Gateway** registry'de `v1:` bloğu olan her model için `/v1/analyze/<model_id>` ucunu ve `model:<model_id>` scope'unu otomatik açar.

## Adımlar

### 1. İskeleti üret

```bash
python scripts/new_model.py --id voice_fatigue --title "Ses yorgunluğu" --group gpu --input audio --weights model.pt
```

Oluşan dosyalar:

- `diagvoice-backend/services/voice_fatigue/app.py`: `load()` ve `POST /analyze` iskeleti
- `diagvoice-backend/registry.yaml` içinde taslak kayıt

Seçenekler: `--group cpu` (sklearn vb.), `--input text` (JSON `{"text": ...}`).

### 2. Ağırlıkları koy ve SHA256'yı yaz

Sunucuda, model kökü altına (`/opt/api/diagvoice-backend/models`, konteynerde `/app/models`):

```bash
mkdir -p diagvoice-backend/models/voice_fatigue/v1
cp model.pt diagvoice-backend/models/voice_fatigue/v1/
python scripts/hash_models.py --write     # registry.yaml'daki sha256'yı doldurur
python scripts/hash_models.py             # hepsi OK olmalı
```

Model dosyaları git'e girmez (`.gitignore`). `registry.yaml` girer.

### 3. Modeli bağla

`services/voice_fatigue/app.py` içinde iki yer:

- **`load()`**: yolu `os.environ["VOICE_FATIGUE_MODEL_PATH"]`'ten al (registry `env:` ile verir), modeli `model` değişkenine yükle. Yükleme başarısız olur da `model` `None` kalırsa worker `/ready`'de hata verir (`require: [model]`).
- **`_predict_sync()`**: çıkarım. Ses için `audio_io.load_mono_float32(path, sr=16000)` hazır.

Hugging Face'ten backbone gerekiyorsa `from_pretrained(...)` kullan; ilk açılışta `/app/.cache/huggingface` altına iner.

### 4. Test

```bash
cd diagvoice-backend
pytest tests/test_worker.py -q
```

Golden örnek eklemek için `tests/golden/cases.py`'ye uç ve örnekleri ekle; sunucuda `python -m tests.golden.capture --base-url http://127.0.0.1:8085 --only voice_fatigue` ile kaydet.

### 5. Yayına al

```bash
cd /opt/api && git pull --ff-only
docker compose restart backend
curl -s http://127.0.0.1:8060/ready | python3 -m json.tool      # voice_fatigue: ready
```

Gateway'de otomatik açılanlar:

- `POST /v1/analyze/voice_fatigue` (multipart `file` veya JSON `text`)
- `model:voice_fatigue` scope'u: admin panelinden anahtara verilir (`PATCH /admin/keys/{key_id}` → `scopes`)

## Sürüm yükseltme ve geri dönüş

- Yeni sürüm: `models/voice_fatigue/v2/` klasörü → registry'de `version: v2` ve `path` → `hash_models.py --write` → restart.
- Geri dönüş: registry'yi önceki commit'e al (`git checkout <commit> -- diagvoice-backend/registry.yaml`) → restart.
- Modeli kapatmak: registry'de `enabled: false` → restart.

## Mevcut modeller ve eski düzen

Mevcut 10 model (`text_sentiment`, `stt`, `emotion_audio`, `disease_wurss`, `depression`, `age_gender`, `turkish_psych`, `emotion_v2`, `mental_fitness`, `occupational_health`) aynı registry'den yüklenir. Kendi elle yazılmış `/v1` uçları vardır; `v1:` bloğu yalnızca yeni modeller içindir.

Sorun olursa eski düzene (her model ayrı süreç) dönmek için `.env`'e `WORKER_MODE=legacy` yazıp `docker compose up -d --force-recreate backend`.
