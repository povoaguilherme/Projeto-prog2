"""Camada de serviço: une leitura, interpretação, frequência, notas e banco de dados.
Usada pela linha de comando e pela interface gráfica."""
from __future__ import annotations
from datetime import date
from typing import Callable, Optional
from pathlib import Path
from exportacao.ics import ExportadorICS
from extrator_notas import extrair_frequencia_minima, extrair_itens, extrair_media_minima
from interpretador import InterpretadorCronograma
from leitores import criar_leitor
from modelos.agenda_geral import AgendaGeral
from modelos.agendador import AgendadorHorarios
from modelos.disciplina import Disciplina
from modelos.evento import (DIAS, AulaCancelada, Evento, FimPeriodo, Feriado, InicioPeriodo,
                            classe_por_rotulo)
from modelos.frequencia import ResumoFrequencia
from modelos.horario import HORA_FIM_DIA, HORA_INICIO_DIA, Horario, ajustar_a_janela
from modelos.notas import AnaliseNotas
from padroes import inferir_ano
from repositorio import Repositorio
from texto import chave_alfabetica, chave_de_comparacao


class ServicoCalendario:
    def __init__(self, repositorio: Repositorio | None = None) -> None:
        self.repositorio = repositorio                  # None = tudo só em memória
        self.disciplinas: dict[str, Disciplina] = {}    # todas as matérias abertas
        self.disciplina: Disciplina | None = None       # a matéria selecionada agora
        self.linhas: list[str] = []
        self.ano: int | None = None
        self.nome_leitor = ""
        self._avisos_leitura: dict[str, list[str]] = {}

    # ------------------------------------------------------------ matérias
    def nomes(self) -> list[str]:
        return sorted(self.disciplinas, key=chave_alfabetica)

    def selecionar(self, nome: str) -> Disciplina:
        if nome not in self.disciplinas:
            raise ValueError(f"Matéria '{nome}' não encontrada")
        self.disciplina = self.disciplinas[nome]
        return self.disciplina

    def _exigir(self) -> Disciplina:
        if not self.disciplina:
            raise ValueError("Nenhuma matéria carregada.")
        return self.disciplina

    def _salvar(self, disciplina: Disciplina | None = None) -> None:
        alvo = disciplina or self.disciplina
        if self.repositorio and alvo:
            self.repositorio.salvar(alvo)

    def agenda_geral(self) -> AgendaGeral:
        """Visão de TODAS as matérias abertas juntas."""
        return AgendaGeral(self.disciplinas.values())

    def dono_de(self, evento: Evento) -> Disciplina:
        """Descobre a que matéria pertence um evento."""
        for d in self.disciplinas.values():
            if any(e is evento for e in d.calendario.eventos_do_dia(evento.data)):
                return d
        raise ValueError("Esse evento não pertence a nenhuma matéria aberta")

    @property
    def avisos(self) -> list[str]:
        """Avisos da leitura + verificações sempre atualizadas (dia da semana, sobreposição)."""
        if not self.disciplina:
            return []
        atual = self.disciplina
        conflitos = [AgendaGeral.descrever_conflito(par) for par in self.agenda_geral().conflitos()
                     if any(d is atual for d in (par[0][0], par[1][0]))]
        return self._avisos_leitura.get(atual.nome, []) + self._validar(atual) + conflitos

    # ------------------------------------------------------------ carregar
    def carregar(self, caminho: str, ano: int | None = None, nome: str | None = None,
                 perguntar_nome: Optional[Callable[[str], Optional[str]]] = None) -> Disciplina:
        """Lê o cronograma e cria (ou atualiza) a matéria. Se o documento não diz o nome da matéria, usa `nome`;
        sem `nome`, chama `perguntar_nome(sugestão)` (a interface abre uma caixa de diálogo) e, por fim, o nome do arquivo."""
        leitor = criar_leitor(caminho)
        linhas = leitor.ler(caminho)
        ano = ano or inferir_ano(linhas) or date.today().year

        disciplina = Disciplina.do_cabecalho(linhas)
        nome_do_documento = disciplina.nome != "—"
        padrao = disciplina.faixa_horario()
        interpretador = InterpretadorCronograma(ano, padrao.duracao_min if padrao else 60)
        eventos = interpretador.interpretar(linhas)
        if not eventos:
            self.linhas = linhas
            raise ValueError(
                f"Li o arquivo ({type(getattr(leitor, 'leitor_usado', leitor)).__name__}, {len(linhas)} "
                "linhas), mas não encontrei datas (ex.: 10/08, 10 de agosto, 2026-08-10, 'agosto' "
                "seguido de '10 - Aula'). Use --mostrar-texto para ver o que foi extraído.")
        if nome and nome.strip():
            disciplina.nome = nome.strip()
        elif not nome_do_documento:
            sugestao = Path(caminho).stem
            escolhido = (perguntar_nome(sugestao) if perguntar_nome else None) or ""
            disciplina.nome = escolhido.strip() or sugestao
        disciplina.calendario.adicionar_varios(eventos)
        avisos = (interpretador.avisos + self._aplicar_horario_padrao(disciplina)
                  + list(getattr(leitor, "avisos", [])))

        salva = self.repositorio.carregar(disciplina.nome) if self.repositorio else None
        if salva:
            self._restaurar_estado(disciplina, salva)
        else:
            avisos += self._estado_do_documento(disciplina, linhas)

        self.linhas, self.ano = linhas, ano
        self.nome_leitor = type(getattr(leitor, "leitor_usado", leitor)).__name__
        self.disciplinas[disciplina.nome] = disciplina
        self.disciplina = disciplina
        self._avisos_leitura[disciplina.nome] = avisos
        self._salvar()
        return disciplina

    def carregar_do_banco(self, nome: str | None = None) -> list[str]:
        """Reabre matérias já guardadas (sem precisar do arquivo do cronograma)."""
        if not self.repositorio:
            raise ValueError("Nenhum banco de dados configurado.")
        carregadas = []
        for n in ([nome] if nome else self.repositorio.listar()):
            d = self.repositorio.carregar(n)
            if d:
                self.disciplinas[n] = d
                carregadas.append(n)
        if carregadas:
            self.disciplina = self.disciplinas[carregadas[0]]
            self.ano = self.disciplina.calendario.intervalo()[0].year
        return carregadas

    @staticmethod
    def _importar_avaliacoes(d: Disciplina, peso=1) -> list[str]:
        """Cria na aba Notas as avaliações marcadas no calendário que ainda não são itens. Devolve os nomes criados."""
        existentes = {chave_de_comparacao(i.nome) for i in d.notas.itens}
        novos = []
        for nome, _ in d.avaliacoes_do_calendario():
            if chave_de_comparacao(nome) not in existentes:
                d.notas.adicionar_item(nome, peso)
                novos.append(nome)
        return novos

    def importar_avaliacoes_do_calendario(self, peso=1) -> list[str]:
        """Botão/opção 'importar avaliações do calendário'. Devolve os nomes das avaliações novas."""
        novos = self._importar_avaliacoes(self._exigir(), peso)
        if novos:
            self._salvar()
        return novos

    def renomear_materia(self, antigo: str, novo: str) -> None:
        novo = novo.strip()
        if not novo:
            raise ValueError("Escolha um nome para a matéria")
        if antigo not in self.disciplinas:
            raise ValueError(f"Matéria '{antigo}' não encontrada")
        if novo != antigo and novo in self.disciplinas:
            raise ValueError(f"Já existe uma matéria chamada '{novo}'")
        d = self.disciplinas.pop(antigo)
        d.nome = novo
        self.disciplinas[novo] = d
        self._avisos_leitura[novo] = self._avisos_leitura.pop(antigo, [])
        if self.repositorio:
            self.repositorio.excluir(antigo)
            self.repositorio.salvar(d)

    @staticmethod
    def _estado_do_documento(d: Disciplina, linhas: list[str]) -> list[str]:
        """Primeira vez que a matéria aparece: pesos, média e frequência vêm do próprio cronograma."""
        media = extrair_media_minima(linhas)
        if media is not None:
            d.notas.definir_media_minima(media)
        freq = extrair_frequencia_minima(linhas)
        if freq is not None:
            d.frequencia.minima = freq
        for nome, peso in extrair_itens(linhas):
            try:
                d.notas.adicionar_item(nome, peso)
            except ValueError:
                pass                                     # nome repetido no documento: ignora
        if d.notas.itens:
            return []
        novos = ServicoCalendario._importar_avaliacoes(d)    # sem fórmula no documento: usa o que está no calendário
        return ([f"Os pesos das avaliações não estão no cronograma: usei peso 1 para {', '.join(novos)}. "
                 "Ajuste os pesos na aba Notas."] if novos else [])

    @staticmethod
    def _restaurar_estado(nova: Disciplina, salva: Disciplina) -> None:
        """Matéria já conhecida: presenças, notas e horários manuais do banco têm prioridade."""
        nova.frequencia, nova.notas = salva.frequencia, salva.notas
        nova.removidos = set(salva.removidos)
        for e in list(nova.calendario.todos()):              # o que o usuário apagou/editou não volta
            if e.chave in nova.removidos:
                nova.calendario.remover(e)
        for e in salva.calendario.todos():                    # o que o usuário criou à mão é mantido
            if e.manual:
                nova.calendario.adicionar(e)
        horarios = {e.chave: e for e in salva.calendario.todos() if e.origem_horario == "manual" and not e.manual}
        for e in nova.calendario.todos():
            if not e.manual and e.chave in horarios:
                e.horario, e.origem_horario = horarios[e.chave].horario, "manual"

    @staticmethod
    def _aplicar_horario_padrao(disciplina: Disciplina) -> list[str]:
        """Aulas e avaliações sem hora própria recebem o horário da disciplina (se couber em 8h–17h)."""
        faixa = disciplina.faixa_horario()
        if not faixa:
            return []
        ajustado, aviso = ajustar_a_janela(faixa)
        if not ajustado:
            return [f"Horário padrão da disciplina {aviso}; não foi aplicado às aulas"]
        for e in disciplina.calendario.todos():
            if e.ocupa_horario and e.horario is None:
                e.horario, e.origem_horario = ajustado, "padrao"
        return [f"Horário padrão da disciplina {aviso}"] if aviso else []

    def _validar(self, disciplina: Disciplina) -> list[str]:
        cal, avisos = disciplina.calendario, []
        pred = cal.dia_semana_predominante()
        for e in cal.fora_do_padrao():
            avisos.append(f"{e.data:%d/%m} cai em {DIAS[e.data.weekday()]}, "
                          f"mas a disciplina costuma ser em {DIAS[pred]}")
        for a, b in cal.sobreposicoes():
            avisos.append(f"{a.data:%d/%m}: {a.titulo()} ({a.horario}) e {b.titulo()} ({b.horario}) se sobrepõem")
        for d in cal.datas_com_conflito():
            if any(e.horario is None for e in cal.eventos_do_dia(d)):
                avisos.append(f"Mais de um evento em {d:%d/%m}")
        return avisos

    # ------------------------------------------------------------ consultas
    def eventos_do_dia(self, dia: date) -> list[Evento]:
        return self.disciplina.calendario.eventos_do_dia(dia) if self.disciplina else []

    def todos(self) -> list[Evento]:
        return self.disciplina.calendario.todos() if self.disciplina else []

    # ------------------------------------------------------------ frequência
    def eventos_de_frequencia(self) -> list[Evento]:
        return self._exigir().eventos_de_frequencia()

    def marcar_presenca(self, evento: Evento, status) -> None:
        self._exigir().frequencia.marcar(evento, status)
        self._salvar()

    def limpar_presenca(self, evento: Evento) -> None:
        self._exigir().frequencia.limpar(evento)
        self._salvar()

    def marcar_presenca_em(self, dia: date, status) -> int:
        """Marca presença/falta em todas as aulas daquele dia. Devolve quantas foram marcadas."""
        alvo = [e for e in self.eventos_do_dia(dia) if e.conta_frequencia]
        if not alvo:
            raise ValueError(f"Não há aula em {dia:%d/%m} (feriado, sem aula ou data fora do calendário)")
        for e in alvo:
            self._exigir().frequencia.marcar(e, status)
        self._salvar()
        return len(alvo)

    def resumo_frequencia(self) -> ResumoFrequencia:
        return self._exigir().resumo_frequencia()

    def definir_frequencia_minima(self, percentual) -> None:
        valor = float(str(percentual).replace(",", "."))
        if not 0 < valor <= 100:
            raise ValueError("A frequência mínima deve estar entre 0 e 100%")
        self._exigir().frequencia.minima = valor
        self._salvar()

    # ------------------------------------------------------------ notas
    def adicionar_item_nota(self, nome: str, peso, nota=None) -> None:
        self._exigir().notas.adicionar_item(nome, peso, nota)
        self._salvar()

    def remover_item_nota(self, nome: str) -> None:
        self._exigir().notas.remover_item(nome)
        self._salvar()

    def definir_nota(self, nome: str, nota) -> None:
        self._exigir().notas.definir_nota(nome, nota)
        self._salvar()

    def definir_media_minima(self, media) -> None:
        self._exigir().notas.definir_media_minima(media)
        self._salvar()

    def analise_notas(self) -> AnaliseNotas:
        return self._exigir().analise_notas()

    # ------------------------------------------------------------ edição manual do calendário
    @staticmethod
    def _montar_evento(disciplina: Disciplina, tipo, data, texto: str, inicio: str, fim: str,
                       padrao_se_vazio: bool) -> Evento:
        """Valida os dados digitados e cria o evento (nada é alterado se algo estiver errado)."""
        classe = tipo if isinstance(tipo, type) else classe_por_rotulo(tipo)
        if not isinstance(data, date):
            raise ValueError("Informe a data (dia/mês/ano)")
        texto = (texto or "").strip()
        if not texto:
            padroes = {Feriado: "FERIADO", AulaCancelada: "Não houve aula",
                       InicioPeriodo: "Início do período letivo", FimPeriodo: "Fim do período letivo"}
            if classe not in padroes:
                raise ValueError("Escreva uma descrição para o evento")
            texto = padroes[classe]
        horario, origem = None, ""
        if (inicio or "").strip() or (fim or "").strip():
            horario = Horario.de_texto(inicio, fim)
            if not horario.dentro_da_janela():
                raise ValueError(f"Use horários entre {HORA_INICIO_DIA:02d}:00 e {HORA_FIM_DIA:02d}:00 (recebi {horario}).")
            origem = "manual"
        elif padrao_se_vazio and classe.ocupa_horario:
            faixa = disciplina.faixa_horario()
            if faixa and faixa.dentro_da_janela():
                horario, origem = faixa, "padrao"
        return classe(data, texto, horario, origem, True)

    def adicionar_evento(self, tipo, data: date, texto: str, inicio: str = "", fim: str = "",
                         materia: str | None = None) -> Evento:
        """Cria um evento à mão. Sem horário, aulas e avaliações usam o horário da matéria."""
        alvo = self.disciplinas.get(materia) if materia else self._exigir()
        if alvo is None:
            raise ValueError(f"Matéria '{materia}' não encontrada")
        evento = self._montar_evento(alvo, tipo, data, texto, inicio, fim, True)
        alvo.calendario.adicionar(evento)
        self._salvar(alvo)
        return evento

    def editar_evento(self, evento: Evento, tipo, data: date, texto: str, inicio: str = "", fim: str = "") -> Evento:
        """Substitui um evento por uma versão editada (a presença vai junto). Devolve o novo evento."""
        dono = self.dono_de(evento)
        novo = self._montar_evento(dono, tipo, data, texto, inicio, fim, False)
        dono.calendario.remover(evento)
        if not evento.manual:
            dono.removidos.add(evento.chave)                  # o original do cronograma não deve voltar
        dono.calendario.adicionar(novo)
        dono.frequencia.migrar(evento.chave, novo)
        self._salvar(dono)
        return novo

    def remover_evento(self, evento: Evento) -> None:
        dono = self.dono_de(evento)
        dono.calendario.remover(evento)
        if not evento.manual:
            dono.removidos.add(evento.chave)
        dono.frequencia.limpar(evento)
        self._salvar(dono)

    def conflitos_do_evento(self, evento: Evento) -> list[str]:
        """Avisos de sobreposição que envolvem este evento (com eventos da mesma ou de outras matérias)."""
        return [AgendaGeral.descrever_conflito(par) for par in self._conflitos_internos(evento)]

    def _conflitos_internos(self, evento: Evento) -> list:
        """Pares (da mesma matéria ou não) em que o evento aparece com horário sobreposto."""
        if not evento.horario:
            return []
        dono, pares = self.dono_de(evento), []
        for d in self.disciplinas.values():
            for outro in d.calendario.eventos_do_dia(evento.data):
                if outro is not evento and outro.horario and outro.horario.sobrepoe(evento.horario):
                    pares.append(((dono, evento), (d, outro)))
        return pares

    # ------------------------------------------------------------ horários (08:00 a 17:00)
    def atribuir_horario(self, evento: Evento, inicio: str, fim: str) -> list[str]:
        """Define o horário de um evento. Levanta ValueError se for inválido ou fora da janela."""
        h = Horario.de_texto(inicio, fim)
        if not h.dentro_da_janela():
            raise ValueError(f"Use horários entre {HORA_INICIO_DIA:02d}:00 e {HORA_FIM_DIA:02d}:00 (recebi {h}).")
        evento.horario, evento.origem_horario = h, "manual"
        self._salvar()
        return [f"{evento.data:%d/%m}: sobrepõe-se a {o.titulo()} ({o.horario})"
                for o in self.eventos_do_dia(evento.data)
                if o is not evento and o.horario and o.horario.sobrepoe(h)]

    def remover_horario(self, evento: Evento) -> None:
        evento.horario, evento.origem_horario = None, ""
        self._salvar()

    def atribuir_horarios_livres(self, duracao_min: int = 120) -> tuple[int, list[str]]:
        """Dá a cada aula/avaliação sem hora o primeiro horário livre do dia entre 08:00 e 17:00."""
        resultado = AgendadorHorarios(self._exigir().calendario, duracao_min).atribuir_pendentes()
        self._salvar()
        return resultado

    def exportar_ics(self, destino: str, todas: bool = False) -> str:
        """Exporta a matéria atual ou, com todas=True, todas as matérias em um só calendário."""
        alvo = list(self.disciplinas.values()) if todas else self._exigir()
        return ExportadorICS(alvo).salvar(destino)
