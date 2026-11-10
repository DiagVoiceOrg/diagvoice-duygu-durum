"""
benchmark_v2 (inference-api) native çökme teşhisi.

Her aşama ayrı bir alt süreçte çalışır; SIGSEGV olan aşama "CRASH" olarak raporlanır
ve faulthandler yığını gösterilir. Konteyner içinde:

  docker compose exec backend python -m inference_api.diag_crash /app/test-data/.../ornek.m4a
"""
from __future__ import annotations

import json
import subprocess
import sys

STAGES = ["versions", "librosa_load", "audio_features", "praat", "opensmile", "full_row", "predict", "predict_in_thread", "predict_repeat_threads"]

_CODE = r'''
import faulthandler, sys, json, threading
faulthandler.enable(all_threads=True)
stage, audio = sys.argv[1], sys.argv[2]
from inference_api import engine
engine.setup_sys_path()

def run():
    if stage == "versions":
        import importlib.metadata as md
        out = {}
        for p in ["numpy", "scipy", "scikit-learn", "joblib", "librosa", "numba", "llvmlite", "soundfile",
                  "audioread", "opensmile", "audinterface", "audresample", "audobject", "praat-parselmouth",
                  "torch", "pandas"]:
            try:
                out[p] = md.version(p)
            except Exception:
                out[p] = None
        return out
    if stage == "librosa_load":
        import librosa
        y, sr = librosa.load(audio, sr=16000, mono=True)
        return {"samples": len(y), "sr": sr}
    if stage == "audio_features":
        from features.audio_features import extract_audio_features_dict
        return {"n": len(extract_audio_features_dict(audio, run_praat_voice=False))}
    if stage == "praat":
        from features.audio_features import extract_audio_features_dict
        return {"n": len(extract_audio_features_dict(audio, run_praat_voice=True))}
    if stage == "opensmile":
        from features.opensmile_features import extract_opensmile_egemaps_dict
        return {"n": len(extract_opensmile_egemaps_dict(audio))}
    cfg = dict(engine._load_yaml(engine.load_config_path()))
    cfg["transcript"] = "bugün kendimi iyi hissediyorum"
    if stage == "full_row":
        return {"n": len(engine._row_from_audio(audio, cfg["transcript"], cfg))}
    if stage == "predict":
        return engine.predict_from_uploaded_file(audio, cfg["transcript"])
    if stage == "predict_in_thread":
        res = {}
        t = threading.Thread(target=lambda: res.update(engine.predict_from_uploaded_file(audio, cfg["transcript"])))
        t.start(); t.join()
        return res
    if stage == "predict_repeat_threads":
        # Flask gibi: her istek yeni thread, aynı süreç. Snapshot sırasında çalışıp sonra çöktüğü için.
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        for i in range(n):
            t = threading.Thread(target=lambda: engine.predict_from_uploaded_file(audio, cfg["transcript"]))
            t.start(); t.join()
            print(f"repeat {i + 1}/{n} ok", file=sys.stderr, flush=True)
        return {"repeats": n}

print("RESULT " + json.dumps(run(), default=str, ensure_ascii=False))
'''


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    audio = sys.argv[1]
    for stage in STAGES:
        p = subprocess.run([sys.executable, "-c", _CODE, stage, audio], capture_output=True, text=True, timeout=600)
        if p.returncode == 0:
            line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT ")), "RESULT ?")
            print(f"[OK]    {stage}: {line[7:]}")
            continue
        kind = "CRASH (signal %d)" % -p.returncode if p.returncode < 0 else f"ERROR (exit {p.returncode})"
        print(f"[{kind}] {stage}")
        print("----- stderr (son 60 satır) -----")
        print("\n".join(p.stderr.splitlines()[-60:]))
        print("---------------------------------")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
