"""Tests for the JSON settings used by the server."""

import json

from kvk_reader.config import DEFAULTS
from kvk_reader.settings import Settings, coerce_value


class TestCoerceValue:
    def test_int_from_form_string(self):
        assert coerce_value("8899", 0) == 8899

    def test_int_falls_back_on_garbage(self):
        assert coerce_value("abc", 7) == 7

    def test_bool_from_string(self):
        assert coerce_value("true", False) is True
        assert coerce_value("ja", False) is True
        assert coerce_value("false", False) is False

    def test_bool_stays_bool(self):
        assert coerce_value(True, False) is True

    def test_none_becomes_empty_string(self):
        assert coerce_value(None, "") == ""


class TestSettings:
    def test_defaults_when_no_file(self, tmp_path):
        settings = Settings(path=str(tmp_path / "config.json"))
        assert settings.get_int("api/port") == DEFAULTS["api/port"]
        assert settings.get_str("praxis/bsnr") == ""

    def test_set_persists_immediately(self, tmp_path):
        path = tmp_path / "config.json"
        Settings(path=str(path)).set("praxis/bsnr", "123456789")
        assert json.loads(path.read_text())["praxis/bsnr"] == "123456789"

    def test_reload_keeps_values(self, tmp_path):
        path = str(tmp_path / "config.json")
        Settings(path=path).set("praxis/lanr", "987654321")
        assert Settings(path=path).get_str("praxis/lanr") == "987654321"

    def test_update_coerces_and_filters(self, tmp_path):
        settings = Settings(path=str(tmp_path / "config.json"))
        settings.update({"api/port": "9000", "unbekannt": "x"})
        assert settings.get("api/port") == 9000
        assert "unbekannt" not in settings.as_dict()

    def test_broken_file_falls_back_to_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("{kein gültiges JSON")
        settings = Settings(path=str(path))
        assert settings.get_int("api/port") == DEFAULTS["api/port"]
