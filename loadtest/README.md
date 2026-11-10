# Yük testi — mevcut sistem (rate limit / kuyruk yok)

Amaç: sistemin **bugünkü haliyle** (tek g4dn.xlarge, T4 GPU, tek fusion süreci, rate limit ve Redis kuyruğu yok) artan yük altında nasıl davrandığını ve nerede kırıldığını görmek. Bu test bir sınav değil, ölçümdür. Sonuçlar F1 (rate limit) ve F4 (kuyruk) tasarımına girdi olacak.

## Dosyalar

| Dosya | Ne yapar | Nerede çalışır |
|---|---|---|
| `k6/diagvoice.js` | Tek kademe yük üretir | yük makinesi |
| `run.sh` | Kademeleri sırayla çalıştırır; aralarda sunucunun toparlanmasını bekler | yük makinesi |
| `monitor.sh` | CPU, RAM, GPU, bağlantı sayıları ve çökme olaylarını kaydeder | GPU sunucusu |

`run.sh` parametresiz çalışırsa **istek atmaz**, sadece planı gösterir. İstek atmak için `--go` gerekir.

## Plan

| # | Kademe | Uç | Yük | Ölçülen |
|---|---|---|---|---|
| 1 | `fused_1` | `/analyze-fused` | 1 istek | Referans süre (beklenen ~5 sn) |
| 2 | `fused_10` | 〃 | 10 kullanıcı, 3 dk sürekli | Gerçekçi eşzamanlılık |
| 3 | `fused_25` | 〃 | 25 kullanıcı, 3 dk | |
| 4 | `fused_50` | 〃 | 50 kullanıcı, 3 dk | |
| 5 | `fused_100` | 〃 | 100 kullanıcı, 3 dk | |
| 6 | `fused_100_burst` | 〃 | 100 istek aynı anda | Ani yük |
| 7 | `fused_1000_burst` | 〃 | 1000 istek aynı anda | Kuyruk / timeout davranışı |
| 8–11 | `text_1` … `text_1000_burst` | `/analyze-text-sentiment` | 1 → 1000 | Kısa GPU işi |
| 12–16 | `root_1000_burst` … `root_50000_burst` | `GET /` | 1000 → 50.000 aynı anda | Karşılama katmanı (nginx + uvicorn + audit) |

**Neden 10k–50k ağır uçta değil, `GET /`'de?** `/analyze-fused` tek istekte GPU'da yaklaşık 5 sn çalışıyor. Sunucu saniyede kabaca 0,2–1 istek bitirebilir. 10.000 eşzamanlı fused isteğinin son sırası saatler sonra gelir. nginx 900 sn'de keser, yani sonuç "hepsi 504" olur ve yeni bilgi vermez. Diske ve Mongo'ya da gereksiz yük biner. 1000 burst bu kırılmayı zaten gösterir. 50.000'e kadar çıkmanın anlamlı olduğu yer, modele hiç dokunmayan karşılama katmanı.

Her kademede hata oranı 30 sn sonra %50'yi geçerse o kademe erken durur (`ABORT_ERR`). Sonra sunucunun toparlanması beklenir: `GET /` ve text uç 200 dönmeli. 10 dk içinde toparlanmazsa test tamamen durur.

Tahmini toplam süre: **1,5–2 saat**. En uzun parçalar fused burst'ler ve aralardaki bekleme.

## Beklentilerim (sonuçlarla karşılaştırmak için)

- **fused_1:** ~5 sn.
- **fused_10–100:** Throughput sabit kalır (GPU sıralı çalışır), süre eşzamanlılıkla doğrusal uzar. 100'de ortalama birkaç dakika. GPU belleği (T4, 16 GB) aynı anda çok sayıda Whisper/WavLM çalışırsa **CUDA OOM** riski var. İç servislerden biri çökerse supervisord yeniden başlatır ve o süre içinde 5xx gelir.
- **fused_1000_burst:** İlk birkaç yüz istek biter, kalanlar 900 sn'de **504** alır. fusion'ın iç httpx havuzu 64 bağlantıyla sınırlı, istekler orada da birikir.
- **root_10000+:** Ubuntu nginx varsayılanı `worker_connections 768` × 4 worker ≈ 3000 bağlantı. Bunun üstünde nginx bağlantı reddeder (`worker_connections are not enough`), istemcide ağ hatası görünür. Ayrıca her `GET /` Mongo'ya audit kaydı yazıyor; harici Mongo'nun yazma hızı da darboğaz olabilir.

## Yük makinesi

**GPU sunucusunun kendisinde çalıştırma.** k6, ölçülen sistemle aynı CPU'yu paylaşır ve sonuçlar bozulur.

- **fused / text kademeleri:** Herhangi bir makine olur, Coolify CPU sunucusu da uygun. 1000 burst ~150 MB upload demek, ev bağlantısı yavaşlatabilir.
- **root 25k–50k:** Tek bir Linux makinesi, **≥ 16 GB RAM** (k6 her VU için ~0,3–1 MB kullanır). Mümkünse aynı AWS bölgesinde olsun. Windows'ta yerel port sınırı (~16k) yüzünden 25k+ yapılamaz. Hazırlık:

  ```bash
  ulimit -n 250000
  sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"
  sudo sysctl -w net.ipv4.tcp_tw_reuse=1
  ```

- k6 kurulumu: <https://grafana.com/docs/k6/latest/set-up/install-k6/>
- Repo yük makinesine klonlanmış olmalı: script, ses dosyasını `diagvoice-backend/test-data/` altından okur.

## Başlamadan önce — kontrol listesi

1. **TOGG'a ve kendi uygulamalarımıza haber ver.** Test sırasında `aiapi.diagvoice.com` yavaşlayacak ve hata verecek. Hiçbir katmanda koruma yok.
2. **Sunucu temiz mi?**
   - `docker compose ps`: `backend` Up.
   - `df -h /`: boş alan > 50 GB.
   - `nvidia-smi`: GPU boşta.
3. **Ses kaydı biriktirme.** Her ses isteği `data/audio_recordings/` altına da kaydediliyor. Toplam en fazla birkaç bin dosya, < 1 GB, sorun değil. Test bitince silinebilir (aşağıda).
4. **Mongo kotası.** Plan toplam ~95.000 audit kaydı üretir (çoğu `GET /`, ~1 KB). Mongo ücretsiz/paylaşımlı katmandaysa (512 MB) yer yetiyor mu kontrol et.
5. **Sunucuda izleme başlat** (ayrı bir SSH oturumunda):

   ```bash
   cd /opt/api && git pull --ff-only && sudo loadtest/monitor.sh
   ```

6. **Yük makinesinde:**

   ```bash
   git pull --ff-only
   loadtest/run.sh                 # plan doğru mu, kontrol et
   loadtest/run.sh --go            # başlat
   ```

   Parça parça da çalışabilirsin:
   - `--only "fused_1 fused_10"`: sadece bu kademeler.
   - `--from root_1000_burst`: bu kademeden itibaren.

## Bittikten sonra

- **Topla:**
  - Yük makinesinde `loadtest/results/<zaman>/`: `run.log` ve her kademenin JSON'u.
  - Sunucuda `loadtest/monitor/<zaman>/`.
  - Sunucuda `sudo grep -c "worker_connections are not enough" /var/log/nginx/error.log`.
- **Temizlik** (geri alınamaz, onaydan sonra):
  - Test süresince oluşan audit kayıtları: `fusion_api_logs` içinde `client_ip` = yük makinesi IP'si ve `created_at` test aralığında olanlar.
  - Bu kayıtlara bağlı ses dosyaları: `data/audio_recordings/`.
