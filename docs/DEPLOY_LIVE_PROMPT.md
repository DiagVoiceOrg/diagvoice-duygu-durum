# Görev: Yeni sürümü canlıya al — tüm modeller sağlıklı çalışmalı

Deploy dizini: **`/opt/api`** · Dal: **`feat/prod-hardening`** · Domain: `https://aiapi.diagvoice.com`

Bu bir **canlıya alma** görevidir, test görevi değil. Yük testi, golden testi veya birim testi **çalıştırma**. Hedef: sistemin yeni sürümle açılması ve 10 modelin hepsinin sağlıklı çalışması.

**Kurallar:**
- Sırları (MONGO_URI, JWT_SECRET, CMS_ADMIN_PASSWORD, API_KEY_PEPPER, JOBS_WEBHOOK_SECRET, API anahtarları, OPENAI/DEEPSEEK) sohbete, loga, commit'e **yazma**. Yalnızca "tanımlı / uzunluk N" raporla.
- `main`'e dokunma. 8085 yalnızca `127.0.0.1`'de kalır. `TOGG_DIVERSIFY_ENABLED` kapatılmaz.
- Kod, Dockerfile, compose veya registry dosyalarını **değiştirme**. Bir şey çalışmazsa dur ve raporla.
- Docker volume'larını silme (`down -v` YASAK). HF model önbelleği orada.

## Kurulum betiği ne yapar

`scripts/deploy.sh` kendini korur. Adımları:

1. Kodu çeker ve image'ı build eder. Bu sırada eski sistem çalışmaya devam eder.
2. `.env` sırlarını ve GPU'yu kontrol eder. Sorun varsa eski sisteme **dokunmadan** durur.
3. Eski sistemi durdurur, yeni düzeni başlatır: `gateway` + `worker-gpu` + `worker-cpu` + `redis`.
4. Tüm modellerin yüklenmesini bekler (en fazla 25 dk), sonra `scripts/healthcheck.py` ile **10 modelin her birine gerçek istek atar**.
5. Herhangi bir model sağlıksızsa tanı loglarını `deploy-logs/<zaman>/` altına kaydeder ve **otomatik olarak** kanıtlanmış yedek düzene döner: `docker-compose.single.yml`, tek konteyner, her model ayrı süreç. Bugüne kadar prod'da çalışan yapı budur. Yedeği de aynı 10 model kontrolüyle doğrular.

Çıkış kodları:

| Kod | Anlamı |
|---|---|
| `0` | Yeni düzen canlıda, 10/10 model sağlıklı |
| `2` | Yeni düzen açılmadı, yedek düzen canlıda, 10/10 model sağlıklı |
| `1` | Hata — çıktıyı ve `deploy-logs/<zaman>/errors.txt`'yi raporla |

Kesinti, eski sistemin durdurulduğu andan modellerin yüklenmesine kadar sürer. HF önbelleği doluysa bu birkaç dakikadır.

## Adım 1 — Ön durum

```bash
cd /opt/api
git status --short                       # boş olmalı; değilse dur ve raporla
docker compose ls; docker ps --format '{{.Names}}\t{{.Status}}'
free -h; swapon --show; df -h /
python3 scripts/healthcheck.py 2>/dev/null || curl -s -o /dev/null -w "eski sistem /togg-analyze: %{http_code}\n" -F "file=@diagvoice-backend/test-data/ornek-ses-kayitlari/bu-harika-bir-gun.m4a" http://127.0.0.1:8085/togg-analyze
```

> `scripts/healthcheck.py` henüz çekilmediyse ikinci komut çalışır. Sorun değil.

## Adım 2 — Swap (yoksa 4 GB)

```bash
swapon --show | grep -q . || {
  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
}
swapon --show
```

## Adım 3 — .env sırları

Önce yedek al, sonra eksikleri ekle. Mevcut değerleri değiştirme.

```bash
cd /opt/api
cp .env .env.bak.$(date +%Y%m%d%H%M)
grep -q '^API_KEY_PEPPER=.\+' .env      || { sed -i '/^API_KEY_PEPPER=/d' .env; echo "API_KEY_PEPPER=$(openssl rand -hex 32)" >> .env; }
grep -q '^JOBS_WEBHOOK_SECRET=.\+' .env || { sed -i '/^JOBS_WEBHOOK_SECRET=/d' .env; echo "JOBS_WEBHOOK_SECRET=$(openssl rand -hex 32)" >> .env; }
grep -q '^API_KEY_LEGACY_MODE=' .env    || echo "API_KEY_LEGACY_MODE=optional" >> .env
for v in JWT_SECRET CMS_ADMIN_PASSWORD API_KEY_PEPPER JOBS_WEBHOOK_SECRET MONGO_URI; do
  val=$(grep -E "^$v=" .env | head -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//; s/^"//; s/"$//')
  echo "$v: uzunluk=${#val}"
done
```

- `API_KEY_PEPPER` **bir kez** üretilir. Değişirse tüm API anahtarları geçersiz olur.
- `API_KEY_LEGACY_MODE=optional` ile TOGG'un ve kendi uygulamalarımızın kullandığı eski uçlar anahtarsız çalışmaya devam eder.
- **`JWT_SECRET` < 32 karakter** veya **`CMS_ADMIN_PASSWORD` < 12 karakter / `admin123`** ise **dur ve kullanıcıya sor**. Bu durumda uygulama başlamaz.
  - JWT değişirse admin oturumları düşer.
  - `CMS_ADMIN_PASSWORD` yalnızca ilk admin oluşturulurken kullanılır; mevcut admin şifresi Mongo'da değişmez.

## Adım 4 — Kodu al ve canlıya al

```bash
cd /opt/api
git fetch origin && git checkout feat/prod-hardening && git pull --ff-only origin feat/prod-hardening
git log --oneline -3
chmod +x scripts/deploy.sh
scripts/deploy.sh; echo "deploy çıkış kodu: $?"
```

Betik 30 dakikaya kadar sürebilir: build + model yükleme + kontroller. Terminali kapatma. Bağlantı kopabilecekse betiği `tmux` veya `nohup scripts/deploy.sh > deploy.out 2>&1 &` ile çalıştır ve `tail -f deploy.out` ile izle.

- **Çıkış `0`** → Adım 5.
- **Çıkış `2`** → sistem yedek düzende sağlıklı çalışıyor. `deploy-logs/<zaman>/errors.txt` ve `healthcheck_multi.txt` içeriğini raporla (sır içermez), sonra Adım 5'e geç.
- **Çıkış `1`** → betiğin son 30 satırını ve `deploy-logs/<zaman>/errors.txt`'yi raporla. Durumu düzeltmeye çalışma.

## Adım 5 — Son doğrulama

```bash
cd /opt/api
python3 scripts/healthcheck.py                                        # sunucu içinden: 10/10
python3 scripts/healthcheck.py --base https://aiapi.diagvoice.com      # internet üzerinden: 10/10
curl -s http://127.0.0.1:8085/ready | python3 -m json.tool | head -40
docker ps --format '{{.Names}}\t{{.Status}}'
free -h; nvidia-smi --query-gpu=memory.used,memory.total --format=csv
```

## Adım 6 — TOGG API anahtarı

Bu adım yalnızca anahtar üretir; sistemi değiştirmez.

```bash
cd /opt/api
EMAIL=$(grep -E '^CMS_ADMIN_EMAIL=' .env | cut -d= -f2- | sed 's/[[:space:]]*#.*$//')
PASS=$(grep -E '^CMS_ADMIN_PASSWORD=' .env | cut -d= -f2- | sed 's/[[:space:]]*#.*$//')
TOKEN=$(curl -s -X POST http://127.0.0.1:8085/auth/login -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"email":sys.argv[1],"password":sys.argv[2]}))' "$EMAIL" "$PASS")" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))')
echo "token uzunluğu: ${#TOKEN}"     # 0 ise giriş başarısız: dur ve raporla
CID=$(curl -s -X POST http://127.0.0.1:8085/admin/clients -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"TOGG","notes":"Araç içi analiz"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
umask 077
curl -s -X POST "http://127.0.0.1:8085/admin/clients/$CID/keys" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"type":"sk","name":"TOGG prod","scopes":["analyze:togg"],"limits":{"rpm":600,"max_concurrent":20,"monthly_quota":0}}' \
  > /root/togg_api_key.json
python3 -c 'import json; d=json.load(open("/root/togg_api_key.json")); print("key_id:", d["key"]["key_id"], "| scopes:", d["key"]["scopes"], "| limits:", d["key"]["limits"])'
KEY=$(python3 -c 'import json; print(json.load(open("/root/togg_api_key.json"))["api_key"])')
curl -s -o /dev/null -w "v1 togg (anahtarlı): %{http_code}\n" -H "Authorization: Bearer $KEY" -H "User-Agent: diagvoice-deploy/1.0" \
  -F "file=@diagvoice-backend/test-data/ornek-ses-kayitlari/bu-harika-bir-gun.m4a" https://aiapi.diagvoice.com/v1/analyze/togg
unset PASS TOKEN KEY
```

Tam anahtar yalnızca `/root/togg_api_key.json` dosyasındadır (izin 600). **Ekrana basma, rapora yazma.** Kullanıcı dosyayı kendisi alacak.

## Rapor

```
Adım 1 — Ön durum: çalışan konteynerler, RAM/swap/disk, eski sistem kontrolü
Adım 2 — Swap: vardı / eklendi
Adım 3 — Sırlar: eklenen değişkenler (değer YOK), uzunluklar, .env yedeği adı
Adım 4 — deploy.sh çıkış kodu, son 15 satır, (2 veya 1 ise) errors.txt
Adım 5 — healthcheck içeriden ve dışarıdan (10/10?), /ready özeti, RAM/VRAM
Adım 6 — TOGG: key_id, scopes, limits, v1 togg HTTP kodu (anahtar YOK)
```
