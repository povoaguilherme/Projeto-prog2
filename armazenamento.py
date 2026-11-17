"""Onde o aplicativo guarda os dados do usuário (banco de dados e registro de erros).

Antes o banco ficava na pasta de onde o programa era executado; como aplicativo, ele fica numa pasta fixa do usuário,
então os dados são os mesmos não importa de onde o programa seja aberto."""
from __future__ import annotations
import os
import shutil
import sys
from pathlib import Path

NOME_DO_APP = "CalendarioAcademico"
BANCO_ANTIGO = "calendario_academico.db"        # nome/lugar usados nas versões anteriores


def pasta_de_dados() -> Path:
    """Windows: %APPDATA%\\CalendarioAcademico | macOS: ~/Library/Application Support/... | Linux: ~/.local/share/..."""
    forcada = os.environ.get("CALENDARIO_DADOS")             # permite escolher outra pasta (e facilita os testes)
    if forcada:
        return Path(forcada)
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / NOME_DO_APP


def caminho_padrao_do_banco() -> str:
    """Caminho do banco de dados do aplicativo. Se existir um banco da versão antiga na pasta atual e ainda não
    houver um novo, COPIA o antigo (uma única vez), para ninguém perder notas e faltas."""
    destino = pasta_de_dados() / "dados.db"
    antigo = Path.cwd() / BANCO_ANTIGO
    if not destino.exists() and antigo.is_file():
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(antigo, destino)
    return str(destino)
