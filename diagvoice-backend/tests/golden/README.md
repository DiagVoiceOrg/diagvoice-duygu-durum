# Golden testler

Refactor sırasında (registry, worker, kuyruk, `/v1`) **model çıktılarının değişmediğini** kanıtlamak için.

1. **Kayıt:** Mevcut, çalışan sisteme sabit istekler atılır (`cases.py`), yanıtlar `snapshots/` altına yazılır.
2. **Karşılaştırma:** Her değişiklikten sonra aynı istekler yeni sisteme atılır, yanıtlar kayıtla toleranslı karşılaştırılır.

Snapshot'lar **GPU sunucusunda (g4dn.xlarge) alınmalı**. CPU ve GPU (fp16) çıktıları küçük farklar verir; referans prod ortamı olmalı.

## Kurulum

```bash
cd diagvoice-backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
```

## 1) Snapshot kaydı (bir kez, refactor'dan önce)

Sunucuda, mevcut sistem çalışırken. Kayıt sırasında rastgelelik ve gereksiz yan etkileri kapatın: depo kökündeki `.env`'e geçici olarak

```dotenv
TOGG_DIVERSIFY_ENABLED=0        # TOGG çıktısına bilinçli jitter ekleyen katman
AUDIT_LOG_ENABLED=0             # 150+ test isteği kullanım loglarına düşmesin
AUDIT_AUDIO_STORAGE_ENABLED=0   # test sesleri diske kaydedilmesin
```

ekleyip konteyneri yeniden oluşturun:

```bash
docker compose up -d --force-recreate backend
```

Sonra:

```bash
cd diagvoice-backend
python -m tests.golden.capture --list                                 # vakaları gör
python -m tests.golden.capture --base-url http://127.0.0.1:8085       # tümünü kaydet
python -m tests.golden.capture --base-url http://127.0.0.1:8085 --only analyze-fused   # bir kısmı
```

- Her vaka 2 kez çalıştırılır. İki koşu arasında değişen alanlar `volatile_paths` olarak kaydedilir ve karşılaştırmada yok sayılır.
- `UYARI` satırlarını okuyun: 5xx, koşular arasında farklı durum ya da TOGG skorlarının değişmesi kaydın güvenilir olmadığını gösterir.
- Bittiğinde `.env`'deki geçici satırları geri alın ve `snapshots/` klasörünü git'e ekleyin.

## 2) Karşılaştırma (her değişiklikten sonra)

```bash
GOLDEN_BASE_URL=http://127.0.0.1:8085 python -m pytest tests/golden -q
GOLDEN_BASE_URL=... GOLDEN_ONLY=analyze-depression,togg python -m pytest tests/golden -q
GOLDEN_BASE_URL=... GOLDEN_API_KEY=dv_sk_... python -m pytest tests/golden -q   # F1 sonrası
```

`GOLDEN_BASE_URL` yoksa golden testler atlanır; karşılaştırıcının kendi testleri (`test_compare.py`) her yerde çalışır:

```bash
python -m pytest tests/golden/test_compare.py -q
```

## Karşılaştırma kuralları (`compare.py`)

| Alan | Kural |
|---|---|
| Sayılar | `abs_tol=1e-3`, `rel_tol=1e-3` |
| Etiketler, enum'lar, diğer metinler | Birebir |
| `*.text`, `*.transcript`, `*.transcription` | Benzerlik oranı ≥ 0.9 (Whisper fp16 küçük farkları) |
| Süre/zaman alanları (`*processing_time*`, `*_ms`, `*elapsed*`, …) | Yok sayılır |
| Koşular arası değişen alanlar (`volatile_paths`) | Yok sayılır |
| Eksik/fazla alan, liste uzunluğu, tip | Fark sayılır |

Vaka bazında ayar: `cases.py` içinde `Case(rules={"abs_tol": 1e-2, "ignore": ["$.x"]})`.

## Kapsam

`cases.py` başındaki açıklamaya bakın. LLM kullanan uçlar (DeepSeek transkript doğrulama, wellness sohbeti) deterministik olmadığı için dahil değil.

## `/v1` geçişi

F1'de uçlar `/v1/...` altına taşınınca `Case.path` değerleri yeni yollara güncellenir. Yanıt şekli değişen uçlar için kayıt sırasında beklenen dönüşüm `compare` öncesinde uygulanacak; ham model sayıları aynı kalmalı.
