"""Seletor nativo de pasta do sistema operacional.

Usa `tkinter` (biblioteca padrao do Python — nao adiciona dependencia nova)
para abrir o dialogo nativo de escolha de diretorio. Se tkinter nao estiver
disponivel neste ambiente (algumas instalacoes minimas de Python no Linux
nao incluem `tkinter` por padrao), devolve `None` para o chamador cair no
fallback de digitacao manual — nunca derruba o processo.
"""

from __future__ import annotations

import threading
from typing import Optional

# so uma janela de dialogo por vez: tkinter/Tcl nao foi desenhado pra ser
# chamado de varias threads simultaneamente, e cada request HTTP roda na sua
# propria thread (ThreadingHTTPServer).
_dialog_lock = threading.Lock()


def is_available() -> bool:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return False
    return True


def pick_directory(initial_dir: Optional[str] = None) -> Optional[str]:
    """Abre o dialogo nativo de escolha de pasta e devolve o caminho
    escolhido, ou `None` se o usuario cancelou, se ja existe outro dialogo
    aberto, ou se tkinter nao esta disponivel neste ambiente.
    """
    if not _dialog_lock.acquire(blocking=False):
        return None
    try:
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            return None

        root = tk.Tk()
        root.withdraw()  # so queremos o dialogo, nao uma janela vazia atras dele
        root.attributes("-topmost", True)  # senao o dialogo pode abrir atras do navegador
        try:
            chosen = filedialog.askdirectory(
                initialdir=initial_dir or None,
                mustexist=True,
                title="Escolher pasta para salvar as reunioes",
            )
        finally:
            root.destroy()
        return chosen or None
    finally:
        _dialog_lock.release()
