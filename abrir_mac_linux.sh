#!/bin/sh
# Abre o Calendario Academico no macOS/Linux (na primeira vez instala o que falta).
cd "$(dirname "$0")" || exit 1
python3 -m pip install -q -r requirements.txt
python3 CalendarioAcademico.pyw
