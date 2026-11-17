"""Pequenas utilidades de texto."""
import re
import unicodedata


def chave_alfabetica(texto: str) -> str:
    """Ordena sem ligar para acento ou maiúscula: 'Álgebra' vem antes de 'Química'."""
    sem_acento = unicodedata.normalize("NFD", texto)
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower()


def chave_de_comparacao(texto: str) -> str:
    """Para saber se dois nomes são o mesmo, mesmo com erro de acento do OCR: 'Apresentac¢ao' == 'Apresentação'."""
    return re.sub(r"[^a-z0-9]+", "", chave_alfabetica(texto))
