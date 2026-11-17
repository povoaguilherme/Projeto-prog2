"""Reconhecimento de datas e horários em linhas de cronograma.

Datas: no começo da linha (modo tolerante) ou em QUALQUER posição (modo estrito, que evita
falsos positivos como "1/2" ou "até 15/09" dentro de um texto). Aceita 10/08, 10/08/2026,
10-08-2026, 10.08.2026, 2026-08-10, 10 de agosto, 10 ago, agosto 10, Aug 10, intervalos
("07/09 a 09/09", "21 a 23 de abril") e, em listas por mês, linhas como "10 - Aula 1".
"""
from __future__ import annotations
import re
from typing import NamedTuple, Optional

from modelos.horario import Horario

# ------------------------------------------------------------------ meses
MESES = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_COMPLETOS = sorted(MESES, key=len, reverse=True)
MESES.update({"jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "mai": 5, "jun": 6,
              "jul": 7, "ago": 8, "aug": 8, "set": 9, "sep": 9, "sept": 9, "out": 10,
              "oct": 10, "nov": 11, "dez": 12, "dec": 12})
_MES_ALT = "|".join(sorted(MESES, key=len, reverse=True))
_MES_COMPLETO = "|".join(_COMPLETOS)
_MES_PRIMEIRO = "|".join(_COMPLETOS + ["jan", "feb", "apr", "aug", "sept", "sep", "oct", "dec", "jun", "jul", "nov", "fev", "abr", "ago", "dez"])


def _alternativas(leniente: bool) -> str:
    """Formas de escrever uma data. Grupos: d1..d6 (dia), m1..m6 (mês), y1..y6 (ano)."""
    dash = (r"(?P<d5>\d{2})-(?P<m5>\d{2})(?:-(?P<y5>\d{4}))?" if leniente
            else r"(?P<d5>\d{1,2})-(?P<m5>\d{1,2})-(?P<y5>\d{4})")
    return "(?:" + "|".join([
        r"(?P<y1>\d{4})\s*[-/]\s*(?P<m1>\d{1,2})\s*[-/]\s*(?P<d1>\d{1,2})(?!\d)",              # 2026-08-10
        r"(?P<d2>\d{1,2})\s*/\s*(?P<m2>\d{1,2})(?:\s*/\s*(?P<y2>\d{4}|\d{2})(?!\d))?",         # 10/08[/2026]
        dash,                                                                                    # 10-08[-2026]
        r"(?P<d4>\d{1,2})\.(?P<m4>\d{1,2})\.(?P<y4>\d{4})",                                     # 10.08.2026
        r"(?P<d3>\d{1,2})(?:[º°]?\s*(?:de\s+)?|[º°]?[/\-]\s*)(?P<m3>" + _MES_ALT + r")\b\.?"  # 10 de agosto
        r"(?:\s*(?:de\s+|[/\-,]\s*)?(?P<y3>\d{4}))?",
        r"(?P<m6>" + _MES_PRIMEIRO + r")\b\.?\s*,?\s*(?P<d6>\d{1,2})(?:º|st|nd|rd|th)?(?!\d)"  # agosto 10
        r"(?:\s*,?\s*(?P<y6>\d{4}))?",
    ]) + ")"


# início de um intervalo "21 a 23/04" ou "21-23 de abril"
_DR = (r"(?:(?P<dr>\d{1,2})(?:\s+(?:a|à|até|ate)\s+|[-–])"
       r"(?=\d{1,2}\s*/\s*\d|\d{1,2}[º°]?\s*(?:de\s+)?(?:" + _MES_ALT + r")\b))?")

_SEMANA = (r"(?:segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo|"
           r"seg|ter|qua|qui|sex|s[áa]b|dom)\w*(?:-feira)?")
_PREFIXO = (r"^\s*[•*\-–]*\s*"
            r"(?:(?:semana|sem\.?)\s*)?"
            r"(?:\d{1,2}(?:\s*[ªº°.):\-–|;,]+\s*|\s+))?"
            r"(?:" + _SEMANA + r"[\s,.\-–|;:]*)?")

_REGEX_INICIO = re.compile(_PREFIXO + _DR + _alternativas(True), re.I)
_REGEX_MEIO = re.compile(r"(?<![\w/.:])" + _DR + _alternativas(False) + r"(?![\d/])", re.I)
_REGEX_FIM = re.compile(r"(?:\s+(?:a|à|até|ate)\s+|\s*[-–—]\s*)" + _alternativas(False) + r"(?![\d/])", re.I)
# palavras que indicam que a data é só uma referência dentro do texto ("até 15/09")
_REFERENCIA = re.compile(r"\b(?:at[ée]|para|desde|ap[óo]s|antes|entre|prazo|conforme|previsto)\s*"
                         r"(?:o\s+dia\s+|dia\s+|em\s+)?$", re.I)
_MES_CAB = re.compile(r"^\W*(?P<m>" + _MES_COMPLETO + r")\b\W*(?:de\W*)?(?P<y>\d{4})?\W*$", re.I)
_DIA_SOLTO = re.compile(r"^(?:dia\s+)?(?P<d>\d{1,2})\s*(?:[-–:|)]\s*|\s+(?=[A-Za-zÀ-ÿ]))(?P<r>\S.*)$", re.I)


class AchadoData(NamedTuple):
    dia: int
    mes: int
    ano: Optional[int]
    resto: str                                  # texto da linha sem a(s) data(s)
    inicio_da_linha: bool                       # a data estava no começo da linha?
    fim: Optional[tuple] = None                 # (dia, mes, ano|None) se for um intervalo


def _limpar(s: str, sobras: bool = False) -> str:
    s = re.sub(r"\s*\|\s*", " ", s)
    s = re.sub(r"\(\s*\)|\[\s*\]", " ", s)
    s = re.sub(r"^[\s\-–—:|;,.)\]]+", "", s)
    s = re.sub(r"[\s\-–—:|;,(\[]+$", "", s)
    if sobras:                                  # "Seminário 1 - dia" -> "Seminário 1"
        s = re.sub(r"(?:\s+(?:dia|em|no|na|de|do|da|at[ée]|às|as))+$", "", s, flags=re.I)
        s = re.sub(r"[\s\-–—:|;,(\[]+$", "", s)
    return " ".join(s.split())


def _decodificar(m: re.Match, estrito: bool):
    g = m.groupdict()
    for k in "123456":
        d = g.get("d" + k)
        if not d:
            continue
        mes_txt, ano = g["m" + k], g.get("y" + k)
        mes = MESES[mes_txt.lower()] if k in "36" else int(mes_txt)
        dia = int(d)
        if k == "2" and estrito and not ano and len(d) == 1 and len(mes_txt) == 1:
            return None                          # "1/2" parece fração, não data
        if ano:
            ano = int(ano) + (2000 if int(ano) < 100 else 0)
            if not 1990 <= ano <= 2100:
                return None
        if not (1 <= dia <= 31 and 1 <= mes <= 12):
            return None
        dr = int(g["dr"]) if g.get("dr") else None
        if dr is not None and not 1 <= dr < dia:
            return None
        return dia, mes, ano or None, dr
    return None


def _montar(linha: str, m: re.Match, dec, inicio: bool) -> AchadoData:
    dia, mes, ano, dr = dec
    fim, fim_pos = None, m.end()
    if dr:                                       # "21 a 23/04": começa em dr, termina em dia
        ini, fim = (dr, mes, ano), (dia, mes, ano)
    else:
        ini = (dia, mes, ano)
        fm = _REGEX_FIM.match(linha, m.end())    # "07/09 a 09/09"
        if fm:
            d2 = _decodificar(fm, True)
            if d2 and d2[3] is None:
                fim, fim_pos = d2[:3], fm.end()
    antes, depois = linha[:m.start()], linha[fim_pos:]
    resto = _limpar(depois) if inicio else _limpar(antes + " " + depois, sobras=True)
    return AchadoData(ini[0], ini[1], ini[2], resto, inicio, fim)


def achar_data(linha: str, permitir_meio: bool = False) -> Optional[AchadoData]:
    """Procura a data da linha. Com permitir_meio=True aceita a data em qualquer posição."""
    linha = linha.strip()
    m = _REGEX_INICIO.match(linha)
    if m:
        dec = _decodificar(m, False)
        if dec:
            return _montar(linha, m, dec, True)
    if permitir_meio:
        for m in _REGEX_MEIO.finditer(linha):
            dec = _decodificar(m, True)
            if dec and not _REFERENCIA.search(linha[:m.start()]):
                return _montar(linha, m, dec, False)
    return None


_PREPOSICAO_ANTES = re.compile(r"\b(?:de|e|a|à|ao|às|até|para|em|dia|do|da|no|na|desde|após|antes|entre|conforme|prazo|ou)\s*$")


def dividir_em_partes(linha: str) -> list[str]:
    """Tabela em duas partes na mesma linha: '11/8 A 20/10 B' -> ['11/8 A', '20/10 B'].
    Datas apenas citadas no texto ('até 15/09', 'prova de 15/09 e 22/09') não dividem a linha."""
    linha = linha.strip()
    primeira = _REGEX_INICIO.match(linha)
    if not primeira:
        return [linha]
    cortes = []
    for m in _REGEX_MEIO.finditer(linha, primeira.end()):
        antes, depois = linha[:m.start()], linha[m.end():]
        d = _decodificar(m, False)
        parece_fracao = (d and m.group(0).count("/") == 1 and len(m.group(0).replace(" ", "")) <= 3
                         and depois.strip()[:1].islower())                  # "1/2 do conteúdo"
        if d and depois.strip() and not parece_fracao and not _PREPOSICAO_ANTES.search(antes.rstrip()) \
                and not _REFERENCIA.search(antes):
            cortes.append(m.start())
    pontos = [0] + cortes + [len(linha)]
    return [linha[a:b].strip() for a, b in zip(pontos, pontos[1:])]


def contem_data(linha: str) -> bool:
    """Há alguma data na linha (em qualquer posição)?"""
    return achar_data(linha, permitir_meio=True) is not None


def tem_data_no_inicio(linha: str) -> bool:
    return achar_data(linha) is not None


def achar_mes_cabecalho(linha: str) -> Optional[tuple[int, Optional[int]]]:
    """'AGOSTO 2026', 'Setembro' (linha só com o mês) -> (mês, ano|None)."""
    m = _MES_CAB.match(linha.strip())
    return (MESES[m.group("m").lower()], int(m.group("y")) if m.group("y") else None) if m else None


def achar_dia_solto(linha: str) -> Optional[tuple[int, str]]:
    """'10 - Aula 1' / 'Dia 10: Aula' (usado dentro de uma lista organizada por mês)."""
    m = _DIA_SOLTO.match(linha.strip())
    if m and 1 <= int(m.group("d")) <= 31 and not re.match(r"de\b", m.group("r"), re.I):
        return int(m.group("d")), m.group("r").strip()
    return None


def inferir_ano(linhas: list[str]) -> Optional[int]:
    """Procura um ano (20xx) nas primeiras linhas do documento."""
    for linha in linhas[:20]:
        m = re.search(r"\b(20\d{2})\b", linha)
        if m:
            return int(m.group(1))
    return None


# ------------------------------------------------------------------ horários
_M1 = r"(?::(?P<m1>\d{2})|\s*h(?![a-zà-ÿ])\s*(?P<m1b>\d{2})?)"
_M2 = r"(?::(?P<m2>\d{2})|\s*h(?![a-zà-ÿ])\s*(?P<m2b>\d{2})?)?"
_R_INTERVALO = re.compile(r"(?<![\d:/.])(?P<h1>\d{1,2})" + _M1 +                      # 13:00 às 15:00 | 13h-15h
                          r"\s*(?:às|as|até|ate|à|a|[-–—/])\s*(?P<h2>\d{1,2})" + _M2 +
                          r"(?:\s*horas?\b)?(?![\d:/])", re.I)
_R_DAS = re.compile(r"\bdas\s+(?P<h1>\d{1,2})(?:(?::|\s*h(?![a-zà-ÿ]))\s*(?P<m1>\d{2})?)?\s*(?:às|as)\s*"  # das 8 às 10
                    r"(?P<h2>\d{1,2})(?:(?::|\s*h(?![a-zà-ÿ]))\s*(?P<m2>\d{2})?)?(?:\s*horas?\b)?(?![\d:/])", re.I)
_R_UNICO = re.compile(r"(?<![\d:/.])(?P<h>\d{1,2})(?::(?P<m>\d{2})|\s*h(?![a-zà-ÿ])\s*(?P<mb>\d{2})?)"
                      r"(?![\d:/])", re.I)                                              # 14h | 14:30 | 14h30
_ANTES_DO_HORARIO = re.compile(r"\b(?:a\s+partir\s+d[ae]s?|às|as|das|de|em|hor[áa]rio\s*:?)\s*$", re.I)


class AchadoHorario(NamedTuple):
    horario: Optional[Horario]
    resto: str          # texto sem o horário
    explicito: bool     # True = intervalo escrito ("13h às 15h"); False = só um horário ("14h")


def _minutos(h, m) -> Optional[int]:
    h, m = int(h), int(m or 0)
    return h * 60 + m if h < 24 and m < 60 else None


def achar_horario(texto: str, duracao_min: int = 60) -> AchadoHorario:
    """Extrai '13h às 15h', 'das 8 às 10', '8:30-10:00' ou um horário simples ('14h')."""
    for rx in (_R_INTERVALO, _R_DAS):
        m = rx.search(texto)
        if not m:
            continue
        g = m.groupdict()
        ini = _minutos(g["h1"], g.get("m1") or g.get("m1b"))
        fim = _minutos(g["h2"], g.get("m2") or g.get("m2b"))
        if ini is not None and fim is not None and fim > ini:
            return AchadoHorario(Horario.de_minutos(ini, fim), _sem_trecho(texto, m), True)
    m = _R_UNICO.search(texto)
    if m:
        ini = _minutos(m.group("h"), m.group("m") or m.group("mb"))
        if ini is not None and ini + duracao_min < 24 * 60:
            return AchadoHorario(Horario.de_minutos(ini, ini + duracao_min), _sem_trecho(texto, m), False)
    return AchadoHorario(None, texto, False)


def _sem_trecho(texto: str, m: re.Match) -> str:
    antes = _ANTES_DO_HORARIO.sub("", texto[:m.start()])
    return _limpar(antes + " " + texto[m.end():], sobras=True)
