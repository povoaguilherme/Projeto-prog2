"""Lê, do texto do cronograma, os pesos das avaliações, a média e a frequência mínimas."""
from __future__ import annotations
import re
from decimal import Decimal
from typing import Optional

_INICIO_FORMULA = re.compile(r"c[áa]lculo\s+(?:da\s+)?nota\s+final", re.I)
_TERMO = re.compile(r"Nota\s+(?P<nome>[^()+]+?)\s*[x×*]\s*(?P<peso>\d+(?:[.,]\d+)?)", re.I)
_PESO = re.compile(r"(?P<nome>[A-Za-zÀ-ÿ][^\-–:(]*?)\s*[-–:(]\s*peso\s*(?P<peso>\d+(?:[.,]\d+)?)", re.I)
_MEDIA = re.compile(r"m[ée]dia(?:\s+m[ií]nima)?(?:\s+(?:maior\s+ou\s+igual\s+a|igual\s+ou\s+superior\s+a|de|>=|≥|=))?"
                    r"\s*(\d+(?:[.,]\d+)?)", re.I)
_FREQ = [re.compile(r"(\d{2,3})\s*%\s*(?:de\s+)?(?:frequ[êe]ncia|presen[çc]a|das\s+aulas)", re.I),
         re.compile(r"frequ[êe]ncia\s+(?:m[ií]nima\s+)?(?:de\s+)?(\d{2,3})\s*%", re.I)]


def _num(texto: str) -> Decimal:
    return Decimal(texto.replace(",", "."))


def extrair_itens(linhas: list[str]) -> list[tuple[str, Decimal]]:
    """[('SEM 1', 4), ('ED1', 3), ...] a partir de '(Nota SEM 1 x 4) + (Nota ED1 x 3)' ou 'Seminário - Peso 4'."""
    texto = " ".join(linhas)
    achou = _INICIO_FORMULA.search(texto)
    termos = list(_TERMO.finditer(texto[achou.end():] if achou else texto))
    if termos:
        return [(t["nome"].strip(), _num(t["peso"])) for t in termos]
    itens = []
    for linha in linhas:
        m = _PESO.search(linha)
        if m:
            itens.append((m["nome"].strip(), _num(m["peso"])))
    return itens


def extrair_media_minima(linhas: list[str]) -> Optional[Decimal]:
    for m in _MEDIA.finditer(" ".join(linhas)):
        valor = _num(m.group(1))
        if 3 <= valor <= 10:                       # ignora "média de 2 notas"
            return valor
    return None


def extrair_frequencia_minima(linhas: list[str]) -> Optional[float]:
    texto = " ".join(linhas)
    for rx in _FREQ:
        m = rx.search(texto)
        if m and 50 <= int(m.group(1)) <= 100:
            return float(m.group(1))
    return None
