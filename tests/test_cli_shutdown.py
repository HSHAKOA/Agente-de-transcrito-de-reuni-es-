"""Testes do shutdown gracioso do cli.py.

Nao registram signal handlers de verdade nem chamam os._exit (o que mataria
o processo do pytest) -- em vez disso, testam a funcao pura que produz o
handler (`_make_shutdown_handler`), injetando um `force_exit` falso.
"""

import threading

from meeting_transcriber.cli import _make_shutdown_handler


def test_first_signal_sets_stop_event_without_forcing_exit():
    stop_event = threading.Event()
    calls = []
    handler = _make_shutdown_handler(stop_event, force_exit=calls.append)

    handler(signum=2, frame=None)

    assert stop_event.is_set()
    assert calls == []


def test_second_signal_forces_exit():
    stop_event = threading.Event()
    calls = []
    handler = _make_shutdown_handler(stop_event, force_exit=calls.append)

    handler(signum=2, frame=None)
    handler(signum=2, frame=None)

    assert calls == [1]  # os._exit(1) -- so uma chamada mesmo que um 3o sinal chegue depois


def test_third_signal_forces_exit_again():
    stop_event = threading.Event()
    calls = []
    handler = _make_shutdown_handler(stop_event, force_exit=calls.append)

    handler(signum=2, frame=None)
    handler(signum=2, frame=None)
    handler(signum=2, frame=None)

    assert calls == [1, 1]
