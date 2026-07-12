"""Tests de las piezas puras del pipeline (sin whisper/ffmpeg)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qcaptions.assgen import AssStyle, build_ass  # noqa: E402
from qcaptions.corrections import apply_corrections  # noqa: E402
from qcaptions.grouping import group_words  # noqa: E402


def _words(*pairs):
    return [{"word": w, "start": s, "end": e} for w, s, e in pairs]


def test_corrections_merge_multiword():
    words = _words(
        ("ene", 0.6, 0.8), ("ocho", 0.8, 1.0), ("ene", 1.0, 1.3), ("ya", 1.3, 1.5)
    )
    out = apply_corrections(words, [(["ene", "ocho", "ene"], "n8n")])
    assert [w["word"] for w in out] == ["n8n", "ya"]
    assert out[0]["start"] == 0.6 and out[0]["end"] == 1.3


def test_corrections_case_and_accent_insensitive():
    words = _words(("Quimballa", 0.0, 0.5))
    out = apply_corrections(words, [(["quimballa"], "Quimbaya")])
    assert out[0]["word"] == "Quimbaya"


def test_grouping_by_max_words():
    words = _words(*[(str(i), i * 0.2, i * 0.2 + 0.15) for i in range(9)])
    caps = group_words(words, max_words=3, max_duration=99)
    assert all(len(c["words"]) <= 3 for c in caps)
    assert len(caps) == 3


def test_grouping_by_duration():
    words = _words(("a", 0.0, 0.9), ("b", 0.9, 2.0), ("c", 2.0, 2.2))
    caps = group_words(words, max_words=10, max_duration=1.8)
    assert len(caps) >= 2


def test_ass_first_word_starts_gold():
    caps = group_words(_words(("hola", 0.0, 0.5), ("mundo", 0.5, 1.0)), 4, 1.8)
    ass = build_ass(caps, AssStyle())
    dialogue = [l for l in ass.splitlines() if l.startswith("Dialogue")][0]
    # La primera palabra activa en t=0 debe pintarse dorada de base (no \t(0,0)).
    assert "\\t(0,0" not in dialogue
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass


def test_ass_uppercase_toggle():
    caps = group_words(_words(("hola", 0.0, 0.5)), 4, 1.8)
    assert "HOLA" in build_ass(caps, AssStyle(uppercase=True))
    assert "hola" in build_ass(caps, AssStyle(uppercase=False))
