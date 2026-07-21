from __future__ import annotations

import gc
import math
import re
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import joblib
import librosa
import numpy as np
import opensmile
import soundfile as sf
import torch
from sentence_transformers import SentenceTransformer
from transformers import (
    AutoFeatureExtractor,
    AutoModelForSpeechSeq2Seq,
    AutoProcessor,
    WavLMModel,
    pipeline as hf_pipeline,
)


LABELS = ("anger", "fear", "happiness", "sadness")

# Eğitim sırasında kullanılan talimatla aynı tutulmalıdır.
TEXT_INSTRUCTION = (
    "Bu Türkçe konuşma transkriptini dört sınıflı duygu tanıma için temsil et: "
    "anger, fear, happiness, sadness."
)


@dataclass(frozen=True)
class RuntimeConfig:
    model_path: str
    sample_rate: int = 16_000
    wavlm_chunk_seconds: float = 10.0
    wavlm_stride_seconds: float = 8.0
    wavlm_batch_size: int = 4
    whisper_chunk_seconds: int = 30
    whisper_batch_size: int = 4
    device: Optional[str] = None
    min_audio_seconds: float = 0.25
    max_audio_seconds: float = 300.0


def _resolve_device(value: Optional[str]) -> torch.device:
    if value:
        device = torch.device(value)
    else:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("EMOSYON_DEVICE=cuda seçildi ancak CUDA kullanılabilir değil.")

    return device


def _aligned_predict_proba(
    model: Any,
    features: np.ndarray,
    n_classes: int,
) -> np.ndarray:
    probabilities = np.asarray(model.predict_proba(features), dtype=np.float64)
    classes = np.asarray(model.classes_, dtype=int)

    aligned = np.zeros((len(features), n_classes), dtype=np.float64)
    aligned[:, classes] = probabilities
    aligned = np.clip(aligned, 1e-8, 1.0)
    aligned /= aligned.sum(axis=1, keepdims=True)
    return aligned


def load_audio_mono(
    path: str | Path,
    target_sample_rate: int = 16_000,
) -> Tuple[np.ndarray, int]:
    audio_path = Path(path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Ses dosyası bulunamadı: {audio_path}")

    try:
        waveform, sample_rate = sf.read(
            audio_path,
            dtype="float32",
            always_2d=False,
        )
        waveform = np.asarray(waveform, dtype=np.float32)

        # soundfile çok kanallı sesi [frame, channel] döndürür.
        if waveform.ndim == 2:
            waveform = waveform.mean(axis=1)
    except Exception:
        # MP3/M4A/WEBM gibi biçimlerde ffmpeg/audioread fallback.
        waveform, sample_rate = librosa.load(
            audio_path,
            sr=None,
            mono=True,
        )
        waveform = np.asarray(waveform, dtype=np.float32)

    if waveform.ndim != 1:
        waveform = np.ravel(waveform)

    if waveform.size == 0:
        raise ValueError("Yüklenen ses dosyası boş.")

    waveform = np.nan_to_num(
        waveform,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    if int(sample_rate) != int(target_sample_rate):
        waveform = librosa.resample(
            waveform,
            orig_sr=int(sample_rate),
            target_sr=int(target_sample_rate),
        ).astype(np.float32)

    peak = float(np.max(np.abs(waveform)))
    if peak > 1.0:
        waveform = waveform / peak

    return waveform.astype(np.float32), int(target_sample_rate)


def split_audio(
    waveform: np.ndarray,
    sample_rate: int,
    chunk_seconds: float,
    stride_seconds: float,
) -> List[np.ndarray]:
    chunk_size = max(1, int(chunk_seconds * sample_rate))
    stride_size = max(1, int(stride_seconds * sample_rate))

    if len(waveform) <= chunk_size:
        return [waveform]

    starts = list(range(0, len(waveform) - chunk_size + 1, stride_size))
    final_start = len(waveform) - chunk_size

    if starts[-1] != final_start:
        starts.append(final_start)

    return [waveform[start : start + chunk_size] for start in starts]


def transcript_stats(text: str) -> np.ndarray:
    text = str(text or "")
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    char_count = len(text)

    return np.asarray(
        [
            math.log1p(len(words)),
            math.log1p(char_count),
            text.count("!"),
            text.count("?"),
            text.count("..."),
            sum(char.isupper() for char in text) / max(char_count, 1),
        ],
        dtype=np.float32,
    )


def _custom_features(
    waveform: np.ndarray,
    sample_rate: int,
) -> Dict[str, float]:
    duration_seconds = len(waveform) / float(sample_rate)
    frame_length = min(2048, max(256, len(waveform)))
    hop_length = 512

    rms = librosa.feature.rms(
        y=waveform,
        frame_length=frame_length,
        hop_length=hop_length,
    ).ravel()
    rms = np.asarray(rms, dtype=np.float64)

    rms_db = librosa.amplitude_to_db(
        np.maximum(rms, 1e-12),
        ref=np.max,
    )
    silence_ratio = float(np.mean(rms_db < -40.0)) if len(rms_db) else 0.0

    centroid = librosa.feature.spectral_centroid(
        y=waveform,
        sr=sample_rate,
        n_fft=2048,
        hop_length=hop_length,
    ).ravel()

    rolloff = librosa.feature.spectral_rolloff(
        y=waveform,
        sr=sample_rate,
        n_fft=2048,
        hop_length=hop_length,
        roll_percent=0.85,
    ).ravel()

    return {
        "custom__duration_sec": float(duration_seconds),
        "custom__rms_mean": float(np.mean(rms)) if len(rms) else 0.0,
        "custom__rms_std": float(np.std(rms)) if len(rms) else 0.0,
        "custom__silence_ratio_db40": silence_ratio,
        "custom__active_ratio_db40": 1.0 - silence_ratio,
        "custom__spectral_centroid_mean": (
            float(np.mean(centroid)) if len(centroid) else 0.0
        ),
        "custom__spectral_centroid_std": (
            float(np.std(centroid)) if len(centroid) else 0.0
        ),
        "custom__spectral_rolloff85_mean": (
            float(np.mean(rolloff)) if len(rolloff) else 0.0
        ),
        "custom__spectral_rolloff85_std": (
            float(np.std(rolloff)) if len(rolloff) else 0.0
        ),
    }


def _mfcc_features(
    waveform: np.ndarray,
    sample_rate: int,
) -> Tuple[np.ndarray, np.ndarray]:
    mfcc = librosa.feature.mfcc(
        y=waveform,
        sr=sample_rate,
        n_mfcc=20,
        n_fft=2048,
        hop_length=512,
    )
    return (
        mfcc.mean(axis=1).astype(np.float64),
        mfcc.std(axis=1).astype(np.float64),
    )


def _parse_mfcc_column(column: str) -> Tuple[int, str]:
    remainder = column[len("mfcc__") :].lower()
    numbers = re.findall(r"\d+", remainder)

    if not numbers:
        raise KeyError(f"MFCC numarası çözümlenemedi: {column}")

    index = int(numbers[0])
    if not 1 <= index <= 20:
        raise KeyError(f"MFCC indeksi 1-20 dışında: {column}")

    if any(token in remainder for token in ("std", "stdev", "stddev")):
        statistic = "std"
    elif any(token in remainder for token in ("mean", "amean", "avg")):
        statistic = "mean"
    else:
        raise KeyError(f"MFCC istatistiği çözümlenemedi: {column}")

    return index - 1, statistic


def extract_acoustic_vector(
    waveform: np.ndarray,
    sample_rate: int,
    acoustic_columns: Sequence[str],
    smile: Optional[opensmile.Smile] = None,
) -> np.ndarray:
    if smile is None:
        smile = opensmile.Smile(
            feature_set=opensmile.FeatureSet.eGeMAPSv02,
            feature_level=opensmile.FeatureLevel.Functionals,
        )

    egemaps_frame = smile.process_signal(waveform, sample_rate)
    if egemaps_frame.empty:
        raise RuntimeError("openSMILE eGeMAPS özelliği çıkarılamadı.")

    egemaps = {
        f"egemaps__{key}": float(value)
        for key, value in egemaps_frame.iloc[0].to_dict().items()
    }

    mfcc_mean, mfcc_std = _mfcc_features(waveform, sample_rate)
    custom = _custom_features(waveform, sample_rate)

    values: List[float] = []
    missing: List[str] = []

    for column in acoustic_columns:
        if column in egemaps:
            value = egemaps[column]
        elif column in custom:
            value = custom[column]
        elif column.startswith("mfcc__"):
            try:
                index, statistic = _parse_mfcc_column(column)
                value = mfcc_mean[index] if statistic == "mean" else mfcc_std[index]
            except Exception:
                missing.append(column)
                value = np.nan
        else:
            missing.append(column)
            value = np.nan

        values.append(float(value))

    if missing:
        raise KeyError(
            "Artifact içindeki bazı akustik kolonlar çıkarılamadı. "
            f"İlk eksikler: {missing[:20]}"
        )

    vector = np.asarray(values, dtype=np.float32)

    if not np.isfinite(vector).all():
        invalid_indexes = np.where(~np.isfinite(vector))[0][:20]
        invalid_columns = [acoustic_columns[index] for index in invalid_indexes]
        raise ValueError(
            f"Akustik vektörde geçersiz değerler var: {invalid_columns}"
        )

    return vector


class MultimodalEmotionPredictor:
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.device = _resolve_device(config.device)
        self.model_path = Path(config.model_path).expanduser().resolve()

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Nihai model bulunamadı: {self.model_path}"
            )

        self.artifact: Dict[str, Any] = joblib.load(self.model_path)
        self.labels = tuple(self.artifact.get("labels", LABELS))
        self.selected = self.artifact["selected"]
        self.acoustic_columns = list(self.artifact["acoustic_columns"])

        if len(self.acoustic_columns) != 137:
            raise ValueError(
                "Model artifact'ında 137 akustik özellik bekleniyordu; "
                f"{len(self.acoustic_columns)} bulundu."
            )

        self.smile = opensmile.Smile(
            feature_set=opensmile.FeatureSet.eGeMAPSv02,
            feature_level=opensmile.FeatureLevel.Functionals,
        )

        wavlm_name = self.artifact.get(
            "wavlm_backbone",
            "microsoft/wavlm-base-plus",
        )
        self.wavlm_extractor = AutoFeatureExtractor.from_pretrained(wavlm_name)
        self.wavlm = WavLMModel.from_pretrained(wavlm_name).to(self.device)
        self.wavlm.config.apply_spec_augment = False
        self.wavlm.eval()

        for parameter in self.wavlm.parameters():
            parameter.requires_grad = False

        text_encoder_name = self.artifact.get(
            "text_encoder",
            "intfloat/multilingual-e5-large-instruct",
        )
        self.text_encoder = SentenceTransformer(
            text_encoder_name,
            device=str(self.device),
        )

        self.asr = None
        self._whisper_model = None
        self._whisper_processor = None
        self._load_whisper()

    def _load_whisper(self) -> None:
        if self.asr is not None:
            return

        whisper_name = self.artifact.get(
            "whisper_model",
            "openai/whisper-large-v3-turbo",
        )
        dtype = torch.float16 if self.device.type == "cuda" else torch.float32

        processor = AutoProcessor.from_pretrained(whisper_name)
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            whisper_name,
            dtype=dtype,
            low_cpu_mem_usage=True,
            use_safetensors=True,
        ).to(self.device)
        model.eval()

        self._whisper_processor = processor
        self._whisper_model = model
        self.asr = hf_pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            dtype=dtype,
            device=0 if self.device.type == "cuda" else -1,
            chunk_length_s=self.config.whisper_chunk_seconds,
            batch_size=self.config.whisper_batch_size,
        )

    @torch.inference_mode()
    def _extract_wavlm(
        self,
        waveform: np.ndarray,
        required_layers: Iterable[int],
    ) -> Dict[int, np.ndarray]:
        layers = sorted(set(int(layer) for layer in required_layers))
        chunks = split_audio(
            waveform,
            self.config.sample_rate,
            self.config.wavlm_chunk_seconds,
            self.config.wavlm_stride_seconds,
        )

        collected: Dict[int, List[torch.Tensor]] = {
            layer: [] for layer in layers
        }

        for start in range(0, len(chunks), self.config.wavlm_batch_size):
            batch = chunks[start : start + self.config.wavlm_batch_size]

            inputs = self.wavlm_extractor(
                batch,
                sampling_rate=self.config.sample_rate,
                padding=True,
                return_attention_mask=True,
                return_tensors="pt",
            )

            input_values = inputs["input_values"].to(self.device)
            input_mask = inputs["attention_mask"].to(self.device)

            autocast_context = (
                torch.autocast(device_type="cuda", dtype=torch.float16)
                if self.device.type == "cuda"
                else nullcontext()
            )

            with autocast_context:
                output = self.wavlm(
                    input_values,
                    attention_mask=input_mask,
                    output_hidden_states=True,
                    return_dict=True,
                )

            hidden_states = output.hidden_states[1:]
            feature_mask = self.wavlm._get_feature_vector_attention_mask(
                hidden_states[-1].shape[1],
                input_mask,
            )

            mask = feature_mask.unsqueeze(-1).float()
            denominator = mask.sum(dim=1).clamp_min(1.0)
            running_sum = None
            wanted = set(layers)

            for depth, state in enumerate(
                reversed(hidden_states),
                start=1,
            ):
                state = state.float()
                running_sum = (
                    state
                    if running_sum is None
                    else running_sum + state
                )

                if depth in wanted:
                    hidden = running_sum / float(depth)
                    mean = (hidden * mask).sum(dim=1) / denominator
                    variance = (
                        ((hidden - mean.unsqueeze(1)) ** 2) * mask
                    ).sum(dim=1) / denominator
                    std = torch.sqrt(torch.clamp(variance, min=1e-5))

                    collected[depth].append(
                        torch.cat([mean, std], dim=-1).cpu()
                    )

                if depth >= max(layers):
                    break

        return {
            layer: (
                torch.cat(collected[layer], dim=0)
                .mean(dim=0)
                .numpy()
                .astype(np.float32)
            )
            for layer in layers
        }

    def transcribe(
        self,
        waveform: np.ndarray,
        language: Optional[str] = "turkish",
    ) -> str:
        if self.asr is None:
            self._load_whisper()

        generate_kwargs: Dict[str, Any] = {"task": "transcribe"}
        if language:
            generate_kwargs["language"] = language

        result = self.asr(
            {
                "array": waveform,
                "sampling_rate": self.config.sample_rate,
            },
            generate_kwargs=generate_kwargs,
            return_timestamps=False,
        )

        return str(result.get("text", "")).strip()

    def encode_text(self, transcript: str) -> np.ndarray:
        text = transcript.strip() or "[ses anlaşılamadı]"
        formatted = f"Instruct: {TEXT_INSTRUCTION}\nQuery: {text}"

        vector = self.text_encoder.encode(
            [formatted],
            batch_size=1,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype(np.float32)

        return vector[0]

    def predict(
        self,
        audio_path: str | Path,
        language: Optional[str] = "turkish",
        transcript: Optional[str] = None,
    ) -> Dict[str, Any]:
        waveform, sample_rate = load_audio_mono(
            audio_path,
            self.config.sample_rate,
        )

        duration_seconds = len(waveform) / float(sample_rate)
        if duration_seconds < self.config.min_audio_seconds:
            raise ValueError(
                "Ses çok kısa. Minimum süre: "
                f"{self.config.min_audio_seconds:.2f} saniye."
            )
        if duration_seconds > self.config.max_audio_seconds:
            raise ValueError(
                "Ses çok uzun. Maksimum süre: "
                f"{self.config.max_audio_seconds:.0f} saniye."
            )

        resolved_transcript = (
            transcript.strip()
            if transcript and transcript.strip()
            else self.transcribe(waveform, language=language)
        )

        text_vector = self.encode_text(resolved_transcript)
        text_stats = transcript_stats(resolved_transcript)
        acoustic_vector = extract_acoustic_vector(
            waveform,
            sample_rate,
            self.acoustic_columns,
            smile=self.smile,
        )

        required_layers = {
            int(self.selected["wavlm"]["layer"]),
            int(self.selected["multimodal_logistic"]["layer"]),
            int(self.selected["multimodal_svm"]["layer"]),
        }
        wavlm_vectors = self._extract_wavlm(
            waveform,
            required_layers,
        )

        wavlm_features = wavlm_vectors[
            int(self.selected["wavlm"]["layer"])
        ][None, :]

        text_features = text_vector[None, :]
        acoustic_features = acoustic_vector[None, :]

        multimodal_logistic_features = np.concatenate(
            [
                wavlm_vectors[
                    int(self.selected["multimodal_logistic"]["layer"])
                ],
                text_vector,
                text_stats,
                acoustic_vector,
            ]
        )[None, :].astype(np.float32)

        multimodal_svm_features = np.concatenate(
            [
                wavlm_vectors[
                    int(self.selected["multimodal_svm"]["layer"])
                ],
                text_vector,
                text_stats,
                acoustic_vector,
            ]
        )[None, :].astype(np.float32)

        branch_probabilities = {
            "wavlm": _aligned_predict_proba(
                self.artifact["wavlm_model"],
                wavlm_features,
                len(self.labels),
            )[0],
            "text": _aligned_predict_proba(
                self.artifact["text_model"],
                text_features,
                len(self.labels),
            )[0],
            "acoustic": _aligned_predict_proba(
                self.artifact["acoustic_model"],
                acoustic_features,
                len(self.labels),
            )[0],
            "multimodal_logistic": _aligned_predict_proba(
                self.artifact["multimodal_logistic_model"],
                multimodal_logistic_features,
                len(self.labels),
            )[0],
            "multimodal_svm": _aligned_predict_proba(
                self.artifact["multimodal_svm_model"],
                multimodal_svm_features,
                len(self.labels),
            )[0],
        }

        meta_features = np.concatenate(
            [
                branch_probabilities["wavlm"],
                branch_probabilities["text"],
                branch_probabilities["acoustic"],
                branch_probabilities["multimodal_logistic"],
                branch_probabilities["multimodal_svm"],
            ]
        )[None, :]

        final_probabilities = _aligned_predict_proba(
            self.artifact["meta_model"],
            meta_features,
            len(self.labels),
        )[0]

        prediction_index = int(np.argmax(final_probabilities))

        return {
            "prediction": self.labels[prediction_index],
            "confidence": float(final_probabilities[prediction_index]),
            "probabilities": {
                label: float(final_probabilities[index])
                for index, label in enumerate(self.labels)
            },
            "transcript": resolved_transcript,
            "duration_seconds": round(duration_seconds, 3),
            "branch_probabilities": {
                branch: {
                    label: float(values[index])
                    for index, label in enumerate(self.labels)
                }
                for branch, values in branch_probabilities.items()
            },
        }

    def model_info(self) -> Dict[str, Any]:
        return {
            "model_path": str(self.model_path),
            "model_type": "acoustic-linguistic multimodal stacking",
            "labels": list(self.labels),
            "device": str(self.device),
            "wavlm_backbone": self.artifact.get(
                "wavlm_backbone",
                "microsoft/wavlm-base-plus",
            ),
            "whisper_model": self.artifact.get(
                "whisper_model",
                "openai/whisper-large-v3-turbo",
            ),
            "text_encoder": self.artifact.get(
                "text_encoder",
                "intfloat/multilingual-e5-large-instruct",
            ),
            "acoustic_feature_count": len(self.acoustic_columns),
        }

    def close(self) -> None:
        for attribute in (
            "asr",
            "_whisper_model",
            "_whisper_processor",
            "wavlm",
            "wavlm_extractor",
            "text_encoder",
        ):
            if hasattr(self, attribute):
                setattr(self, attribute, None)

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
