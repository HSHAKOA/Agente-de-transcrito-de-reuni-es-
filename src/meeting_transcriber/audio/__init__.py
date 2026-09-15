"""Camada de audio: descoberta de dispositivos, captura (loopback do
sistema + microfone), medicao de nivel e mixagem — isolada do
`recorder.py`/`cli.py` existentes (que continuam cuidando so da gravacao
em blocos e do loop de transcricao) para poder ser testada com dublês, sem
hardware real, e reutilizada tanto pela API quanto pela captura de
verdade.
"""
