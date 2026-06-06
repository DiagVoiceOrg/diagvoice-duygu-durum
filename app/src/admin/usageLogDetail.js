/** Audit log details → görüntülenebilir model bölümleri */

const FUSED_MODELS = [
  { key: 'text', previewKey: 'text_preview', lenKey: 'text_len', errorKey: 'text_error', label: 'STT / Metin' },
  { key: 'text_sentiment', errorKey: 'text_sentiment_error', label: 'Metin duygu analizi' },
  { key: 'audio', errorKey: 'audio_error', label: 'Ses emosyonu' },
  { key: 'disease', errorKey: 'disease_error', label: 'Hastalık (WURSS)' },
  { key: 'mental_fitness', errorKey: 'mental_fitness_error', label: 'Mental fitness' },
  { key: 'age_gender', errorKey: 'age_gender_error', label: 'Yaş / cinsiyet' },
  { key: 'depression', errorKey: 'depression_error', label: 'Depresyon' },
  { key: 'benchmark_v2', errorKey: 'benchmark_v2_error', label: 'Benchmark v2' },
];

const PROXY_LABELS = {
  'analyze-depression': 'Depresyon modeli',
  'analyze-voice-to-text': 'Konuşma → metin (STT)',
  'analyze-text-sentiment': 'Metin duygu analizi',
  'analyze-voice-sentiment': 'Ses emosyonu',
  'analyze-disease': 'Hastalık (WURSS)',
  'analyze-mental-fitness': 'Mental fitness',
  'validate-transcript-meaning': 'Transcript anlamlılık',
  'analyze-age-gender': 'Yaş / cinsiyet',
  'analyze-text-audio-fusion': 'Metin + ses birleşimi',
  'analyze-benchmark-v2': 'Benchmark v2',
  'analyze-turkish-psych-signals': 'Türkçe psik sinyaller',
};

function isObject(v) {
  return v != null && typeof v === 'object' && !Array.isArray(v);
}

function pushSection(sections, section) {
  if (section.error || section.data != null) {
    sections.push(section);
  }
}

function sectionsFromFusedResponse(route, response) {
  if (!isObject(response)) return [];
  const sections = [];
  for (const m of FUSED_MODELS) {
    const data = response[m.key];
    const preview = response[m.previewKey];
    const len = response[m.lenKey];
    const err = response[m.errorKey];
    let payload = data;
    if (!payload && preview) {
      payload = len != null ? { preview, length: len } : { preview };
    }
    pushSection(sections, {
      id: `${route}-${m.key}`,
      title: m.label,
      kind: err ? 'error' : 'model',
      data: payload,
      error: err,
    });
  }
  if (response.fused) {
    pushSection(sections, {
      id: `${route}-fused`,
      title: 'Valence birleşimi (fused)',
      kind: 'model',
      data: response.fused,
    });
  }
  if (response.confidence) {
    pushSection(sections, {
      id: `${route}-confidence`,
      title: 'Güven skorları',
      kind: 'meta',
      data: response.confidence,
    });
  }
  if (response.valence_text != null || response.valence_audio != null) {
    pushSection(sections, {
      id: `${route}-valence`,
      title: 'Valence (ham)',
      kind: 'meta',
      data: { valence_text: response.valence_text, valence_audio: response.valence_audio },
    });
  }
  return sections;
}

/** @returns {{ meta: object, errors: object[], models: object[] }} */
export function parseUsageLogDetail(log) {
  const d = log?.details;
  const meta = {
    id: log?.id,
    path: log?.path,
    method: log?.method,
    http_status: log?.http_status,
    outcome: log?.outcome,
    duration_ms: log?.duration_ms,
    created_at: log?.created_at,
    client_ip: log?.client_ip,
    route: d?.route,
    proxy: d?.proxy,
    filename: d?.filename || d?.upload_name,
    file_bytes: d?.bytes || d?.file_bytes,
    speech_language: d?.speech_language,
    upstream_http: d?.upstream_http,
  };

  const errors = [];
  const models = [];

  if (!isObject(d)) {
    return { meta, errors, models };
  }

  if (d.error_summary || d.error_message) {
    errors.push({
      id: 'primary-error',
      title: 'Hata',
      summary: d.error_summary || d.error_message,
      detail: d.detail ?? d.error_message,
      type: d.error_type,
    });
  }
  if (d.validation_errors?.length) {
    errors.push({
      id: 'validation',
      title: 'Doğrulama hatası',
      summary: d.error_summary,
      detail: d.validation_errors,
      type: 'request_validation',
    });
  }
  if (isObject(d.upstream_errors)) {
    for (const [step, msg] of Object.entries(d.upstream_errors)) {
      errors.push({ id: `upstream-${step}`, title: step, summary: String(msg), detail: msg, type: 'upstream' });
    }
  }
  if (d.upstream_error) {
    errors.push({
      id: 'upstream-error',
      title: 'Upstream hatası',
      summary: String(d.upstream_error),
      detail: d.upstream_error,
    });
  }

  if (d.route && isObject(d.response)) {
    models.push(...sectionsFromFusedResponse(d.route, d.response));
  } else if (d.response != null) {
    const title = PROXY_LABELS[d.proxy] || d.proxy || log?.path || 'Model yanıtı';
    pushSection(models, {
      id: 'proxy-response',
      title,
      kind: d.upstream_error ? 'error' : 'model',
      data: d.response,
      error: d.upstream_error,
    });
  } else if (d.body != null) {
    const title = PROXY_LABELS[d.proxy] || d.proxy || log?.path || 'Model yanıtı';
    pushSection(models, {
      id: 'proxy-body',
      title,
      kind: 'model',
      data: d.body,
    });
  } else if (d.top_prediction != null || d.predictions_count != null) {
    pushSection(models, {
      id: 'psych-signals',
      title: PROXY_LABELS[d.proxy] || 'Psik sinyaller',
      kind: 'model',
      data: { top_prediction: d.top_prediction, predictions_count: d.predictions_count },
    });
  }

  if (d.route === 'wellness-companion-chat') {
    if (d.response_preview) {
      pushSection(models, {
        id: 'wellness-response',
        title: 'Wellness asistan yanıtı',
        kind: 'model',
        data: { message: d.response_preview, length: d.response_len },
      });
    }
    if (d.transcript_preview) {
      pushSection(models, {
        id: 'wellness-transcript',
        title: 'Transcript',
        kind: 'model',
        data: { transcript: d.transcript_preview, length: d.transcript_len },
      });
    }
  }

  return { meta, errors, models };
}

/** Kart üstünde gösterilecek öne çıkan alanlar */
export function highlightFields(data) {
  if (!isObject(data)) return [];
  const preferred = [
    'label',
    'prediction',
    'sentiment',
    'score',
    'top_prediction',
    'class',
    'result',
    'valence',
    'text',
    'preview',
    'transcript',
    'message',
    'probs',
    'intensity',
  ];
  const out = [];
  for (const k of preferred) {
    if (data[k] != null && data[k] !== '') {
      out.push({ key: k, value: data[k] });
    }
  }
  if (out.length >= 4) return out.slice(0, 6);
  for (const [k, v] of Object.entries(data)) {
    if (out.some((x) => x.key === k)) continue;
    if (v == null || typeof v === 'object') continue;
    out.push({ key: k, value: v });
    if (out.length >= 6) break;
  }
  return out;
}

export function formatLogTime(iso) {
  if (!iso) return '—';
  return String(iso).replace('T', ' ').slice(0, 19);
}

export function outcomeLabel(outcome, httpStatus) {
  if (outcome === 'success') return { text: 'Başarılı', className: 'usage-badge--success' };
  if (outcome === 'client_error') return { text: `İstemci ${httpStatus ?? '4xx'}`, className: 'usage-badge--warn' };
  if (outcome === 'server_error') return { text: `Sunucu ${httpStatus ?? '5xx'}`, className: 'usage-badge--error' };
  return { text: String(httpStatus ?? '—'), className: 'usage-badge--neutral' };
}
