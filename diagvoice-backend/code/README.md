# `code/features` — benchmark özellikleri

Varsayılan: bu repoda **librosa + basit metin** skalerleri tanımlıdır. Eğitimde kullandığınız
sütun adları farklıysa, benchmark repo’daki `features/` modüllerini buraya kopyalayın veya
`DIAGVOICE_CODE_ROOT` ile o dizini öne alın (`inference_api/engine.py` içinde `setup_sys_path`).

İş sağlığı (benchmark) çıktı joblib’ini **`diagvoice-backend/models/is-sagligi.joblib`** olarak koyun veya
`DIAGVOICE_MODEL` ile tam yolu verin. Alternatif olarak `inference_api/models/model.joblib` da kabul edilir.
