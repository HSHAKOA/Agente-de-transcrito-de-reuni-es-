"""Testes do wrapper do dialogo nativo de pasta. Nao abrem nenhuma janela de
verdade -- tkinter e substituido por um dublê (via monkeypatch de
sys.modules) pra rodar em CI/headless sem display."""

from __future__ import annotations

import sys
import types

import pytest

from meeting_transcriber import folder_dialog


class _FakeTk:
    def __init__(self):
        self.withdrawn = False
        self.topmost = None
        self.destroyed = False

    def withdraw(self):
        self.withdrawn = True

    def attributes(self, name, value):
        if name == "-topmost":
            self.topmost = value

    def destroy(self):
        self.destroyed = True


@pytest.fixture
def fake_tkinter(monkeypatch):
    """Registra modulos falsos `tkinter` e `tkinter.filedialog` em
    sys.modules, do jeito que os imports locais em folder_dialog.py os
    encontrariam."""
    created_roots = []
    chosen_holder = {"value": "D:/Reunioes"}

    fake_tk_module = types.ModuleType("tkinter")

    def _tk_factory():
        root = _FakeTk()
        created_roots.append(root)
        return root

    fake_tk_module.Tk = _tk_factory

    fake_filedialog_module = types.ModuleType("tkinter.filedialog")

    def _askdirectory(**kwargs):
        return chosen_holder["value"]

    fake_filedialog_module.askdirectory = _askdirectory

    monkeypatch.setitem(sys.modules, "tkinter", fake_tk_module)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", fake_filedialog_module)

    yield types.SimpleNamespace(roots=created_roots, chosen=chosen_holder)


def test_pick_directory_returns_chosen_path(fake_tkinter):
    result = folder_dialog.pick_directory()
    assert result == "D:/Reunioes"
    assert fake_tkinter.roots[0].withdrawn is True
    assert fake_tkinter.roots[0].destroyed is True


def test_pick_directory_returns_none_when_cancelled(fake_tkinter):
    fake_tkinter.chosen["value"] = ""  # askdirectory devolve "" quando o usuario cancela
    assert folder_dialog.pick_directory() is None


def test_pick_directory_destroys_window_even_on_error(monkeypatch, fake_tkinter):
    import tkinter.filedialog as fd  # o modulo falso registrado pelo fixture

    def _boom(**kwargs):
        raise RuntimeError("erro simulado no dialogo")

    monkeypatch.setattr(fd, "askdirectory", _boom)

    with pytest.raises(RuntimeError):
        folder_dialog.pick_directory()

    assert fake_tkinter.roots[0].destroyed is True


def test_is_available_true_when_tkinter_importable(fake_tkinter):
    assert folder_dialog.is_available() is True


def test_pick_directory_returns_none_when_tkinter_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "tkinter", None)  # simula ImportError na importacao
    assert folder_dialog.pick_directory() is None


def test_is_available_false_when_tkinter_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "tkinter", None)
    assert folder_dialog.is_available() is False


def test_concurrent_calls_second_one_gets_none_immediately(fake_tkinter):
    """So um dialogo por vez -- uma segunda chamada enquanto a primeira
    "esta aberta" (lock ja adquirido) devolve None na hora em vez de
    empilhar dialogos."""
    assert folder_dialog._dialog_lock.acquire(blocking=False)
    try:
        assert folder_dialog.pick_directory() is None
    finally:
        folder_dialog._dialog_lock.release()
