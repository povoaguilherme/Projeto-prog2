from __future__ import annotations
import calendar
import re
from datetime import date, timedelta
from modelos.evento import (Evento, Aula, AulaCancelada, Feriado, Prova, Seminario,
                            EstudoDirigido, SegundaChamada, Trabalho, InicioPeriodo,
                            FimPeriodo, OutroEvento)
from modelos.horario import ajustar_a_janela
from padroes import (achar_data, achar_dia_solto, achar_horario, achar_mes_cabecalho, dividir_em_partes)

# A ordem importa: a primeira regra que bater vence.
REGRAS = [(re.compile(p, re.I), c) for p, c in [
    (r"^(?!\s*aula\b)(?=.*\bferiado\b)", Feriado),               # "Sem aula (feriado em ...)" é feriado
    (r"n[ãa]o\s+(?:houve|haver[áa]|ter[áa])\s+aula|sem\s+aula|aula\s+(?:cancelada|suspensa)"
     r"|suspens[ãa]o\s+(?:das\s+)?aulas", AulaCancelada),
    (r"^\s*aula\b", Aula),
    (r"feriado|recesso|ponto\s+facultativo|\bsem\s+expediente", Feriado),
    (r"2\s*[ªa]\s*chamada|segunda\s+chamada|reposi[çc][ãa]o", SegundaChamada),
    (r"fim\s+d[oa]s?\s+(?:per[ií]odo|semestre|aulas)|encerramento\s+d[oa]s?\s+(?:per[ií]odo|semestre|aulas)"
     r"|[úu]ltimo\s+dia\s+(?:letivo|de\s+aula)", FimPeriodo),
    (r"in[ií]cio\s+d[oa]s?\s+(?:per[ií]odo|semestre|aulas)|primeiro\s+dia\s+(?:letivo|de\s+aula)",
     InicioPeriodo),
    (r"semin[áa]rio|apresenta\S{1,3}o\s+final", Seminario),
    (r"estudo\s+dirigido|\bED\s*\d", EstudoDirigido),
    (r"\bprova\b|\bP\d\b|\bAV\d\b|exame|\bavalia[çc][ãa]o\b|\bteste\b", Prova),
    (r"\btrabalhos?\b|\bentregas?\b", Trabalho),
]]
# Onde o cronograma acaba (critérios de avaliação, bibliografia...)
MARCADOR_FIM = re.compile(
    r"PROCESSO\s+DE\s+AVALIA|CRIT[ÉE]RIOS?\s+DE\s+(?:APROVA|AVALIA)|BIBLIOGRAFIA|"
    r"REFER[ÊE]NCIAS\s+BIBLIOGR", re.I)
MAX_DIAS_INTERVALO = 45


class InterpretadorCronograma:
    def __init__(self, ano: int, duracao_padrao_min: int = 60) -> None:
        self.ano = ano
        self.duracao_padrao_min = duracao_padrao_min   # duração de um horário sem fim ("14h")
        self.avisos: list[str] = []
        self._livres = 0                                # eventos de descrição livre (tratados como aula)

    # ------------------------------------------------------------ leitura das linhas
    def _cortar_no_fim(self, linha: str, tem_blocos: bool, modo_meio: bool) -> tuple[str, bool]:
        if MARCADOR_FIM.search(linha):
            cabeca = MARCADOR_FIM.split(linha)[0]            # PDFs colam "…letivoPROCESSO DE…"
            if tem_blocos or achar_data(cabeca.strip(), modo_meio):
                return cabeca, True
        return linha, False

    def _modo_meio(self, linhas: list[str]) -> bool:
        """O documento coloca a data no meio/fim das linhas (em vez de no começo)?"""
        n_ini = n_meio = 0
        for linha in linhas:
            linha, fim = self._cortar_no_fim(linha, bool(n_ini or n_meio), True)
            a = achar_data(linha, permitir_meio=True)
            if a:
                n_ini += a.inicio_da_linha
                n_meio += not a.inicio_da_linha
            if fim:
                break
        return (n_ini == 0 and n_meio >= 1) or (n_meio >= 3 and n_meio >= 0.5 * n_ini)

    def _modo_partes(self, linhas: list[str]) -> bool:
        """A tabela do documento vem 'dividida em duas partes' (duas datas na mesma linha)?"""
        com_data = [l for l in linhas if achar_data(l)]
        divididas = [l for l in com_data if len(dividir_em_partes(l)) > 1]
        return len(divididas) >= 3 and len(divididas) >= 0.4 * len(com_data)

    @staticmethod
    def _ler_partes_em_ordem(linhas: list[str]) -> list[str]:
        """Separa as partes de cada linha e devolve a parte 1 inteira, depois a parte 2... (datas em ordem)."""
        partes: list[list[str]] = [[]]
        ultima = 0
        for linha in linhas:
            pedacos = dividir_em_partes(linha)
            if len(pedacos) == 1 and not achar_data(linha):
                partes[ultima].append(linha)                 # continuação de uma célula
                continue
            for k, pedaco in enumerate(pedacos):
                while len(partes) <= k:
                    partes.append([])
                partes[k].append(pedaco)
            ultima = len(pedacos) - 1
        return [l for parte in partes for l in parte]

    def interpretar(self, linhas: list[str]) -> list[Evento]:
        self.avisos, self._livres = [], 0
        self._ano, self._ultimo_mes = self.ano, None
        if self._modo_partes(linhas):
            linhas = self._ler_partes_em_ordem(linhas)
        modo_meio = self._modo_meio(linhas)
        blocos: list[list] = []                    # [data | None, texto, data_fim | None]
        contexto = None                            # (mês, ano) de um cabeçalho "AGOSTO 2026"
        for linha in linhas:
            linha, fim_doc = self._cortar_no_fim(linha, bool(blocos), modo_meio)
            linha = linha.strip()
            achado = achar_data(linha, permitir_meio=modo_meio)
            cab = None if achado else achar_mes_cabecalho(linha)
            solto = achar_dia_solto(linha) if (contexto and not achado and not cab) else None
            if achado:
                self._abrir(blocos, achado.dia, achado.mes, achado.ano, achado.resto, achado.fim)
            elif cab:
                contexto = cab
            elif solto and solto[0] <= calendar.monthrange(self._ano_do_mes(contexto), contexto[0])[1]:
                self._abrir(blocos, solto[0], contexto[0], contexto[1], solto[1], None)
            elif linha and blocos:                 # continuação da descrição anterior
                blocos[-1][1] += " " + linha
            if fim_doc:
                break
        eventos: list[Evento] = []
        for data, texto, data_fim in blocos:
            if data:
                eventos += self._criar(data, texto.strip(), data_fim)
        if self._livres:
            self.avisos.append(f"{self._livres} evento(s) com descrição livre (sem palavra como prova, feriado ou "
                               "seminário) foram tratados como aula.")
        return eventos

    def _ano_do_mes(self, contexto) -> int:
        return contexto[1] or self._ano

    def _abrir(self, blocos, dia, mes, ano_explicito, resto, fim) -> None:
        if ano_explicito is None:
            if self._ultimo_mes is not None and self._ultimo_mes - mes >= 6:
                self._ano += 1                     # semestre que vira o ano (dez → jan)
            self._ultimo_mes = mes
        ano = ano_explicito or self._ano
        try:
            data = date(ano, mes, dia)
        except ValueError:
            self.avisos.append(f"Data inválida ignorada: {dia:02d}/{mes:02d}")
            blocos.append([None, resto, None])
            return
        data_fim = None
        if fim:
            fdia, fmes, fano = fim
            fa = fano or (ano if (fmes, fdia) >= (mes, dia) else ano + 1)
            try:
                data_fim = date(fa, fmes, fdia)
            except ValueError:
                data_fim = None
        blocos.append([data, resto, data_fim])

    # ------------------------------------------------------------ criação dos eventos
    def _criar(self, data: date, texto: str, data_fim: date | None = None) -> list[Evento]:
        horario, origem = None, ""
        achado = achar_horario(texto, self.duracao_padrao_min)
        if achado.horario:
            ajustado, aviso = ajustar_a_janela(achado.horario)
            plausivel = achado.explicito or 6 <= achado.horario.inicio.hour <= 22
            if ajustado or plausivel:              # parece mesmo um horário (e não "aula de 2h")
                horario, origem, texto = ajustado, ("texto" if ajustado else ""), achado.resto
                if aviso:
                    self.avisos.append(f"{data:%d/%m}: {aviso}")
        if not texto:
            return [OutroEvento(data, "(sem descrição)", horario, origem)]
        classe = next((c for p, c in REGRAS if p.search(texto)), None)
        if classe is None:
            self._livres += 1
            classe = Aula
        if (data_fim and data_fim > data and classe in (Feriado, AulaCancelada)
                and (data_fim - data).days <= MAX_DIAS_INTERVALO):
            eventos = [classe(data + timedelta(days=i), texto) for i in range((data_fim - data).days + 1)]
            for e in eventos:
                e.segue_horario = False            # recesso de vários dias não segue o dia da semana
            return eventos
        return [classe(data, texto, horario, origem)]
