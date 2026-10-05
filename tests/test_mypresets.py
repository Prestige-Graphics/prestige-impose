"""Each computer's own presets: kept across updates, shipped ones added once each."""

import json

import pytest

from prestige_impose import engine, mypresets
from prestige_impose.engine import Settings


@pytest.fixture
def setup(tmp_path, monkeypatch):
    shipped = tmp_path / "shipped.json"
    shipped.write_text(json.dumps({"Cards": {"rows": 7, "cols": 3}}))
    monkeypatch.setattr(mypresets, "PRESETS_FILE", shipped)
    monkeypatch.setattr(engine, "PRESETS_FILE", shipped)
    return tmp_path / "config", shipped


def test_first_run_starts_with_the_shipped_presets(setup):
    folder, _ = setup
    assert mypresets.activate(folder) == folder / mypresets.MY_PRESETS
    assert list(engine.load_presets()) == ["Cards"]


def test_own_presets_kept_and_deleted_shipped_one_stays_deleted(setup):
    folder, shipped = setup
    mypresets.activate(folder)
    engine.save_preset("Postcards", Settings(rows=4, cols=2))
    engine.delete_preset("Cards")
    mypresets.activate(folder)                  # next launch, same version
    assert list(engine.load_presets()) == ["Postcards"]
    # An update ships a new preset (and still has Cards): only the new one is added.
    shipped.write_text(json.dumps({"Cards": {"rows": 7, "cols": 3},
                                   "Tickets": {"rows": 5, "cols": 2}}))
    mypresets.activate(folder)
    assert sorted(engine.load_presets()) == ["Postcards", "Tickets"]


def test_shipped_preset_never_replaces_ones_own(setup):
    folder, shipped = setup
    mypresets.activate(folder)
    engine.save_preset("Tickets", Settings(rows=9, cols=9))
    shipped.write_text(json.dumps({"Tickets": {"rows": 5, "cols": 2}}))
    mypresets.activate(folder)
    assert engine.load_presets()["Tickets"].rows == 9
