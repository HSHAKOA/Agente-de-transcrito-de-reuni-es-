"""Escrita atomica de arquivos pequenos de estado (`levels.json`,
`live_transcript.json`, `state.json`, `settings.json`, `schedules.json`).

O padrao e sempre o mesmo: escreve num temporario ao lado e troca com
`os.replace`, que e atomico -- nenhum leitor nunca ve um arquivo pela
metade.

No Windows, porem, `os.replace` falha com `PermissionError [WinError 5]`
quando ALGUEM tem o destino aberto: o `open()` do CPython nao pede
`FILE_SHARE_DELETE`, entao basta o painel estar lendo o arquivo naquele
instante para a troca ser negada. Antivirus e indexador do sistema causam
o mesmo efeito.

Isso nao e teoria: numa gravacao real de 1h53 (21/09/2026) a troca de
`levels.json` -- feita 5x por segundo enquanto o painel lia o mesmo arquivo
para o SSE dos medidores -- falhou dezenas de vezes. Cada falha despejava
um traceback completo no log, e o log do painel (deque de 300 linhas) virou
quase so isso, expulsando qualquer informacao util.

A janela de colisao e de fracoes de milissegundo, entao algumas tentativas
com um atraso minimo resolvem. Se todas falharem, a excecao original
propaga -- uma permissao de verdade ou disco cheio continua sendo erro.

`settings.py` e `scheduling/store.py` ja tinham, cada um, sua propria copia
desta funcao; `cli.py` e `session.py` nao tinham nenhuma. Esta e a copia
unica.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

DEFAULT_ATTEMPTS = 5
DEFAULT_DELAY = 0.05


def replace_with_retry(
    src: Path, dst: Path, attempts: int = DEFAULT_ATTEMPTS, delay: float = DEFAULT_DELAY, sleep=time.sleep
) -> None:
    """`os.replace(src, dst)` tolerando a negacao transitoria do Windows.

    `sleep` e injetavel para os testes nao esperarem tempo real.
    """
    last_exc: Optional[OSError] = None
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            last_exc = exc
            if attempt < attempts - 1:
                sleep(delay)
    assert last_exc is not None
    raise last_exc


def write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Escreve `text` em `path` de forma atomica.

    O temporario leva o PID no nome para que dois processos escrevendo o
    mesmo destino (painel e gravador) nunca disputem o mesmo temporario.
    """
    tmp_path = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp_path.write_text(text, encoding=encoding)
    replace_with_retry(tmp_path, path)


def write_json(path: Path, data, *, ensure_ascii: bool = False, indent: Optional[int] = None) -> None:
    """Atalho para o caso mais comum: um dict/list serializado em JSON."""
    write_text(path, json.dumps(data, ensure_ascii=ensure_ascii, indent=indent))
