"""Tests de las piezas puras del pipeline (sin whisper/ffmpeg)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qcaptions.assgen import AssStyle, build_ass, scale_style  # noqa: E402
from qcaptions.corrections import (  # noqa: E402
    apply_corrections,
    load_corrections,
    load_settings,
)
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


def test_scale_style_4k_vertical():
    s = scale_style(AssStyle(), 2160, 3840)  # 4K vertical = 2x
    assert (s.play_res_x, s.play_res_y) == (2160, 3840)
    assert s.fontsize == 180 and s.outline == 12
    assert s.margin_v == 1200 and s.margin_lr == 120


def test_scale_style_identity_1080():
    s = scale_style(AssStyle(), 1080, 1920)
    assert s.fontsize == 90 and s.outline == 6 and s.margin_v == 600
    ass = build_ass(group_words(_words(("a", 0.0, 0.5)), 4, 1.8), s)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass


def test_scale_style_header_uses_real_resolution():
    s = scale_style(AssStyle(), 2160, 3840)
    ass = build_ass(group_words(_words(("a", 0.0, 0.5)), 4, 1.8), s)
    assert "PlayResX: 2160" in ass and "PlayResY: 3840" in ass


def test_intro_filter_graph():
    from qcaptions.intro import IntroSpec, build_filter

    spec = IntroSpec(logo=Path("/tmp/logo.png"), start=0.3, duration=2.2,
                     width_frac=0.45, y_frac=0.20)
    graph = build_filter(spec, 1080, 1920, "subs.ass")
    assert "scale=486:-1" in graph            # 1080 * 0.45
    assert "fade=t=in:st=0.3" in graph
    assert "between(t,0.3,2.5)" in graph      # start -> start+duration
    assert graph.endswith("ass=subs.ass[vout]")


def test_intro_from_config():
    import tempfile

    from qcaptions.intro import from_config

    assert from_config({}) is None            # sin logo -> sin intro
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        spec = from_config({"logo": f.name, "duration": 3.0})
        assert spec is not None and spec.duration == 3.0
        # el flag --intro pisa a la config
        spec2 = from_config({"logo": "/no/existe.png"}, override_logo=Path(f.name))
        assert spec2 is not None and str(spec2.logo) == f.name


def test_intro_card_filter_and_shift():
    from qcaptions.intro import IntroSpec, build_card_filter

    spec = IntroSpec(logo=Path("/tmp/logo.png"), mode="card", duration=2.8)
    assert spec.shift == 2.3  # duration - XFADE(0.5)
    graph = build_card_filter(spec, 1080, 1920, 30.0, "subs.ass")
    assert "color=0x000000:s=1080x1920" in graph
    assert "xfade=transition=fade:duration=0.5:offset=2.300" in graph
    assert "adelay=2300:all=1" in graph
    assert "abs(X-W/2)+abs(Y-H/2)" in graph   # revelado Manhattan (circuito)
    assert "gblur" in graph                    # glow default en card
    # overlay no desplaza nada
    assert IntroSpec(logo=Path("/tmp/l.png")).shift == 0.0


def test_intro_card_custom_knobs():
    from qcaptions.intro import IntroSpec, build_card_filter, from_config

    spec = IntroSpec(logo=Path("/tmp/logo.png"), mode="card",
                     bg="#07080b", glow=False, reveal_duration=2.0)
    graph = build_card_filter(spec, 1080, 1920, 30.0, "s.ass")
    assert "color=0x07080b" in graph
    assert "gblur" not in graph
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        spec2 = from_config({"logo": f.name, "mode": "card", "bg": "07080b",
                             "feather": 90, "glow": False})
        assert spec2.bg == "#07080b" and spec2.feather == 90 and not spec2.glow
    # bg inválido debe fallar claro
    try:
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            from_config({"logo": f.name, "mode": "card", "bg": "azul"})
        raise AssertionError("bg inválido no falló")
    except Exception as e:
        assert "bg inválido" in str(e)


def test_intro_card_config_defaults():
    import tempfile

    from qcaptions.intro import from_config

    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        spec = from_config({"logo": f.name, "mode": "card"})
        assert spec.mode == "card"
        assert spec.duration == 2.8 and spec.width_frac == 0.55
        # el usuario puede pisar los defaults del modo
        spec2 = from_config({"logo": f.name, "mode": "card", "duration": 4.0})
        assert spec2.duration == 4.0


def test_load_settings_merge_last_wins():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / "a.toml"
        b = Path(d) / "b.toml"
        a.write_text(
            '[settings]\nmodel = "ggml-medium"\n[corrections]\n"x" = "y"\n',
            encoding="utf-8",
        )
        b.write_text(
            '[settings]\nmodel = "ggml-large-v3-turbo-q5_0"\n', encoding="utf-8"
        )
        assert load_settings([a, b])["model"] == "ggml-large-v3-turbo-q5_0"
        assert load_settings([b, a])["model"] == "ggml-medium"
        assert load_settings([Path(d) / "nope.toml"]) == {}


def test_load_corrections_merge_user_over_project(tmp_path=None):
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "proj.toml"
        user = Path(d) / "user.toml"
        proj.write_text(
            '[corrections]\n"cloud" = "Claude"\n"emcp" = "MCP"\n',
            encoding="utf-8",
        )
        user.write_text('[corrections]\n"Cloud" = "cloud"\n', encoding="utf-8")
        rules = load_corrections([proj, user])
        as_dict = {" ".join(k): v for k, v in rules}
        # el user config pisa al del proyecto (match normalizado)
        assert as_dict["cloud"] == "cloud"
        assert as_dict["emcp"] == "MCP"
        # rutas inexistentes se ignoran sin error
        assert load_corrections([Path(d) / "nope.toml"]) == []
