"""Interface gráfica (Tkinter): calendário mensal colorido + lista de eventos."""
from __future__ import annotations
import calendar
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from modelos.agenda_geral import AgendaGeral
from modelos.evento import (DIAS, TIPOS, TIPOS_EDITAVEIS, Aula, AulaCancelada, Avaliacao, EstudoDirigido, Evento,
                            Feriado, FimPeriodo, InicioPeriodo, Prova, SegundaChamada,
                            Seminario, Trabalho)
from modelos.frequencia import SituacaoFrequencia, StatusPresenca
from modelos.horario import HORA_FIM_DIA, HORA_INICIO_DIA, opcoes_de_horario
from modelos.notas import SituacaoNotas
from repositorio import RepositorioSQLite
from saida.exibidor import ExibidorAgenda, MESES
from saida.relatorio import RelatorioAcademico, fmt_nota, fmt_pct
from servico import ServicoCalendario

CORES = {Aula: "#c8e6c9", AulaCancelada: "#e0e0e0", Feriado: "#f8bbd0", Prova: "#ffcdd2",
         Seminario: "#bbdefb", EstudoDirigido: "#ffe0b2", SegundaChamada: "#e1bee7",
         Avaliacao: "#ffcdd2", Trabalho: "#fff9c4", InicioPeriodo: "#b0bec5",
         FimPeriodo: "#b0bec5"}
BRANCO, CINZA_FORA = "#ffffff", "#f2f2f2"
PALETA_MATERIAS = ["#bbdefb", "#c8e6c9", "#ffe0b2", "#e1bee7", "#ffcdd2", "#b2dfdb", "#fff9c4", "#d7ccc8",
                   "#f8bbd0", "#dcedc8"]
DIAS_LONGOS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
COLUNAS_UMA = ("data", "hora", "tipo", "desc")
COLUNAS_TODAS = ("data", "hora", "materia", "tipo", "desc")
DURACOES = {"1h": 60, "1h30": 90, "2h": 120, "3h": 180, "4h": 240}
FORMATOS = [("Cronogramas", "*.pdf *.docx *.xlsx *.odt *.ods *.pptx *.html *.htm *.csv *.txt *.rtf "
                            "*.json *.md *.png *.jpg *.jpeg *.doc *.xls"), ("Todos os arquivos", "*.*")]


def cor_do(evento: Evento) -> str:
    for classe in type(evento).__mro__:              # sobe na hierarquia até achar uma cor
        if classe in CORES:
            return CORES[classe]
    return BRANCO


class AplicativoCalendario(tk.Tk):
    def __init__(self, caminho: str | None = None, ano: int | None = None, banco: str | None = None) -> None:
        super().__init__()
        self.title("Calendário Acadêmico")
        self.geometry("1240x780")
        self.minsize(960, 560)
        self.repositorio = RepositorioSQLite(banco) if banco else None
        self.servico = ServicoCalendario(self.repositorio)
        self.protocol("WM_DELETE_WINDOW", self._fechar)
        self.dia_foco = date.today()                       # dia em torno do qual mês/semana/dia são desenhados
        self.var_ano = tk.StringVar(value=str(ano) if ano else "")
        self.var_status = tk.StringVar(value="Abra um cronograma para começar.")
        self.var_materia = tk.StringVar(value="")
        self.var_visao = tk.StringVar(value="mes")          # "mes", "semana" ou "dia"
        self.var_todas = tk.BooleanVar(value=False)         # ver todas as matérias juntas?
        self.f_materia, self.f_tipo, self.f_data = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.f_texto, self.f_ini, self.f_fim = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self._evento_em_edicao: Evento | None = None
        self.var_freq_min = tk.StringVar(value="75")
        self.var_media_min = tk.StringVar(value="5")
        self.var_nota = tk.StringVar(value="")
        self.var_item_nome, self.var_item_peso = tk.StringVar(value=""), tk.StringVar(value="")
        self._por_iid_freq: dict[str, object] = {}
        self._nome_por_iid: dict[str, str] = {}
        self._datas: list[date] = []
        self._celulas: list[tk.Label] = []
        self._por_iid: dict[str, Evento] = {}
        self._sincronizando = False
        self._montar_barra()
        self._montar_corpo()
        ttk.Label(self, textvariable=self.var_status, anchor="w", padding=4).pack(fill="x", side="bottom")
        self._atualizar_visao()
        if self.repositorio and self.servico.carregar_do_banco():
            self._exibir_disciplina()                       # reabre as matérias guardadas
        if caminho:
            self.after(100, lambda: self.abrir(caminho))

    def _fechar(self) -> None:
        if self.repositorio:
            self.repositorio.fechar()
        self.destroy()

    # ---------- montagem da tela ----------
    def _montar_barra(self) -> None:
        barra = ttk.Frame(self, padding=6)
        barra.pack(fill="x")
        ttk.Button(barra, text="Abrir cronograma…", command=self.abrir_dialogo).pack(side="left")
        ttk.Label(barra, text="   Matéria:").pack(side="left")
        self.cb_materia = ttk.Combobox(barra, textvariable=self.var_materia, values=[], width=26, state="readonly")
        self.cb_materia.pack(side="left")
        self.cb_materia.bind("<<ComboboxSelected>>", self._trocar_materia)
        ttk.Checkbutton(barra, text="Todas as matérias juntas", variable=self.var_todas,
                        command=self._alternar_todas).pack(side="left", padx=8)
        ttk.Label(barra, text="   Ano:").pack(side="left")
        ttk.Entry(barra, width=6, textvariable=self.var_ano).pack(side="left")
        ttk.Label(barra, text=" (vazio = detectar)").pack(side="left")
        ttk.Button(barra, text="Exportar .ics…", command=self.exportar_ics).pack(side="right")
        ttk.Button(barra, text="Texto extraído", command=self.mostrar_texto).pack(side="right", padx=4)
        ttk.Button(barra, text="Avisos", command=self.mostrar_avisos).pack(side="right")

    def _montar_corpo(self) -> None:
        abas = ttk.Notebook(self)
        abas.pack(fill="both", expand=True)
        aba_cal, aba_freq, aba_notas = ttk.Frame(abas), ttk.Frame(abas), ttk.Frame(abas)
        abas.add(aba_cal, text="Calendário")
        abas.add(aba_freq, text="Frequência")
        abas.add(aba_notas, text="Notas")
        self._montar_aba_frequencia(aba_freq)
        self._montar_aba_notas(aba_notas)
        corpo = ttk.PanedWindow(aba_cal, orient="horizontal")
        corpo.pack(fill="both", expand=True)
        esq, dire = ttk.Frame(corpo, padding=8), ttk.Frame(corpo, padding=8)
        corpo.add(esq, weight=3)
        corpo.add(dire, weight=2)
        esq.columnconfigure(0, weight=1)
        esq.rowconfigure(1, weight=1)

        nav = ttk.Frame(esq)
        nav.grid(row=0, column=0, sticky="ew")
        ttk.Button(nav, text="◀", width=3, command=lambda: self._mudar_periodo(-1)).pack(side="left")
        ttk.Button(nav, text="Hoje", width=6, command=self._ir_hoje).pack(side="left", padx=2)
        self.lbl_mes = ttk.Label(nav, text="", font=("TkDefaultFont", 13, "bold"), anchor="center")
        self.lbl_mes.pack(side="left", fill="x", expand=True)
        ttk.Button(nav, text="▶", width=3, command=lambda: self._mudar_periodo(1)).pack(side="right")
        for texto, valor in (("Dia", "dia"), ("Semana", "semana"), ("Mês", "mes")):
            ttk.Radiobutton(nav, text=texto, value=valor, variable=self.var_visao,
                            command=self._atualizar_visao).pack(side="right", padx=2)

        self.grade = ttk.Frame(esq)                          # visão MÊS: 6 semanas x 7 dias
        self.grade.grid(row=1, column=0, sticky="nsew", pady=6)
        for c, nome in enumerate(("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")):
            ttk.Label(self.grade, text=nome, anchor="center").grid(row=0, column=c, sticky="ew")
            self.grade.columnconfigure(c, weight=1, uniform="col")
        for i in range(42):
            cel = tk.Label(self.grade, text="", width=12, height=5, anchor="nw", justify="left",
                           relief="groove", bg=BRANCO, fg="#000000", wraplength=118)
            cel.grid(row=1 + i // 7, column=i % 7, sticky="nsew")
            cel.bind("<Button-1>", lambda ev, k=i: self._clicar_celula(k))
            cel.bind("<Double-Button-1>", lambda ev, k=i: self._duplo_clique_celula(k))
            self._celulas.append(cel)
        for r in range(1, 7):
            self.grade.rowconfigure(r, weight=1)

        self.grade_h = ttk.Frame(esq)                        # visões SEMANA e DIA: horas de 08:00 a 17:00
        self.grade_h.grid(row=1, column=0, sticky="nsew", pady=6)
        self.grade_h.grid_remove()
        self.legenda = ttk.Frame(esq)
        self.legenda.grid(row=2, column=0, sticky="ew")
        self._desenhar_legenda()

        self.lbl_info = ttk.Label(dire, text="Nenhum cronograma aberto", font=("TkDefaultFont", 11, "bold"),
                                  wraplength=380, justify="left")
        self.lbl_info.pack(fill="x")
        botoes = ttk.Frame(dire)
        botoes.pack(fill="x", pady=(4, 0))
        ttk.Button(botoes, text="Novo evento", command=self.novo_evento).pack(side="left")
        ttk.Button(botoes, text="Editar", command=self.editar_evento).pack(side="left", padx=4)
        ttk.Button(botoes, text="Excluir", command=self.excluir_evento).pack(side="left")
        quadro = ttk.Frame(dire)
        quadro.pack(fill="both", expand=True, pady=6)
        self.arvore = ttk.Treeview(quadro, columns=COLUNAS_TODAS, displaycolumns=COLUNAS_UMA, show="headings", height=9)
        for col, titulo, larg in (("data", "Data", 80), ("hora", "Horário", 95), ("materia", "Matéria", 120),
                                  ("tipo", "Tipo", 100), ("desc", "Descrição", 230)):
            self.arvore.heading(col, text=titulo)
            self.arvore.column(col, width=larg, anchor="w")
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=self.arvore.yview)
        self.arvore.configure(yscrollcommand=rolagem.set)
        self.arvore.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")
        self.arvore.bind("<<TreeviewSelect>>", self._linha_selecionada)
        self.arvore.bind("<Double-Button-1>", lambda ev: self.editar_evento())
        self._montar_painel_horario(dire)
        self.detalhe = tk.Text(dire, height=10, wrap="word", state="disabled", font=("TkFixedFont", 10))
        self.detalhe.pack(fill="both")

    def _montar_painel_horario(self, pai) -> None:
        quadro = ttk.LabelFrame(pai, text=f"Horário ({HORA_INICIO_DIA:02d}:00 às {HORA_FIM_DIA:02d}:00)", padding=6)
        quadro.pack(fill="x", pady=(0, 6))
        opcoes = opcoes_de_horario()
        self.var_ini, self.var_fim = tk.StringVar(value=""), tk.StringVar(value="")
        self.var_dur = tk.StringVar(value="2h")
        ttk.Label(quadro, text="Início").grid(row=0, column=0)
        ttk.Combobox(quadro, textvariable=self.var_ini, values=opcoes, width=7, state="readonly").grid(row=0, column=1, padx=4)
        ttk.Label(quadro, text="Fim").grid(row=0, column=2)
        ttk.Combobox(quadro, textvariable=self.var_fim, values=opcoes, width=7, state="readonly").grid(row=0, column=3, padx=4)
        ttk.Button(quadro, text="Atribuir", command=self.atribuir_horario).grid(row=0, column=4, padx=2)
        ttk.Button(quadro, text="Remover", command=self.remover_horario).grid(row=0, column=5, padx=2)
        ttk.Label(quadro, text="Duração").grid(row=1, column=0, pady=(6, 0))
        ttk.Combobox(quadro, textvariable=self.var_dur, values=list(DURACOES), width=7,
                     state="readonly").grid(row=1, column=1, pady=(6, 0))
        ttk.Button(quadro, text="Atribuir horários livres a todas as aulas/avaliações sem hora",
                   command=self.atribuir_livres).grid(row=1, column=2, columnspan=4, sticky="w", padx=4, pady=(6, 0))

    # ---------- agenda, cores e legenda ----------
    def _agenda(self) -> AgendaGeral:
        """O que as visões mostram: só a matéria atual ou TODAS as matérias juntas."""
        if self.var_todas.get():
            return self.servico.agenda_geral()
        return AgendaGeral([self.servico.disciplina] if self.servico.disciplina else [])

    def _cor_item(self, disciplina, evento: Evento) -> str:
        """Junto: uma cor por matéria. Só uma matéria: uma cor por tipo de evento."""
        if self.var_todas.get():
            return PALETA_MATERIAS[self.servico.nomes().index(disciplina.nome) % len(PALETA_MATERIAS)]
        return cor_do(evento)

    def _desenhar_legenda(self) -> None:
        for w in self.legenda.winfo_children():
            w.destroy()
        if self.var_todas.get():
            itens = [(n, PALETA_MATERIAS[i % len(PALETA_MATERIAS)]) for i, n in enumerate(self.servico.nomes())]
        else:
            itens = [(t.rotulo, cor_do(t(date.today(), ""))) for t in TIPOS]
        for texto, cor in itens:
            tk.Label(self.legenda, text=f" {texto} ", bg=cor, fg="#000000").pack(side="left", padx=2, pady=2)

    def _titulo_periodo(self) -> str:
        d, visao = self.dia_foco, self.var_visao.get()
        if visao == "mes":
            return f"{MESES[d.month]} {d.year}"
        if visao == "semana":
            segunda = AgendaGeral.inicio_da_semana(d)
            return f"Semana de {segunda:%d/%m} a {segunda + timedelta(days=6):%d/%m/%Y}"
        return f"{DIAS_LONGOS[d.weekday()]}, {d:%d/%m/%Y}"

    # ---------- visões: mês, semana e dia ----------
    def _atualizar_visao(self) -> None:
        """Desenha a visão escolhida (mês, semana ou dia) em torno do dia em foco."""
        visao = self.var_visao.get()
        self.lbl_mes.config(text=self._titulo_periodo())
        if visao == "mes":
            self.grade_h.grid_remove()
            self.grade.grid()
            self._desenhar_mes()
            return
        self.grade.grid_remove()
        self.grade_h.grid()
        if visao == "semana":
            segunda = AgendaGeral.inicio_da_semana(self.dia_foco)
            self._desenhar_grade_horaria([segunda + timedelta(days=i) for i in range(7)])
        else:
            self._desenhar_grade_horaria([self.dia_foco])

    def _mudar_periodo(self, delta: int) -> None:
        """◀ e ▶: andam um mês, uma semana ou um dia, conforme a visão."""
        visao, d = self.var_visao.get(), self.dia_foco
        if visao == "mes":
            total = d.year * 12 + d.month - 1 + delta
            self.dia_foco = date(total // 12, total % 12 + 1, 1)
        else:
            self.dia_foco = d + timedelta(days=(7 if visao == "semana" else 1) * delta)
        self._atualizar_visao()

    def _ir_hoje(self) -> None:
        self.dia_foco = date.today()
        self._atualizar_visao()

    def _desenhar_mes(self) -> None:
        ano, mes = self.dia_foco.year, self.dia_foco.month
        agenda = self._agenda()
        semanas = calendar.Calendar(0).monthdatescalendar(ano, mes)
        self._datas = []
        for i, cel in enumerate(self._celulas):
            semana, col = divmod(i, 7)
            if semana >= len(semanas):
                self._datas.append(None)
                cel.config(text="", bg=CINZA_FORA)
                continue
            d = semanas[semana][col]
            self._datas.append(d)
            itens = agenda.eventos_do_dia(d)
            texto = f"{d.day}"
            cor = CINZA_FORA if d.month != mes else BRANCO
            if itens and d.month == mes:
                disc, ev = itens[0]
                cor = self._cor_item(disc, ev)
                hora = f"{ev.horario.inicio:%H:%M} " if ev.horario else ""
                materia = f"{disc.nome.split()[0][:5]} " if self.var_todas.get() else ""
                texto += "\n" + hora + materia + ev.resumo(46) + (f"  (+{len(itens) - 1})" if len(itens) > 1 else "")
            cel.config(text=texto, bg=cor)

    def _desenhar_grade_horaria(self, datas: list[date]) -> None:
        """Semana (7 colunas) ou dia (1 coluna): uma linha por hora, de 08:00 às 17:00."""
        for w in self.grade_h.winfo_children():
            w.destroy()
        agenda, hoje = self._agenda(), date.today()
        largura = 110 if len(datas) > 1 else 560
        tk.Label(self.grade_h, text="", width=7).grid(row=0, column=0)
        for c, d in enumerate(datas):
            tk.Label(self.grade_h, text=f"{DIAS[d.weekday()]} {d:%d/%m}", font=("TkDefaultFont", 10, "bold"),
                     bg="#fff3cd" if d == hoje else "#e8eef5", fg="#000000").grid(row=0, column=1 + c, sticky="nsew", padx=1, pady=1)
            self.grade_h.columnconfigure(1 + c, weight=1, uniform="dia")
        tk.Label(self.grade_h, text="dia todo", fg="#555555", anchor="ne").grid(row=1, column=0, sticky="ne")
        for c, d in enumerate(datas):
            self._celula_grade(1, 1 + c, d, [it for it in agenda.eventos_do_dia(d) if not it[1].horario], None, largura)
        for r, h in enumerate(range(HORA_INICIO_DIA, HORA_FIM_DIA)):
            tk.Label(self.grade_h, text=f"{h:02d}:00", fg="#555555", anchor="ne").grid(row=2 + r, column=0, sticky="ne")
            for c, d in enumerate(datas):
                itens = [it for it in agenda.eventos_do_dia(d) if it[1].horario and it[1].horario.cobre_hora(h)]
                self._celula_grade(2 + r, 1 + c, d, itens, h, largura)
            self.grade_h.rowconfigure(2 + r, weight=1)

    def _celula_grade(self, linha: int, coluna: int, dia: date, itens: list, hora: int | None, largura: int) -> None:
        """Uma célula da semana/dia: colorida se houver evento; mostra o evento na hora em que ele começa."""
        textos = []
        for disc, ev in itens:
            rotulo = ev.resumo(70 if largura < 200 else 220) + (f" [{disc.nome.split()[0]}]" if self.var_todas.get() else "")
            if hora is None:
                textos.append(rotulo)
            elif ev.horario.inicio.hour == hora:
                textos.append(f"{ev.horario.inicio:%H:%M} {rotulo}")
            else:
                textos.append("↳ " + rotulo)               # continuação de um evento que começou antes
        cel = tk.Label(self.grade_h, text="\n".join(textos), bg=self._cor_item(*itens[0]) if itens else BRANCO,
                       fg="#000000", anchor="nw", justify="left", relief="groove", wraplength=largura)
        cel.grid(row=linha, column=coluna, sticky="nsew", padx=1, pady=1)
        cel.bind("<Button-1>", lambda ev, d=dia, it=itens: self._clicar_grade(d, it))
        cel.bind("<Double-Button-1>", lambda ev, d=dia, it=itens: self._duplo_clique_grade(d, it))

    def _clicar_celula(self, i: int) -> None:
        d = self._datas[i]
        if d is None:
            return
        self.dia_foco = d
        self._atualizar_visao()
        self._mostrar_dia(d)
        self._selecionar_na_lista(next((e for _, e in self._agenda().eventos_do_dia(d)), None))

    def _duplo_clique_celula(self, i: int) -> None:
        if self._datas[i] is not None:
            self.novo_evento(self._datas[i])

    def _clicar_grade(self, dia: date, itens: list) -> None:
        self._mostrar_dia(dia)
        self._selecionar_na_lista(itens[0][1] if itens else None)

    def _duplo_clique_grade(self, dia: date, itens: list) -> None:
        if itens:
            self.editar_evento(itens[0][1])
        else:
            self.novo_evento(dia)

    def _selecionar_na_lista(self, evento: Evento | None) -> None:
        """Destaca o evento na tabela sem disparar a atualização em cadeia."""
        for iid, e in self._por_iid.items():
            if e is evento:
                self._sincronizando = True
                self.arvore.selection_set(iid)
                self.arvore.see(iid)
                self._sincronizando = False
                break

    def _linha_selecionada(self, _evento=None) -> None:
        if self._sincronizando:
            return
        selecionados = self.arvore.selection()
        if not selecionados:
            return
        ev = self._por_iid.get(selecionados[0])
        if ev:
            self.var_ini.set(f"{ev.horario.inicio:%H:%M}" if ev.horario else "")
            self.var_fim.set(f"{ev.horario.fim:%H:%M}" if ev.horario else "")
            self.dia_foco = ev.data
            self._atualizar_visao()
            self._mostrar_dia(ev.data)

    def _mostrar_dia(self, d: date) -> None:
        if not self.servico.disciplina:
            return
        agenda = self._agenda()
        texto = ExibidorAgenda(agenda).dia(d)
        if not agenda.eventos_do_dia(d):
            texto += "\n\nSem eventos neste dia."
        self._escrever(self.detalhe, texto)

    @staticmethod
    def _escrever(caixa: tk.Text, texto: str) -> None:
        caixa.config(state="normal")
        caixa.delete("1.0", "end")
        caixa.insert("end", texto)
        caixa.config(state="disabled")

    # ---------- abrir matérias e lista de eventos ----------
    def abrir_dialogo(self) -> None:
        caminho = filedialog.askopenfilename(title="Escolha o cronograma", filetypes=FORMATOS)
        if caminho:
            self.abrir(caminho)

    def abrir(self, caminho: str) -> None:
        texto_ano = self.var_ano.get().strip()
        try:
            ano = int(texto_ano) if texto_ano else None
        except ValueError:
            messagebox.showerror("Ano inválido", "Digite o ano com 4 dígitos (ex.: 2026) ou deixe vazio.")
            return
        self.var_status.set("Lendo o arquivo... (imagens e PDFs escaneados podem levar alguns segundos)")
        self.update_idletasks()
        try:
            self.servico.carregar(caminho, ano, perguntar_nome=self._perguntar_nome)
        except Exception as e:
            messagebox.showerror("Não foi possível ler o cronograma", str(e))
            return
        self._exibir_disciplina(caminho)

    def _perguntar_nome(self, sugestao: str) -> str | None:
        """O documento não diz o nome da matéria (comum em imagens): pergunta ao usuário."""
        return simpledialog.askstring("Nome da matéria", "O documento não diz o nome da matéria.\nQual é o nome?",
                                      initialvalue=sugestao, parent=self)

    def _exibir_disciplina(self, caminho: str | None = None) -> None:
        """Mostra na tela a matéria selecionada (calendário, frequência e notas)."""
        disc = self.servico.disciplina
        self.cb_materia.config(values=self.servico.nomes())
        self.var_materia.set(disc.nome)
        self.title(f"Calendário Acadêmico — {disc.nome}")
        self._atualizar_info()
        self._preencher_lista()
        intervalo = self._agenda().intervalo()
        self.dia_foco = intervalo[0] if intervalo else date.today()
        self._desenhar_legenda()
        self._atualizar_visao()
        self._escrever(self.detalhe, "Clique em um dia ou em um evento da lista.")
        self._atualizar_frequencia()
        self._atualizar_notas()
        origem = f"{Path(caminho).name} | leitor: {self.servico.nome_leitor}" if caminho else "do banco de dados"
        self.var_status.set(f"{origem}: {len(disc.calendario)} eventos | {len(self.servico.avisos)} aviso(s)")
        if caminho and self.servico.avisos:
            self.mostrar_avisos()

    def _atualizar_info(self) -> None:
        disc = self.servico.disciplina
        if self.var_todas.get():
            conflitos = len(self.servico.agenda_geral().conflitos())
            self.lbl_info.config(text=f"TODAS AS MATÉRIAS ({len(self.servico.nomes())})\n"
                                      f"{conflitos} conflito(s) de horário entre matérias")
        elif disc:
            self.lbl_info.config(text=f"{disc.nome}\nProf.: {disc.professor}\n{disc.horario} | {disc.local}")

    def _preencher_lista(self) -> None:
        self.arvore.delete(*self.arvore.get_children())
        self._por_iid = {}
        for n, (_, e) in enumerate(self._agenda().todos()):
            iid = str(n)
            self._por_iid[iid] = e
            self.arvore.insert("", "end", iid=iid, values=self._valores(e))

    def _trocar_materia(self, _evento=None) -> None:
        try:
            self.servico.selecionar(self.var_materia.get())
        except ValueError as e:
            messagebox.showerror("Matéria", str(e))
            return
        self._exibir_disciplina()

    def _alternar_todas(self) -> None:
        """Marca/desmarca "Todas as matérias juntas": muda lista, cores, legenda e visões."""
        if not self._exigir_disciplina():
            self.var_todas.set(False)
            return
        self.arvore.configure(displaycolumns=COLUNAS_TODAS if self.var_todas.get() else COLUNAS_UMA)
        self._atualizar_info()
        self._preencher_lista()
        self._desenhar_legenda()
        self._atualizar_visao()
        self._escrever(self.detalhe, "Clique em um dia ou em um evento da lista.")

    def _valores(self, e: Evento) -> tuple:
        return (f"{e.data:%d/%m/%Y}", str(e.horario) if e.horario else "—", self.servico.dono_de(e).nome,
                e.rotulo, e.descricao())

    def _evento_selecionado(self) -> Evento | None:
        sel = self.arvore.selection()
        return self._por_iid.get(sel[0]) if sel else None

    def _atualizar_apos_horario(self, ev: Evento | None = None) -> None:
        for iid, e in self._por_iid.items():
            self.arvore.item(iid, values=self._valores(e))
        self._atualizar_visao()
        if ev:
            self._mostrar_dia(ev.data)
        self.var_status.set(f"{len(self.servico.avisos)} aviso(s)")

    # ---------- criar, editar e excluir eventos à mão ----------
    def novo_evento(self, dia: date | None = None) -> None:
        if self._exigir_disciplina():
            self._abrir_formulario(None, dia or self.dia_foco)

    def editar_evento(self, evento: Evento | None = None) -> None:
        evento = evento or self._evento_selecionado()
        if not self._exigir_disciplina():
            return
        if not evento:
            messagebox.showinfo("Editar evento", "Selecione um evento (na lista ou no calendário).")
            return
        self._abrir_formulario(evento, evento.data)

    def excluir_evento(self) -> None:
        evento = self._evento_selecionado()
        if not self._exigir_disciplina():
            return
        if not evento:
            messagebox.showinfo("Excluir evento", "Selecione um evento na lista.")
            return
        if messagebox.askyesno("Excluir evento", f"Excluir '{evento.titulo()}' de {evento.data:%d/%m/%Y}?"):
            self.servico.remover_evento(evento)
            self._depois_de_editar()

    def _abrir_formulario(self, evento: Evento | None, dia: date) -> None:
        """Janela de novo evento / edição. Os campos ficam em variáveis para o botão Salvar ler."""
        self._evento_em_edicao = evento
        self.f_materia.set(self.servico.dono_de(evento).nome if evento else self.servico.disciplina.nome)
        self.f_tipo.set(evento.rotulo if evento else "Aula")
        self.f_data.set(f"{(evento.data if evento else dia):%d/%m/%Y}")
        self.f_texto.set(evento.texto if evento else "")
        self.f_ini.set(f"{evento.horario.inicio:%H:%M}" if evento and evento.horario else "")
        self.f_fim.set(f"{evento.horario.fim:%H:%M}" if evento and evento.horario else "")
        janela = tk.Toplevel(self)
        janela.title("Editar evento" if evento else "Novo evento")
        quadro = ttk.Frame(janela, padding=10)
        quadro.pack(fill="both", expand=True)
        opcoes = [""] + opcoes_de_horario()
        campos = (("Matéria", ttk.Combobox(quadro, textvariable=self.f_materia, values=self.servico.nomes(),
                                           width=34, state="disabled" if evento else "readonly")),
                  ("Tipo", ttk.Combobox(quadro, textvariable=self.f_tipo, values=[t.rotulo for t in TIPOS_EDITAVEIS],
                                        width=34, state="readonly")),
                  ("Data (dd/mm/aaaa)", ttk.Entry(quadro, textvariable=self.f_data, width=37)),
                  ("Descrição", ttk.Entry(quadro, textvariable=self.f_texto, width=37)),
                  ("Início", ttk.Combobox(quadro, textvariable=self.f_ini, values=opcoes, width=34, state="readonly")),
                  ("Fim", ttk.Combobox(quadro, textvariable=self.f_fim, values=opcoes, width=34, state="readonly")))
        for linha, (rotulo, campo) in enumerate(campos):
            ttk.Label(quadro, text=rotulo).grid(row=linha, column=0, sticky="w", pady=3)
            campo.grid(row=linha, column=1, pady=3, padx=6)
        ttk.Label(quadro, justify="left", foreground="#555555",
                  text=f"Horários entre {HORA_INICIO_DIA:02d}:00 e {HORA_FIM_DIA:02d}:00. Em um evento novo, aulas e\n"
                       "avaliações sem horário usam o horário da matéria.").grid(row=6, column=0, columnspan=2, pady=4)
        botoes = ttk.Frame(quadro)
        botoes.grid(row=7, column=0, columnspan=2, pady=(6, 0))
        ttk.Button(botoes, text="Salvar", command=self._salvar_formulario).pack(side="left", padx=4)
        ttk.Button(botoes, text="Cancelar", command=janela.destroy).pack(side="left")
        self._janela_form = janela

    def _ler_data(self, texto: str) -> date:
        """Aceita 04/11/2026, 04/11/26 ou 04/11 (usa o ano em foco)."""
        for formato, sem_ano in (("%d/%m/%Y", False), ("%d/%m/%y", False), ("%d/%m", True)):
            try:
                d = datetime.strptime(texto.strip(), formato).date()
            except ValueError:
                continue
            return d.replace(year=self.dia_foco.year) if sem_ano else d
        raise ValueError("Data inválida. Use dia/mês/ano, ex.: 04/11/2026")

    def _salvar_formulario(self) -> None:
        try:
            data = self._ler_data(self.f_data.get())
            if self._evento_em_edicao is None:
                novo = self.servico.adicionar_evento(self.f_tipo.get(), data, self.f_texto.get(), self.f_ini.get(),
                                                     self.f_fim.get(), materia=self.f_materia.get())
            else:
                novo = self.servico.editar_evento(self._evento_em_edicao, self.f_tipo.get(), data,
                                                  self.f_texto.get(), self.f_ini.get(), self.f_fim.get())
        except ValueError as e:
            messagebox.showerror("Evento", str(e))
            return
        self._janela_form.destroy()
        self.dia_foco = novo.data
        self._depois_de_editar(novo)
        avisos = self.servico.conflitos_do_evento(novo)
        if avisos:
            messagebox.showwarning("Conflito de horário", "\n".join(avisos))

    def _depois_de_editar(self, evento: Evento | None = None) -> None:
        """Atualiza tudo que depende do calendário depois de criar/editar/excluir um evento."""
        self._preencher_lista()
        self._atualizar_info()
        self._atualizar_visao()
        self._atualizar_frequencia()
        self._atualizar_notas()
        if evento:
            self._mostrar_dia(evento.data)
            self._selecionar_na_lista(evento)
        else:
            self._escrever(self.detalhe, "Evento excluído.")
        self.var_status.set(f"{len(self.servico.avisos)} aviso(s)")

    def atribuir_horario(self) -> None:
        ev = self._evento_selecionado()
        if not ev:
            messagebox.showinfo("Horário", "Selecione um evento na lista.")
            return
        try:
            avisos = self.servico.atribuir_horario(ev, self.var_ini.get(), self.var_fim.get())
        except ValueError as e:
            messagebox.showerror("Horário inválido", str(e))
            return
        self._atualizar_apos_horario(ev)
        if avisos:
            messagebox.showwarning("Sobreposição de horários", "\n".join(avisos))

    def remover_horario(self) -> None:
        ev = self._evento_selecionado()
        if ev:
            self.servico.remover_horario(ev)
            self.var_ini.set("")
            self.var_fim.set("")
            self._atualizar_apos_horario(ev)

    def atribuir_livres(self) -> None:
        if not self.servico.disciplina:
            messagebox.showinfo("Horário", "Abra um cronograma primeiro.")
            return
        n, avisos = self.servico.atribuir_horarios_livres(DURACOES.get(self.var_dur.get(), 120))
        self._atualizar_apos_horario()
        messagebox.showinfo("Horários livres", f"{n} evento(s) receberam horário entre "
                                               f"{HORA_INICIO_DIA:02d}:00 e {HORA_FIM_DIA:02d}:00."
                            + ("\n\n" + "\n".join(avisos) if avisos else ""))

    # ---------- aba Frequência ----------
    def _montar_aba_frequencia(self, pai) -> None:
        topo = ttk.Frame(pai, padding=8)
        topo.pack(fill="x")
        self.lbl_freq = ttk.Label(topo, text="Abra um cronograma para registrar presenças.", justify="left")
        self.lbl_freq.pack(side="left", fill="x", expand=True)
        minimo = ttk.Frame(pai, padding=(8, 0))
        minimo.pack(fill="x")
        ttk.Label(minimo, text="Frequência mínima (%):").pack(side="left")
        ttk.Entry(minimo, width=5, textvariable=self.var_freq_min).pack(side="left", padx=4)
        ttk.Button(minimo, text="Aplicar", command=self._aplicar_freq_minima).pack(side="left")
        quadro = ttk.Frame(pai, padding=8)
        quadro.pack(fill="both", expand=True)
        self.arvore_freq = ttk.Treeview(quadro, columns=("data", "aula", "status"), show="headings",
                                        selectmode="extended")
        for col, titulo, larg in (("data", "Data", 100), ("aula", "Aula", 420), ("status", "Presença", 120)):
            self.arvore_freq.heading(col, text=titulo)
            self.arvore_freq.column(col, width=larg, anchor="w")
        self.arvore_freq.tag_configure("presente", background="#c8e6c9")
        self.arvore_freq.tag_configure("falta", background="#ffcdd2")
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=self.arvore_freq.yview)
        self.arvore_freq.configure(yscrollcommand=rolagem.set)
        self.arvore_freq.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")
        botoes = ttk.Frame(pai, padding=8)
        botoes.pack(fill="x")
        ttk.Button(botoes, text="✔ Presente", command=lambda: self._marcar_presenca("presente")).pack(side="left")
        ttk.Button(botoes, text="✘ Falta", command=lambda: self._marcar_presenca("falta")).pack(side="left", padx=6)
        ttk.Button(botoes, text="Limpar registro", command=self._limpar_presenca).pack(side="left")

    def _exigir_disciplina(self) -> bool:
        if not self.servico.disciplina:
            messagebox.showinfo("Matéria", "Abra um cronograma primeiro.")
            return False
        return True

    def _atualizar_frequencia(self) -> None:
        d = self.servico.disciplina
        selecionados = self.arvore_freq.selection()
        self.arvore_freq.delete(*self.arvore_freq.get_children())
        self._por_iid_freq = {}
        if not d:
            return
        for n, e in enumerate(self.servico.eventos_de_frequencia()):
            status = d.frequencia.status_de(e)
            iid = str(n)
            self._por_iid_freq[iid] = e
            texto = {StatusPresenca.PRESENTE: "✔ Presente", StatusPresenca.FALTA: "✘ Falta"}.get(status, "—")
            self.arvore_freq.insert("", "end", iid=iid, values=(f"{e.data:%d/%m/%Y}", e.titulo(), texto),
                                    tags=(status.value if status else "pendente",))
        self.var_freq_min.set(f"{d.frequencia.minima:g}")
        situacao = d.resumo_frequencia().situacao
        cor = {SituacaoFrequencia.OK: "#1b5e20", SituacaoFrequencia.ATENCAO: "#e65100",
               SituacaoFrequencia.REPROVADO: "#b71c1c"}[situacao]
        self.lbl_freq.config(text=RelatorioAcademico(d).frequencia(), foreground=cor)
        if selecionados:
            self.arvore_freq.selection_set(selecionados)

    def _marcar_presenca(self, status: str) -> None:
        selecionados = self.arvore_freq.selection()
        if not self._exigir_disciplina() or not selecionados:
            return
        try:
            for iid in selecionados:
                self.servico.marcar_presenca(self._por_iid_freq[iid], status)
        except ValueError as e:
            messagebox.showerror("Frequência", str(e))
        self._atualizar_frequencia()

    def _limpar_presenca(self) -> None:
        selecionados = self.arvore_freq.selection()
        if not self._exigir_disciplina() or not selecionados:
            return
        for iid in selecionados:
            self.servico.limpar_presenca(self._por_iid_freq[iid])
        self._atualizar_frequencia()

    def _aplicar_freq_minima(self) -> None:
        if not self._exigir_disciplina():
            return
        try:
            self.servico.definir_frequencia_minima(self.var_freq_min.get())
        except ValueError as e:
            messagebox.showerror("Frequência mínima", str(e))
        self._atualizar_frequencia()

    # ---------- aba Notas ----------
    def _montar_aba_notas(self, pai) -> None:
        topo = ttk.Frame(pai, padding=8)
        topo.pack(fill="x")
        ttk.Label(topo, text="Média mínima para aprovação:").pack(side="left")
        ttk.Entry(topo, width=5, textvariable=self.var_media_min).pack(side="left", padx=4)
        ttk.Button(topo, text="Aplicar", command=self._aplicar_media_minima).pack(side="left")
        quadro = ttk.Frame(pai, padding=8)
        quadro.pack(fill="both", expand=True)
        self.arvore_notas = ttk.Treeview(quadro, columns=("nome", "data", "peso", "nota", "precisa"), show="headings",
                                         height=8, selectmode="browse")
        for col, titulo, larg in (("nome", "Avaliação", 240), ("data", "Data", 110), ("peso", "Peso", 60),
                                  ("nota", "Nota", 70), ("precisa", "Precisa tirar", 260)):
            self.arvore_notas.heading(col, text=titulo)
            self.arvore_notas.column(col, width=larg, anchor="w")
        self.arvore_notas.tag_configure("feita", background="#c8e6c9")
        self.arvore_notas.bind("<<TreeviewSelect>>", self._item_selecionado)
        self.arvore_notas.pack(fill="both", expand=True)
        edicao = ttk.LabelFrame(pai, text="Nota da avaliação selecionada", padding=6)
        edicao.pack(fill="x", padx=8)
        ttk.Entry(edicao, width=7, textvariable=self.var_nota).pack(side="left")
        ttk.Button(edicao, text="Lançar nota", command=self._lancar_nota).pack(side="left", padx=6)
        ttk.Button(edicao, text="Apagar nota", command=self._apagar_nota).pack(side="left")
        ttk.Button(edicao, text="Remover avaliação", command=self._remover_item).pack(side="right")
        novo = ttk.LabelFrame(pai, text="Nova avaliação (nome e peso)", padding=6)
        novo.pack(fill="x", padx=8, pady=6)
        ttk.Entry(novo, width=22, textvariable=self.var_item_nome).pack(side="left")
        ttk.Entry(novo, width=6, textvariable=self.var_item_peso).pack(side="left", padx=6)
        ttk.Button(novo, text="Adicionar", command=self._adicionar_item).pack(side="left")
        ttk.Button(novo, text="Importar avaliações do calendário", command=self._importar_avaliacoes).pack(side="right")
        self.lbl_notas = ttk.Label(pai, text="", justify="left", padding=8)
        self.lbl_notas.pack(fill="x")

    def _atualizar_notas(self) -> None:
        d = self.servico.disciplina
        self.arvore_notas.delete(*self.arvore_notas.get_children())
        self._nome_por_iid = {}
        if not d:
            return
        a = d.analise_notas()
        necessaria = {i.nome: i for i in a.por_item}
        for n, item in enumerate(d.notas.itens):
            if item.nota is not None:
                precisa = "—"
            elif a.situacao is SituacaoNotas.JA_APROVADO:
                precisa = "qualquer nota"
            else:
                precisa = f"{fmt_nota(necessaria[item.nome].necessaria_igual)} (se as outras forem iguais)"
            iid = str(n)
            self._nome_por_iid[iid] = item.nome
            self.arvore_notas.insert("", "end", iid=iid, tags=("feita",) if item.nota is not None else (),
                                     values=(item.nome, ", ".join(f"{dt:%d/%m}" for dt in d.datas_da_avaliacao(item.nome)) or "—",
                                             fmt_nota(item.peso), fmt_nota(item.nota), precisa))
        self.var_media_min.set(fmt_nota(a.media_minima).replace(",", "."))
        bom = a.situacao in (SituacaoNotas.APROVADO, SituacaoNotas.JA_APROVADO)
        ruim = a.situacao in (SituacaoNotas.REPROVADO, SituacaoNotas.IMPOSSIVEL)
        self.lbl_notas.config(text=RelatorioAcademico(d).resumo_notas() or "Cadastre as avaliações e seus pesos.",
                              foreground="#1b5e20" if bom else "#b71c1c" if ruim else "#000000")

    def _nome_do_item_selecionado(self) -> str | None:
        selecionados = self.arvore_notas.selection()
        return self._nome_por_iid.get(selecionados[0]) if selecionados else None

    def _item_selecionado(self, _evento=None) -> None:
        nome = self._nome_do_item_selecionado()
        if nome and self.servico.disciplina:
            nota = self.servico.disciplina.notas.item(nome).nota
            self.var_nota.set("" if nota is None else fmt_nota(nota))

    def _executar_nota(self, acao) -> None:
        """Roda uma ação do serviço e atualiza a tela; erros viram mensagem."""
        if not self._exigir_disciplina():
            return
        try:
            acao()
        except ValueError as e:
            messagebox.showerror("Notas", str(e))
        self._atualizar_notas()

    def _lancar_nota(self) -> None:
        nome = self._nome_do_item_selecionado()
        if not nome:
            messagebox.showinfo("Notas", "Selecione uma avaliação na lista.")
            return
        self._executar_nota(lambda: self.servico.definir_nota(nome, self.var_nota.get()))

    def _apagar_nota(self) -> None:
        nome = self._nome_do_item_selecionado()
        if nome:
            self.var_nota.set("")
            self._executar_nota(lambda: self.servico.definir_nota(nome, None))

    def _adicionar_item(self) -> None:
        def acao():
            self.servico.adicionar_item_nota(self.var_item_nome.get(), self.var_item_peso.get())
            self.var_item_nome.set("")
            self.var_item_peso.set("")
        self._executar_nota(acao)

    def _remover_item(self) -> None:
        nome = self._nome_do_item_selecionado()
        if nome:
            self._executar_nota(lambda: self.servico.remover_item_nota(nome))

    def _importar_avaliacoes(self) -> None:
        """Cria na lista de notas as provas, seminários e trabalhos que estão no calendário (peso 1 até você ajustar)."""
        if not self._exigir_disciplina():
            return
        novos = self.servico.importar_avaliacoes_do_calendario()
        self._atualizar_notas()
        messagebox.showinfo("Avaliações", ("Importadas do calendário: " + ", ".join(novos) + "\nAjuste os pesos, se precisar.")
                            if novos else "Nenhuma avaliação nova no calendário.")

    def _aplicar_media_minima(self) -> None:
        self._executar_nota(lambda: self.servico.definir_media_minima(self.var_media_min.get()))

    def exportar_ics(self) -> None:
        if not self.servico.disciplina:
            messagebox.showinfo("Exportar", "Abra um cronograma primeiro.")
            return
        todas = self.var_todas.get()
        nome = "calendario_todas_as_materias" if todas else "".join(c if c.isalnum() else "_" for c in self.servico.disciplina.nome)
        destino = filedialog.asksaveasfilename(defaultextension=".ics", initialfile=f"{nome}.ics",
                                               filetypes=[("Calendário iCalendar", "*.ics")])
        if destino:
            try:
                self.servico.exportar_ics(destino, todas=todas)
                messagebox.showinfo("Exportar", f"Arquivo criado:\n{destino}\n\nImporte no Google Agenda, "
                                                "Outlook ou Apple Calendário.")
            except OSError as e:
                messagebox.showerror("Erro ao salvar", str(e))

    def mostrar_avisos(self) -> None:
        avisos = list(self.servico.avisos)
        if self.var_todas.get():                             # junto: mostra TODOS os conflitos entre matérias
            avisos += [AgendaGeral.descrever_conflito(p) for p in self.servico.agenda_geral().conflitos()
                       if AgendaGeral.descrever_conflito(p) not in avisos]
        messagebox.showwarning("Avisos", "\n".join(f"• {a}" for a in avisos[:25]) if avisos else "Sem avisos.")

    def mostrar_texto(self) -> None:
        if not self.servico.linhas:
            messagebox.showinfo("Texto extraído", "Abra um cronograma primeiro.")
            return
        janela = tk.Toplevel(self)
        janela.title("Texto extraído do arquivo")
        caixa = tk.Text(janela, width=100, height=30, wrap="word")
        caixa.pack(fill="both", expand=True)
        caixa.insert("end", "\n".join(self.servico.linhas))
        caixa.config(state="disabled")
