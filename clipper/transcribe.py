"""Paroles mot à mot avec Whisper (faster-whisper), en local, sur la carte graphique si elle est là."""
from __future__ import annotations

import os
from pathlib import Path

from .analyze import Word
from .util import log

_model = None
_name = None


def _cuda_dlls():
    """Windows : les DLL CUDA des paquets pip nvidia-cublas-cu12 / nvidia-cudnn-cu12 ne sont pas trouvées toutes seules"""
    if os.name != "nt":
        return
    import glob
    import site
    dirs = [site.getusersitepackages(), *site.getsitepackages()]
    for d in dirs:
        for b in glob.glob(os.path.join(d, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(b)
            except OSError:
                pass
            os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")


def _gpu() -> bool:
    _cuda_dlls()
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def load(name: str | None = None, cpu: bool = False):
    global _model, _name
    if _model is not None and not cpu:
        return _model
    from faster_whisper import WhisperModel
    gpu = _gpu() and not cpu
    name = name or os.environ.get("CLIPPER_WHISPER") or ("large-v3-turbo" if gpu else "small")
    log(f"Whisper {name} sur {'la carte graphique' if gpu else 'le processeur'} (premier lancement : téléchargement du modèle)")
    _model = WhisperModel(name, device="cuda" if gpu else "cpu", compute_type="float16" if gpu else "int8")
    _name = name
    return _model


def words(wav: Path, lang: str | None = None) -> tuple[list[Word], str]:
    global _model
    for essai in range(2):
        m = load(_name)
        try:
            segs, info = m.transcribe(str(wav), language=lang, word_timestamps=True, vad_filter=True,
                                      beam_size=5, condition_on_previous_text=False)
            out = [Word(float(w.start), float(w.end), w.word.strip())
                   for s in segs for w in (s.words or []) if w.word.strip()]
            return out, info.language
        except RuntimeError as e:  # carte graphique sans les bibliothèques CUDA : on repasse sur le processeur
            if essai or "cuda" not in str(e).lower() and "cublas" not in str(e).lower() and "cudnn" not in str(e).lower():
                raise
            log(f"Whisper ne tourne pas sur la carte graphique ({e}) : passage au processeur")
            _model = None
            load("small", cpu=True)
    return [], lang or "en"
