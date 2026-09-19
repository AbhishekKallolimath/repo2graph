import argparse
import pytest
from repo2graph.cli import _max_file_mb
from repo2graph.graph import build
from repo2graph.parse import BuildConfig


def test_max_file_mb_validator():
    assert _max_file_mb("1.5") == 1.5
    assert _max_file_mb("0.1") == 0.1
    with pytest.raises(argparse.ArgumentTypeError, match="must be at least 0.1"):
        _max_file_mb("0.09")
    with pytest.raises(argparse.ArgumentTypeError, match="expected a number, got 'abc'"):
        _max_file_mb("abc")


def test_file_limits(tmp_path):
    # create files
    repo = tmp_path / "repo"
    repo.mkdir()

    under_limit_file = repo / "under_limit.py"
    over_limit_file = repo / "over_limit.py"

    under_content = b"a = 1\n" * (1_499_900 // 6)
    under_content += b"x" * (1_499_900 - len(under_content))
    under_limit_file.write_bytes(under_content)

    over_content = b"b = 2\n" * (1_500_100 // 6)
    over_content += b"y" * (1_500_100 - len(over_content))
    over_limit_file.write_bytes(over_content)

    # default config
    g = build(repo)
    assert "file:under_limit.py" in g.nodes
    assert "file:over_limit.py" not in g.nodes

    # chunk large files config
    config = BuildConfig(chunk_large_files=True)
    g2 = build(repo, config=config)
    assert "file:under_limit.py" in g2.nodes
    assert "file:over_limit.py" in g2.nodes
    assert g2.nodes["file:over_limit.py"].get("chunked") is True


def test_exclude_dir(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    normal_dir = repo / "normal"
    normal_dir.mkdir()
    (normal_dir / "a.py").write_text("a = 1")

    excluded_dir = repo / "my_excluded"
    excluded_dir.mkdir()
    (excluded_dir / "b.py").write_text("b = 2")

    # default
    g = build(repo)
    assert "file:normal/a.py" in g.nodes
    assert "file:my_excluded/b.py" in g.nodes

    # with exclude
    config = BuildConfig(extra_exclude_dirs=["my_excluded"])
    g2 = build(repo, config=config)
    assert "file:normal/a.py" in g2.nodes
    assert "file:my_excluded/b.py" not in g2.nodes
