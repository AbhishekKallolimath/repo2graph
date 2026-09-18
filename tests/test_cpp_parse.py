import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

from repo2graph.parse import parse_source


def test_cpp_parse_pass_1():
    # Simple #define handled fine by tree-sitter (0 errors)
    source = b"#define FOO 1\nint main() { return FOO; }"
    pf = parse_source(source, "c", filepath=Path("test.c"))
    assert pf.parse_errors == 0
    assert not pf.used_cpp


@patch("subprocess.run")
def test_cpp_parse_pass_2(mock_run):
    # A macro that tree-sitter cannot handle produces an ERROR node
    # e.g., an unclosed bracket or weird token in macro
    source = b"#define MACRO { error \nint main() MACRO }"

    # Mock subprocess.run to first succeed for 'cpp --version', then for 'cpp -w ...'
    def mock_run_impl(cmd, **kwargs):
        if "--version" in cmd:
            return MagicMock(returncode=0)
        else:
            return MagicMock(returncode=0, stdout="int main() { return 0; }")
    mock_run.side_effect = mock_run_impl

    pf = parse_source(source, "c", filepath="test.c")
    # Tree-sitter would normally error on `source`, but with cpp_output it's 0 errors
    assert pf.parse_errors == 0
    assert pf.used_cpp
    assert mock_run.call_count == 2


@patch("subprocess.run")
def test_cpp_parse_cpp_unavailable(mock_run):
    source = b"#define MACRO { error \nint main() MACRO }"

    # Mock subprocess.run to raise FileNotFoundError for cpp
    mock_run.side_effect = FileNotFoundError

    pf = parse_source(source, "c", filepath="test.c")
    # Should fall back to Pass 1 result silently
    assert pf.parse_errors > 0
    assert not pf.used_cpp


@patch("subprocess.run")
def test_cpp_parse_cpp_too_large(mock_run, caplog):
    source = b"#define MACRO { error \nint main() MACRO }"

    def mock_run_impl(cmd, **kwargs):
        if "--version" in cmd:
            return MagicMock(returncode=0)
        else:
            # Return output larger than 2x original size
            return MagicMock(returncode=0, stdout="int main() { return 0; } " * 10)
    mock_run.side_effect = mock_run_impl

    with caplog.at_level(logging.WARNING):
        pf = parse_source(source, "c", filepath="test.c")

    # Should skip cpp and use Pass 1
    assert pf.parse_errors > 0
    assert not pf.used_cpp
    assert "is too large, skipping" in caplog.text

