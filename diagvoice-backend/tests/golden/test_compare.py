"""Karşılaştırıcının kendi testleri (servis gerektirmez)."""

from tests.golden.cases import SAMPLES_DIR, build_cases
from tests.golden.compare import Rules, changed_paths, compare


def test_equal_objects_have_no_diff():
    a = {"label": "happy", "probs": [0.1, 0.9], "ok": True, "x": None}
    assert compare(a, dict(a)) == []


def test_numeric_tolerance():
    assert compare({"v": 0.5000}, {"v": 0.5004}) == []
    diffs = compare({"v": 0.50}, {"v": 0.52})
    assert len(diffs) == 1 and diffs[0].path == "$.v"


def test_bool_is_not_number():
    assert compare({"v": True}, {"v": 1})


def test_int_and_float_compare_as_numbers():
    assert compare({"v": 1}, {"v": 1.0}) == []


def test_missing_and_extra_keys():
    kinds = {d.kind for d in compare({"a": 1, "b": 2}, {"a": 1, "c": 3})}
    assert kinds == {"eksik alan", "fazla alan"}
    assert compare({"a": 1}, {"a": 1, "c": 3}, Rules(allow_extra_keys=True)) == []


def test_list_length_and_items():
    assert compare([1, 2], [1, 2, 3])[0].kind.startswith("liste uzunluğu")
    assert compare([{"l": "a"}], [{"l": "b"}])[0].path == "$[0].l"


def test_default_ignore_timing_fields():
    assert compare({"processing_time_ms": 10, "r": {"elapsed_sec": 1}}, {"processing_time_ms": 99, "r": {"elapsed_sec": 7}}) == []


def test_fuzzy_text():
    e = {"stt": {"text": "bugün çok güzel bir gün"}}
    assert compare(e, {"stt": {"text": "bugün çok güzel bir gün."}}) == []
    assert compare(e, {"stt": {"text": "tamamen farklı bir cümle"}})
    # bulanık olmayan alan birebir olmalı
    assert compare({"label": "happy"}, {"label": "happy."})


def test_volatile_paths_override():
    rules = Rules().with_overrides(None, extra_ignore=["$.audio.probs[0]"])
    assert compare({"audio": {"probs": [0.1, 0.9]}}, {"audio": {"probs": [0.5, 0.9]}}, rules) == []


def test_case_overrides_extend_ignore():
    rules = Rules().with_overrides({"ignore": ["$.foo"], "abs_tol": 0.1})
    assert "$.foo" in rules.ignore and "*processing_time*" in rules.ignore
    assert compare({"foo": 1, "v": 0.5}, {"foo": 2, "v": 0.55}, rules) == []


def test_changed_paths_is_strict():
    assert changed_paths({"a": 0.5, "b": "x"}, {"a": 0.5000001, "b": "x"}) == ["$.a"]


def test_nan_equals_nan():
    assert compare({"v": float("nan")}, {"v": float("nan")}) == []


def test_cases_are_valid_and_samples_exist():
    cases = build_cases()
    assert len(cases) > 50
    for c in cases:
        if c.audio:
            assert (SAMPLES_DIR / c.audio).is_file(), c.audio
