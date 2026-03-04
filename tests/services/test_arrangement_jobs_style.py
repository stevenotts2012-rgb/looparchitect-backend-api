import json

from app.services.arrangement_jobs import _parse_style_sections, _parse_seed_from_json


def test_parse_style_sections_valid_payload() -> None:
    raw = json.dumps(
        [
            {"name": "intro", "bars": 8, "energy": 0.3},
            {"name": "hook", "bars": 8, "energy": 0.8},
        ]
    )

    parsed = _parse_style_sections(raw)
    assert parsed is not None
    assert len(parsed) == 2
    assert parsed[0]["start_bar"] == 0
    assert parsed[0]["end_bar"] == 7
    assert parsed[1]["start_bar"] == 8
    assert parsed[1]["end_bar"] == 15


def test_parse_style_sections_wrapped_with_seed() -> None:
    """Test parsing sections from new wrapped format with seed."""
    raw = json.dumps(
        {
            "seed": 12345,
            "sections": [
                {"name": "intro", "bars": 4, "energy": 0.3},
                {"name": "verse", "bars": 8, "energy": 0.6},
            ]
        }
    )

    parsed = _parse_style_sections(raw)
    assert parsed is not None
    assert len(parsed) == 2
    assert parsed[0]["name"] == "intro"
    assert parsed[0]["bars"] == 4
    assert parsed[0]["start_bar"] == 0
    assert parsed[0]["end_bar"] == 3
    assert parsed[1]["name"] == "verse"
    assert parsed[1]["start_bar"] == 4
    assert parsed[1]["end_bar"] == 11


def test_parse_style_sections_ignores_invalid_payload() -> None:
    assert _parse_style_sections("{}") is None
    assert _parse_style_sections("[]") is None
    assert _parse_style_sections("not-json") is None


def test_parse_seed_from_json_valid() -> None:
    """Test extracting seed from wrapped format."""
    raw = json.dumps(
        {
            "seed": 99999,
            "sections": [{"name": "test", "bars": 4}]
        }
    )

    seed = _parse_seed_from_json(raw)
    assert seed == 99999


def test_parse_seed_from_json_missing() -> None:
    """Test that seed extraction returns None when not present."""
    # Legacy format (array)
    raw_array = json.dumps([{"name": "test", "bars": 4}])
    assert _parse_seed_from_json(raw_array) is None

    # Object without seed
    raw_no_seed = json.dumps({"sections": [{"name": "test", "bars": 4}]})
    assert _parse_seed_from_json(raw_no_seed) is None

    # Invalid JSON
    assert _parse_seed_from_json("not-json") is None

    # None input
    assert _parse_seed_from_json(None) is None


def test_parse_seed_from_json_zero_seed() -> None:
    """Test that zero seed is correctly parsed (not treated as falsy)."""
    raw = json.dumps({"seed": 0, "sections": []})
    seed = _parse_seed_from_json(raw)
    assert seed == 0
