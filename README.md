# Calendário Acadêmico

Lê o cronograma de uma disciplina (em quase qualquer formato) e aloca aulas, provas,
seminários e feriados nos respectivos dias. Mostra no terminal, em uma janela (Tkinter)
ou exporta para `.ics`.

## Uso
    python main.py                          # interface gráfica
    python main.py cronograma.pdf           # terminal
    python main.py cronograma.docx --ics agenda.ics
    python main.py cronograma.pdf --mes 9 --ano 2026
    python main.py arquivo.qualquer --mostrar-texto   # depuração: texto extraído

## Datas: em qualquer posição e formato
A data pode estar no começo, no meio ou no fim da linha, ou em outra coluna da tabela:
`10/08`, `10/08/2026`, `10-08-2026`, `10.08.2026`, `2026-08-10`, `10 de agosto`, `10 ago`,
`agosto 10`, `Aug 10, 2026`, `1º de setembro`, intervalos (`07/09 a 09/09`, `21 a 23 de abril` — recessos
e feriados viram um evento por dia) e listas organizadas por mês (`AGOSTO 2026` seguido de `10 - Aula 1`).
Para evitar falsos positivos, uma data no meio de uma frase só vale se o documento usar esse estilo
(ex.: `até 15/09` e `1/2 do conteúdo` não viram eventos). O ano é detectado no documento (ou use `--ano`)
e o programa avança para o ano seguinte quando o semestre vira (dezembro → janeiro).

## Horários (08:00 às 17:00)
- Lidos do texto de cada evento: `13h às 15h`, `13:30-15:00`, `das 8 às 10`, `8h30`, `às 14h` (sem fim = duração do horário da disciplina, ou 1h).
- Aulas e avaliações sem hora própria usam o horário do cabeçalho da disciplina.
- Só valem horários entre 08:00 e 17:00 (constantes em `modelos/horario.py`): o que passa de 17:00 é cortado, o que começa fora da janela é ignorado, com aviso.
- Manual (interface): selecione o evento → escolha início/fim → *Atribuir*. Automático: *Atribuir horários livres* ou `--atribuir-horarios --duracao 2` dão a cada aula/avaliação sem hora o primeiro horário livre do dia.
- Sobreposições de horário no mesmo dia geram avisos; `--dia 10/08` mostra a agenda do dia de 08:00 a 17:00; o `.ics` usa o horário de cada evento.

## Visões, edição manual e todas as matérias juntas
- **Mês, semana e dia:** na aba Calendário, escolha a visão (Mês, Semana, Dia). A semana e o dia mostram uma grade de horas de 08:00 às 17:00 (segunda a domingo); ◀ e ▶ andam um mês, uma semana ou um dia e *Hoje* volta para hoje. No terminal: `--semana 12/08`.
- **Criar, editar e excluir eventos:** botões *Novo evento*, *Editar* e *Excluir* (ou duplo clique em um dia ou em um evento). Escolha matéria, tipo, data, descrição e horário (08:00–17:00). Aulas e avaliações novas sem horário usam o horário da matéria. O que você cria ou muda fica guardado: ao reler o mesmo cronograma, o que você apagou não volta e o que você criou continua. No terminal: `--adicionar "04/11/2026|Prova|Prova extra|09:00-11:00"` e `--remover "04/11|extra"`.
- **Todas as matérias juntas:** marque a caixa *Todas as matérias juntas* para ver os planos de ensino de todas as matérias no mesmo calendário (uma cor por matéria) e receber avisos de conflito de horário entre elas; o `.ics` também sai com todas. No terminal: `--todas --semana 12/08` (ou `--todas --dia 10/08`).

## Frequência e notas (por matéria)
- **Frequência:** cada aula, seminário e estudo dirigido conta; feriado, 2ª chamada e "não houve aula" não. Marque *presente* ou *falta* (aba Frequência ou `--presente 10/08 --falta 17/08`). O programa mostra a frequência atual, quantas faltas ainda pode ter (mínimo padrão 75%, ou o que estiver no cronograma) e avisa quando não pode mais faltar.
- **Notas:** os pesos saem do próprio cronograma (ex.: `(Nota SEM 1 x 4) + (Nota ED1 x 3) + (Nota ED2 x 3)`), ou você cria avaliações (`--item "Prova 1=3"`). Lance as notas (`--nota "ED1=7,5"`) e o programa diz **quanto precisa tirar em cada avaliação que falta** para atingir a média (padrão 5,0): a nota igual em todas as pendentes e a nota se só uma delas contar. Também avisa quando a média já está garantida ou não é mais possível.
- Várias matérias: cada cronograma aberto vira uma matéria (caixa *Matéria* na janela).

## Banco de dados
Tudo (matérias, eventos, presenças, notas e horários manuais) é guardado em um arquivo SQLite (`calendario_academico.db`, ou `--banco OUTRO.db`). Reabra sem o arquivo do cronograma: `python main.py --materia "NOME" --relatorio`. `--listar-materias` mostra o que há guardado; `--sem-banco` trabalha só na memória.

## Imagens e tabelas em duas colunas
- **Foto ou print do cronograma** (png, jpg...): lido por OCR com a posição das palavras. Para funcionar, instale UM OCR: `pip install -r requirements-ocr.txt` (RapidOCR, não precisa de programa extra) ou o programa Tesseract OCR. Prefira um **print da tela** a uma foto da tela; o programa sempre avisa que o texto veio de OCR e pede para conferir. Corrija o que vier errado no próprio calendário (botão Editar).
- **Cronograma dividido em duas partes** (duas colunas de datas, como `11/8 ... | 20/10 ...`): lido em PDF, imagem, Word, Excel e texto; cada coluna é lida inteira e depois a outra. Datas como `11/8` e `1/9` também são entendidas. Se o OCR não leu algumas datas e o cronograma é semanal, elas são deduzidas de 7 em 7 dias (com aviso).
- **Descrição no calendário:** as células do mês, da semana e do dia mostram a descrição do evento (ex.: "Boas-vindas, classes, objetos").

## Avaliações na aba Notas
Se o cronograma não traz a fórmula da nota final, as provas, seminários, estudos dirigidos e trabalhos que estão no calendário (P1, P2, "Apresentação final...") viram itens da aba Notas com peso 1 (o programa avisa; ajuste os pesos). Cada avaliação mostra a data. O botão *Importar avaliações do calendário* (ou `--importar-avaliacoes`) cria os itens que faltarem. Se o documento não traz o nome da matéria, o programa pergunta (ou use `--nome "Programação II"`).

## Como usar como aplicativo
- **Duplo clique:** `abrir_windows.bat` (Windows) ou `abrir_mac_linux.sh`; ou abra `CalendarioAcademico.pyw` (sem janela de terminal; se der erro, aparece uma caixa e fica gravado em `erro.log`).
- **Executável:** `pip install pyinstaller` e depois `python criar_aplicativo.py` (no Windows, `criar_aplicativo_windows.bat`). Gera `dist/CalendarioAcademico.exe` (Windows) ou `.app` (macOS). O executável é feito para o sistema em que você roda o script.
- **Seus dados** ficam em uma pasta fixa (Windows: `%APPDATA%\CalendarioAcademico\dados.db`; macOS: `~/Library/Application Support/CalendarioAcademico`; Linux: `~/.local/share/CalendarioAcademico`), então são os mesmos de onde quer que você abra o programa. Um banco antigo da pasta atual é copiado uma vez.

## Formatos
PDF (inclusive escaneado, com OCR), Word (.docx; .doc via LibreOffice), Excel (.xlsx; .xls via
LibreOffice), PowerPoint (.pptx), OpenDocument (.odt/.ods/.odp), HTML, CSV/TSV, RTF, JSON, TXT/MD
e imagens (png/jpg/...). Se a extensão estiver errada, o formato é detectado pelo conteúdo.

## Dependências (todas opcionais conforme o formato)
    pip install -r requirements.txt        (e requirements-ocr.txt para imagens)
Tkinter já vem com o Python (Linux: `sudo apt install python3-tk`).
OCR precisa do programa Tesseract; .doc/.xls/.ppt antigos precisam do LibreOffice.

## Estrutura (POO)
- `modelos/`: `Evento` (abstrata) → `Aula`, `Feriado`, `Avaliacao` → `Prova`/`Seminario`/...; `Calendario`; `Disciplina`
- `leitores/`: `LeitorCronograma` (abstrata) → um leitor por formato; `LeitorAutomatico` escolhe e tenta alternativas
- `modelos/frequencia.py`, `modelos/notas.py` e `extrator_notas.py`: frequência, boletim (média ponderada e nota necessária) e leitura dos pesos no cronograma
- `modelos/agenda_geral.py`: `AgendaGeral` junta várias matérias (dia, semana, conflitos)
- `repositorio.py`: `Repositorio` (abstração) e `RepositorioSQLite`; `servico.py` é a fachada que usa tudo
- `padroes.py` e `interpretador.py`: reconhecem datas/horários e classificam cada linha em um tipo de evento
- `modelos/horario.py` (`Horario`, janela 8h–17h) e `modelos/agendador.py` (`AgendadorHorarios`)
- `exportacao/ics.py`: `ExportadorICS`; `saida/exibidor.py`: texto; `gui.py`: Tkinter; `servico.py`: une tudo

## Testes
    pip install python-docx python-pptx reportlab   # só para gerar os arquivos de teste
    python -m unittest discover -s tests -t .

## Documentação para a apresentação (pasta `docs/`)
- `GUIA_DE_APRESENTACAO.pdf`: conceitos aplicados (Git, testes/TDD, banco de dados, SOLID e design patterns), roteiro de apresentação, perguntas do professor e a explicação linha a linha de todo o código.
- `CONCEITOS_APLICADOS.md` e `EXPLICACAO_DO_CODIGO.md`: as mesmas partes em Markdown.

## Git
O `.gitignore` já exclui `__pycache__`, `*.db` (dados pessoais de notas e faltas) e `*.ics`. Veja o fluxo sugerido em `docs/CONCEITOS_APLICADOS.md`.
