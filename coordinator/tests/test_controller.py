import pytest, os, tempfile, argparse
from core.controller import save_args, get_logfile_path

def test_get_logfile_path_with_logdir():
    """Test logfile path generation with logdir"""
    with tempfile.TemporaryDirectory() as tmpdir:
        args = argparse.Namespace(logdir=tmpdir)
        save_args(args)

        path = get_logfile_path("test")
        assert tmpdir in path
        assert "test.log" in path
        assert os.path.dirname(path) == tmpdir

def test_get_logfile_path_without_logdir():
    """Test logfile path generation without logdir"""
    args = argparse.Namespace(logdir=None)
    save_args(args)

    path = get_logfile_path("test")
    assert "test.log" in path
    assert "/" not in path  # Should be just filename
