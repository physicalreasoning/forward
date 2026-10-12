import os
import shutil
import subprocess
import sys

import pytest

from forward import ROOT, cli, registry, scaffold


@pytest.fixture
def ran(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "run", lambda script, args: calls.append((script, args)) or 0)
    return calls


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["capture", "--out", "/tmp/l"], ("scripts/capture.py", ["--out", "/tmp/l"])),
        (["freeze", "--round", "1"], ("scripts/freeze.py", ["--round", "1"])),
        (["rehearse", "/tmp/x"], ("scripts/rehearse.py", ["/tmp/x"])),
        (["leaderboard"], ("scripts/leaderboard.py", [])),
        (["site", "--out", "a.html"], ("scripts/site.py", ["--out", "a.html"])),
        (
            ["score", "--dry-run", "2026-07-01", "2026-10-09"],
            ("scripts/score.py", ["--dry-run", "2026-07-01", "2026-10-09"]),
        ),
        (["score", "--task", "price-ladders", "--round", "2"], ("scripts/score_prices.py", ["--round", "2"])),
    ],
)
def test_steps_run_their_scripts_with_arguments_passed_through(ran, argv, expected):
    assert cli.main(argv) == 0
    assert ran == [expected]


def test_every_wrapped_script_exists():
    for script, _ in cli.SCRIPTS.values():
        assert (ROOT / script).exists()


def test_list_shows_every_entry(capsys):
    cli.main(["list"])
    out = capsys.readouterr().out
    assert all(e in out for e in registry.ENTRIES)


@pytest.mark.parametrize("name", ["Bad", "x", "has_underscore", "isotherm"])
def test_new_refuses_bad_or_taken_names(tmp_path, name):
    with pytest.raises(SystemExit):
        scaffold.new_entry(name, root=tmp_path)


def copy_of_the_package(tmp_path):
    shutil.copytree(ROOT / "forward", tmp_path / "forward", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "tests").mkdir()
    shutil.copy(ROOT / "tests" / "test_entries.py", tmp_path / "tests")
    shutil.copy(ROOT / "pyproject.toml", tmp_path)  # lint as the repo does, from its root
    return tmp_path


@pytest.mark.parametrize(
    ("make", "files"),
    [
        (
            lambda r: scaffold.new_entry("my-mean", "gaussian", "monthly mean", root=r),
            ["forward/entry_my_mean.py"],
        ),
        (lambda r: scaffold.new_entry("my-live", "ladder", root=r), ["forward/entry_my_live.py"]),
        (lambda r: scaffold.new_task("my-task", root=r), ["forward/tasks/my_task.py"]),
    ],
)
def test_scaffolded_files_are_clean_registered_and_their_tests_pass(tmp_path, make, files):
    root = copy_of_the_package(tmp_path)
    paths = make(root)
    assert [str(p.relative_to(root)) for p in paths][0] == files[0]
    # The scaffold refuses to overwrite.
    with pytest.raises(SystemExit):
        make(root)
    targets = [str(p) for p in paths] + [str(root / "forward" / "registry.py")]
    for cmd in (["check"], ["format", "--check"]):
        r = subprocess.run(
            [sys.executable, "-m", "ruff", *cmd, *targets], cwd=root, capture_output=True, text=True
        )
        assert r.returncode == 0, r.stdout
    env = os.environ | {"PYTHONPATH": str(root)}
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(paths[1])],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
