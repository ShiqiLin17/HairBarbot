"""Tests for the head-size menu:  python tests/test_head_profile.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vision"))

from head_profile import (ANSUR_II, ask_head_profile, average_profile, check_circumference, parse_length,
                          personalized_profile)


def test_parse_units():
    cases = {"57 cm": 570, "57cm": 570, "22.5 in": 571.5, "22.5in": 571.5, "22.5 inches": 571.5, '22.5"': 571.5,
             "570 mm": 570, "0.57 m": 570, "57,5 cm": 575, "57 CM": 570, "57 cm.": 570}
    for text, mm in cases.items():
        assert abs(parse_length(text) - mm) < 0.01, (text, parse_length(text))


def test_parse_rejects_missing_or_unknown_units():
    for bad in ["57", "cm", "fifty cm", "57 furlongs", ""]:
        try:
            parse_length(bad)
        except ValueError:
            continue
        raise AssertionError(f"should reject {bad!r}")


def test_circumference_range():
    check_circumference(560)
    for bad in [57, 5700, 300]:      # e.g. typed 57 mm by mistake
        try:
            check_circumference(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_profiles_match_ansur_and_scale():
    f, m = average_profile("female"), average_profile("male")
    assert f.axes == (95.0, 73.5, 127.0) and m.axes == (100.0, 77.0, 131.0)
    assert f.face_scale < m.face_scale == 1.0
    p = personalized_profile(600)
    assert p.circumference == 600 and p.length > m.length      # a 60 cm head is bigger than the male average


def test_menu():
    out = []
    answers = iter(["4", "3", "57", "fifty cm", "22.5 in"])
    p = ask_head_profile(input_fn=lambda prompt: next(answers), print_fn=out.append)
    assert p.label == "Personal" and abs(p.circumference - 571.5) < 0.01
    assert any("1, 2 or 3" in o for o in out) and any("unit" in o for o in out)
    assert ask_head_profile(input_fn=lambda _: "1", print_fn=lambda *_: None).label == "Average female"
    assert ask_head_profile(input_fn=lambda _: "2", print_fn=lambda *_: None).label == "Average male"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
