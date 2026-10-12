import json

import pytest

from forward import seal


@pytest.fixture
def frozen_round(tmp_path):
    (tmp_path / "SPEC.md").write_text("spec")
    (tmp_path / "code.py").write_text("x = 1\n")
    params = {"NY": {"raw-aifs": 2.5}}
    fz = {
        "spec": "SPEC.md",
        "spec_sha256": seal.sha256_file("SPEC.md", tmp_path),
        "code_sha256": {"code.py": seal.sha256_file("code.py", tmp_path)},
        "params_sha256": seal.params_hash(params),
        "params": params,
    }
    (tmp_path / "frozen").mkdir()
    (tmp_path / "frozen" / "round7.json").write_text(json.dumps(fz))
    return tmp_path


def test_untouched_round_loads(frozen_round):
    assert seal.check_frozen(7, frozen_round)["params"] == {"NY": {"raw-aifs": 2.5}}


@pytest.mark.parametrize("target", ["SPEC.md", "code.py"])
def test_any_changed_file_refuses(frozen_round, target):
    (frozen_round / target).write_text("changed")
    with pytest.raises(SystemExit, match=target):
        seal.check_frozen(7, frozen_round)


def test_changed_parameters_refuse(frozen_round):
    f = frozen_round / "frozen" / "round7.json"
    fz = json.loads(f.read_text())
    fz["params"]["NY"]["raw-aifs"] = 1.0
    f.write_text(json.dumps(fz))
    with pytest.raises(SystemExit, match="params"):
        seal.check_frozen(7, frozen_round)


def test_params_hash_ignores_key_order():
    assert seal.params_hash({"a": 1, "b": 2}) == seal.params_hash({"b": 2, "a": 1})
