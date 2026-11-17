"""Calendário acadêmico: lê cronogramas, controla frequência e notas, guarda tudo em um banco SQLite.

Exemplos:
  python main.py                                   # abre a interface gráfica
  python main.py cronograma.pdf                    # mostra o calendário (e guarda a matéria no banco)
  python main.py cronograma.pdf --falta 17/08 --presente 10/08 24/08
  python main.py cronograma.pdf --nota "SEM 1=7" --nota "ED1=4" --relatorio
  python main.py --materia "Medicina Molecular" --relatorio    # reabre do banco, sem o arquivo
"""
import argparse
import re
import sys
from datetime import date

from modelos.agenda_geral import AgendaGeral
from armazenamento import caminho_padrao_do_banco
from repositorio import RepositorioSQLite
from saida.exibidor import ExibidorAgenda, ExibidorTexto
from saida.relatorio import RelatorioAcademico
from servico import ServicoCalendario



def ler_argumentos() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Calendário acadêmico: cronograma, frequência e notas")
    ap.add_argument("arquivo", nargs="?", help="cronograma (pdf, docx, xlsx, odt, html, csv, txt, imagem...)")
    ap.add_argument("--nome", metavar="MATÉRIA", help="nome da matéria (para documentos que não trazem o nome)")
    ap.add_argument("--ano", type=int, help="ano das datas (padrão: detectado no documento ou ano atual)")
    ap.add_argument("--mes", type=int, help="mostrar só este mês (1-12)")
    ap.add_argument("--ics", metavar="SAIDA.ics", help="exporta para .ics (Google Agenda, Outlook, Apple)")
    ap.add_argument("--dia", metavar="DD/MM", help="mostra a agenda desse dia (08:00 às 17:00)")
    ap.add_argument("--atribuir-horarios", action="store_true",
                    help="dá horário livre (08:00–17:00) às aulas/avaliações que ainda não têm hora")
    ap.add_argument("--duracao", type=float, default=2.0, metavar="HORAS",
                    help="duração usada por --atribuir-horarios (padrão: 2)")
    banco = ap.add_argument_group("banco de dados e matérias")
    banco.add_argument("--banco", default=None, metavar="ARQUIVO.db",
                       help="arquivo do banco (padrão: dados.db na pasta de dados do aplicativo)")
    banco.add_argument("--sem-banco", action="store_true", help="não guarda nada (só memória)")
    banco.add_argument("--materia", metavar="NOME", help="abre uma matéria já guardada no banco")
    banco.add_argument("--listar-materias", action="store_true", help="lista as matérias guardadas")
    freq = ap.add_argument_group("frequência")
    freq.add_argument("--presente", nargs="+", metavar="DD/MM", help="marca presença nesses dias")
    freq.add_argument("--falta", nargs="+", metavar="DD/MM", help="marca falta nesses dias")
    freq.add_argument("--frequencia-minima", type=float, metavar="%", help="muda a frequência mínima (padrão 75)")
    notas = ap.add_argument_group("notas")
    notas.add_argument("--nota", action="append", metavar='"AVALIACAO=NOTA"', help='ex.: --nota "ED1=7,5"')
    notas.add_argument("--item", action="append", metavar='"NOME=PESO"', help='cria uma avaliação, ex.: --item "Prova 1=3"')
    notas.add_argument("--remover-item", action="append", metavar="NOME", help="apaga uma avaliação")
    notas.add_argument("--importar-avaliacoes", action="store_true",
                       help="cria, na lista de notas, as provas/seminários/trabalhos que estão no calendário")
    notas.add_argument("--media-minima", type=float, metavar="NOTA", help="muda a média de aprovação (padrão 5)")
    ap.add_argument("--relatorio", action="store_true", help="mostra frequência e notas (com a nota necessária)")
    cal = ap.add_argument_group("visões e edição do calendário")
    cal.add_argument("--semana", nargs="?", const="hoje", metavar="DD/MM",
                     help="mostra a semana (segunda a domingo) que contém essa data (padrão: hoje)")
    cal.add_argument("--todas", action="store_true", help="junta TODAS as matérias guardadas (com --semana ou --dia)")
    cal.add_argument("--adicionar", action="append", metavar='"DD/MM/AAAA|Tipo|Texto|HH:MM-HH:MM"',
                     help='cria um evento à mão; o horário é opcional. Ex.: --adicionar "04/11/2026|Prova|Prova extra|09:00-11:00"')
    cal.add_argument("--remover", action="append", metavar='"DD/MM|trecho do texto"',
                     help="apaga um evento (o trecho do texto escolhe qual, se houver mais de um no dia)")
    ap.add_argument("--gui", action="store_true", help="abre a interface gráfica")
    ap.add_argument("--mostrar-texto", action="store_true", help="mostra o texto extraído do arquivo (depuração)")
    return ap.parse_args()


def separar(texto: str) -> tuple[str, str]:
    """'ED1=7,5' -> ('ED1', '7,5')."""
    if "=" not in texto:
        raise ValueError(f"Use o formato NOME=VALOR (recebi '{texto}')")
    nome, valor = texto.rsplit("=", 1)
    return nome.strip(), valor.strip()


def data_do_calendario(servico: ServicoCalendario, texto: str) -> date:
    """'10/08' -> a data completa daquele dia no calendário da matéria."""
    try:
        dia, mes = (int(x) for x in texto.split("/")[:2])
    except ValueError:
        raise ValueError(f"Use DD/MM, ex.: 10/08 (recebi '{texto}')") from None
    for e in servico.todos():
        if (e.data.day, e.data.month) == (dia, mes):
            return e.data
    raise ValueError(f"Não há nenhum evento em {texto} no calendário")


def ler_data(servico: ServicoCalendario, texto: str) -> date:
    """'04/11/2026' ou '04/11' (sem ano, usa o do calendário da matéria; vira o ano se precisar)."""
    partes = texto.strip().split("/")
    try:
        if len(partes) == 3:
            ano = int(partes[2])
            return date(ano + (2000 if ano < 100 else 0), int(partes[1]), int(partes[0]))
        dia, mes = int(partes[0]), int(partes[1])
        primeira = servico.agenda_geral().intervalo()[0]
        return date(primeira.year + (1 if (mes, dia) < (primeira.month, primeira.day) else 0), mes, dia)
    except (ValueError, IndexError, TypeError):
        raise ValueError(f"Data inválida: '{texto}'. Use DD/MM/AAAA ou DD/MM") from None


def data_de_referencia(servico: ServicoCalendario, texto: str | None) -> date:
    """Dia usado por --semana: o informado ou, sem nada, hoje (ou o começo do calendário se hoje estiver fora)."""
    if texto and texto != "hoje":
        return ler_data(servico, texto)
    intervalo = servico.agenda_geral().intervalo()
    hoje = date.today()
    return hoje if intervalo and intervalo[0] <= hoje <= intervalo[1] else intervalo[0]


def aplicar_edicoes(servico: ServicoCalendario, args: argparse.Namespace) -> list[tuple[str, date]]:
    """Cria e apaga eventos pedidos. Devolve (mensagem, data) de cada alteração feita."""
    feitas = []
    for texto in args.adicionar or []:
        campos = [c.strip() for c in texto.split("|")]
        if len(campos) not in (3, 4):
            raise ValueError("Use --adicionar \"DD/MM/AAAA|Tipo|Texto|HH:MM-HH:MM\" (o horário é opcional)")
        inicio, fim = "", ""
        if len(campos) == 4 and campos[3]:
            horas = re.split(r"\s*[-–]\s*", campos[3])
            if len(horas) != 2:
                raise ValueError(f"Horário inválido: '{campos[3]}' (use HH:MM-HH:MM)")
            inicio, fim = horas
        evento = servico.adicionar_evento(campos[1], ler_data(servico, campos[0]), campos[2], inicio, fim)
        feitas.append((f"Evento adicionado: {evento}", evento.data))
    for texto in args.remover or []:
        dia_texto, _, trecho = texto.partition("|")
        dia = data_do_calendario(servico, dia_texto.strip())
        candidatos = [e for e in servico.eventos_do_dia(dia)
                      if trecho.strip().lower() in f"{e.texto} {e.descricao()}".lower()]
        if not candidatos:
            raise ValueError(f"Nenhum evento em {dia:%d/%m} com '{trecho.strip()}'")
        if len(candidatos) > 1:
            raise ValueError(f"Há {len(candidatos)} eventos em {dia:%d/%m}; escreva parte do texto: "
                             f"--remover \"{dia:%d/%m}|texto\"")
        servico.remover_evento(candidatos[0])
        feitas.append((f"Evento removido: {candidatos[0]}", dia))
    return feitas


def aplicar_acoes(servico: ServicoCalendario, args: argparse.Namespace) -> bool:
    """Executa frequência/notas pedidas. Devolve True se alguma ação foi feita."""
    feito = False
    if args.frequencia_minima is not None:
        servico.definir_frequencia_minima(args.frequencia_minima)
        feito = True
    if args.media_minima is not None:
        servico.definir_media_minima(args.media_minima)
        feito = True
    if args.importar_avaliacoes:
        novos = servico.importar_avaliacoes_do_calendario()
        print("Avaliações importadas do calendário: " + (", ".join(novos) if novos else "nenhuma nova.") + "\n")
        feito = True
    for texto in args.item or []:
        servico.adicionar_item_nota(*separar(texto))
        feito = True
    for nome in args.remover_item or []:
        servico.remover_item_nota(nome)
        feito = True
    for texto in args.nota or []:
        servico.definir_nota(*separar(texto))
        feito = True
    for status, dias in (("presente", args.presente), ("falta", args.falta)):
        for dia in dias or []:
            servico.marcar_presenca_em(data_do_calendario(servico, dia), status)
            feito = True
    return feito


def abrir_interface(args: argparse.Namespace) -> None:
    try:
        from gui import AplicativoCalendario
    except ImportError as e:
        sys.exit(f"Não foi possível abrir a interface gráfica ({e}).\n"
                 "No Linux instale o Tkinter: sudo apt install python3-tk")
    AplicativoCalendario(args.arquivo, args.ano, None if args.sem_banco else args.banco).mainloop()


def main() -> None:
    args = ler_argumentos()
    args.banco = None if args.sem_banco else (args.banco or caminho_padrao_do_banco())
    if args.gui or not (args.arquivo or args.materia or args.listar_materias or args.todas):
        abrir_interface(args)
        return

    repositorio = None if args.sem_banco else RepositorioSQLite(args.banco)
    servico = ServicoCalendario(repositorio)
    try:
        if args.listar_materias:
            print("\n".join(repositorio.listar()) if repositorio else "(sem banco)")
            return
        if args.todas and repositorio:
            servico.carregar_do_banco()                       # todas as matérias guardadas
        if args.arquivo:
            servico.carregar(args.arquivo, args.ano, nome=args.nome)
        elif not args.todas:
            if not repositorio or not servico.carregar_do_banco(args.materia):
                sys.exit(f"Matéria '{args.materia}' não encontrada. Matérias guardadas: "
                         f"{', '.join(repositorio.listar()) if repositorio else 'nenhuma'}")
        elif not servico.disciplinas:
            sys.exit("Nenhuma matéria guardada ainda. Abra um cronograma primeiro.")
        if args.mostrar_texto:
            print("\n".join(servico.linhas), "\n" + "-" * 40)
        feito = aplicar_acoes(servico, args)
        edicoes = aplicar_edicoes(servico, args)
        if args.atribuir_horarios:
            n, avisos_h = servico.atribuir_horarios_livres(int(args.duracao * 60))
            print(f"{n} evento(s) receberam horário entre 08:00 e 17:00." + "".join(f"\n- {a}" for a in avisos_h) + "\n")
    except (ValueError, FileNotFoundError) as e:
        if args.mostrar_texto and servico.linhas:
            print("\n".join(servico.linhas), "\n")
        sys.exit(f"Erro: {e}")

    disciplina = servico.disciplina
    agenda = servico.agenda_geral() if args.todas else AgendaGeral([disciplina])
    if edicoes:
        for mensagem, dia in edicoes:
            print(mensagem + "\n" + ExibidorAgenda(agenda).dia(dia) + "\n")
    elif args.todas or args.semana is not None:
        texto = ExibidorAgenda(agenda)
        if args.dia and args.todas:
            print(texto.dia(data_do_calendario(servico, args.dia)))
        else:
            print(texto.semana(data_de_referencia(servico, args.semana)))
        if args.todas:
            print("\n" + texto.conflitos())
    elif args.relatorio or feito:
        print(RelatorioAcademico(disciplina).completo())
    else:
        ano = servico.ano or disciplina.calendario.intervalo()[0].year
        print(ExibidorTexto(disciplina).tudo((ano, args.mes) if args.mes else None))
        if args.dia:
            try:
                print("\n" + ExibidorTexto(disciplina).agenda_dia(data_do_calendario(servico, args.dia)))
            except ValueError as e:
                print(f"\nErro: {e}")
        if servico.avisos:
            print("\nAvisos:\n" + "\n".join(f"- {a}" for a in servico.avisos))
    if args.ics:
        servico.exportar_ics(args.ics, todas=args.todas)
        print(f"\nArquivo .ics criado: {args.ics}")


if __name__ == "__main__":
    main()
