"""Package-level smoke tests."""

from importlib.metadata import version

from bgvoice import __version__


def test_package_version() -> None:
    """The installed package exposes its project version."""
    assert __version__ == version("bgvoice")
