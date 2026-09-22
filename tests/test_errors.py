"""Failures reach the user as a sentence, not a traceback.

A CLI that answers a mistyped space with 200 lines of Rich-formatted stack is
telling the user about its own call graph instead of about their mistake. Every
command body runs inside `cli.coro`, so that wrapper is the one place this has to
be right.
"""

from __future__ import annotations

import click
import httpx
import pytest
import typer

from swsh import cli


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("SIGNALWIRE_PROJECT_ID", "proj-1")
    monkeypatch.setenv("SIGNALWIRE_API_TOKEN", "tok")
    monkeypatch.setenv("SIGNALWIRE_SPACE", "scratch.signalwire.com")
    for var in ("PROJECT_ID", "REST_API_TOKEN", "SWSH_PROFILE", "SW_TRACEBACK"):
        monkeypatch.delenv(var, raising=False)


def failing(exc: Exception):
    """A command that raises, wrapped exactly as a real one is."""

    @cli.coro
    async def command(client):
        raise exc

    return command


def run(exc: Exception) -> int:
    with pytest.raises(typer.Exit) as caught:
        failing(exc)()
    return caught.value.exit_code


class TestNothingEscapesAsATraceback:
    def test_a_dns_failure_is_one_line_naming_the_space(self, capsys):
        assert run(httpx.ConnectError("[Errno 8] nodename nor servname provided")) == 1
        err = capsys.readouterr().err
        assert "cannot reach scratch.signalwire.com" in err
        assert "SIGNALWIRE_SPACE" in err
        assert "Traceback" not in err

    def test_a_timeout_says_so(self, capsys):
        assert run(httpx.ConnectTimeout("timed out")) == 1
        assert "timed out talking to scratch.signalwire.com" in capsys.readouterr().err

    def test_any_other_transport_error_is_still_handled(self, capsys):
        assert run(httpx.RemoteProtocolError("bad chunk")) == 1
        err = capsys.readouterr().err
        assert "RemoteProtocolError" in err
        assert "Traceback" not in err

    def test_an_os_error_is_handled(self, capsys):
        assert run(OSError("socket is closed")) == 1
        assert "socket is closed" in capsys.readouterr().err

    def test_an_unexpected_exception_gets_one_line_and_a_way_in(self, capsys):
        # The catch-all. A bug in sw should still not print a stack at someone
        # who was only trying to list their phone numbers.
        assert run(ValueError("synthetic")) == 1
        err = capsys.readouterr().err
        assert "ValueError: synthetic" in err
        assert "SW_TRACEBACK=1" in err
        assert "Traceback" not in err

    def test_sw_traceback_opts_back_in(self, monkeypatch):
        # Debuggability is not removed, only moved behind a flag.
        monkeypatch.setenv("SW_TRACEBACK", "1")
        with pytest.raises(ValueError, match="synthetic"):
            failing(ValueError("synthetic"))()

    def test_an_interrupt_uses_the_conventional_code(self):
        assert run(KeyboardInterrupt()) == 130

    def test_a_swsh_error_keeps_its_own_message(self, capsys):
        from swsh.client import SwshError

        assert run(SwshError("no spec operation for 'nope'")) == 1
        assert "no spec operation for 'nope'" in capsys.readouterr().err


class TestControlFlowIsNotSwallowed:
    """The catch-all must not eat Click's control-flow exceptions.

    When it did, every `raise typer.Exit(2)` inside a command body — the usage
    errors that `sw api` and the CRUD verbs raise after printing their own
    message — came out as exit 1, and the message was printed twice.
    """

    def test_an_explicit_exit_code_survives(self):
        assert run(typer.Exit(2)) == 2
        assert run(typer.Exit(130)) == 130

    def test_a_clean_exit_survives(self):
        assert run(typer.Exit()) == 0

    def test_a_click_exception_is_left_for_click_to_render(self):
        with pytest.raises(click.UsageError):
            failing(click.UsageError("expected key=value"))()

    def test_the_message_is_not_printed_twice(self, capsys):
        # A body that reported its own problem then exited must not be described
        # again by the wrapper.
        assert run(typer.Exit(2)) == 2
        assert capsys.readouterr().err == ""


class TestTheReporterIsItselfSafe:
    def test_describing_an_error_never_raises(self, monkeypatch):
        # _describe_network_error resolves the profile to name the space. If that
        # resolution is what is broken, reporting must not fail on top of it.
        def explode(*_args, **_kwargs):
            raise RuntimeError("profile is unreadable")

        monkeypatch.setattr(cli, "_profile", explode)
        message = cli._describe_network_error(httpx.ConnectError("boom"))
        assert "the configured space" in message
