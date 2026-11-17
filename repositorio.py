"""Persistência: guarda matérias, eventos, presenças e notas em um banco SQLite (módulo padrão do Python)."""
from __future__ import annotations
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import date
from decimal import Decimal
from typing import Optional

from modelos.disciplina import Disciplina
from modelos.evento import (Aula, AulaCancelada, Avaliacao, EstudoDirigido, Feriado, FimPeriodo,
                            InicioPeriodo, OutroEvento, Prova, SegundaChamada, Seminario, Trabalho)
from modelos.frequencia import ControleFrequencia
from modelos.horario import Horario
from modelos.notas import Boletim
from texto import chave_alfabetica

_TIPOS = {c.__name__: c for c in (Aula, AulaCancelada, Feriado, Avaliacao, Prova, Seminario,
                                  EstudoDirigido, SegundaChamada, Trabalho, InicioPeriodo,
                                  FimPeriodo, OutroEvento)}

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS disciplina (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nome              TEXT NOT NULL UNIQUE,
    professor         TEXT NOT NULL,
    horario           TEXT NOT NULL,
    local             TEXT NOT NULL,
    media_minima      TEXT NOT NULL DEFAULT '5',
    frequencia_minima REAL NOT NULL DEFAULT 75
);
CREATE TABLE IF NOT EXISTS evento (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    disciplina_id  INTEGER NOT NULL REFERENCES disciplina(id) ON DELETE CASCADE,
    chave          TEXT NOT NULL,
    data           TEXT NOT NULL,
    tipo           TEXT NOT NULL,
    texto          TEXT NOT NULL,
    hora_inicio    TEXT,
    hora_fim       TEXT,
    origem_horario TEXT NOT NULL DEFAULT '',
    segue_horario  INTEGER NOT NULL DEFAULT 1,
    manual         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS evento_removido (
    disciplina_id INTEGER NOT NULL REFERENCES disciplina(id) ON DELETE CASCADE,
    chave         TEXT NOT NULL,
    PRIMARY KEY (disciplina_id, chave)
);
CREATE TABLE IF NOT EXISTS presenca (
    disciplina_id INTEGER NOT NULL REFERENCES disciplina(id) ON DELETE CASCADE,
    chave         TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('presente', 'falta')),
    PRIMARY KEY (disciplina_id, chave)
);
CREATE TABLE IF NOT EXISTS item_nota (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    disciplina_id INTEGER NOT NULL REFERENCES disciplina(id) ON DELETE CASCADE,
    ordem         INTEGER NOT NULL,
    nome          TEXT NOT NULL,
    peso          TEXT NOT NULL,
    nota          TEXT,
    UNIQUE (disciplina_id, nome)
);
CREATE INDEX IF NOT EXISTS idx_evento_disciplina ON evento(disciplina_id, data);
"""


class Repositorio(ABC):
    """Contrato de armazenamento: o resto do programa só conhece ESTA interface."""

    @abstractmethod
    def salvar(self, disciplina: Disciplina) -> None: ...

    @abstractmethod
    def carregar(self, nome: str) -> Optional[Disciplina]: ...

    @abstractmethod
    def listar(self) -> list[str]: ...

    @abstractmethod
    def excluir(self, nome: str) -> None: ...

    @abstractmethod
    def fechar(self) -> None: ...


class RepositorioSQLite(Repositorio):
    def __init__(self, caminho: str = "calendario_academico.db") -> None:
        if caminho != ":memory:":
            Path(caminho).expanduser().parent.mkdir(parents=True, exist_ok=True)     # cria a pasta, se faltar
        self._con = sqlite3.connect(caminho)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA foreign_keys = ON")          # liga a exclusão em cascata
        self._con.executescript(_ESQUEMA)
        self._migrar()

    def _migrar(self) -> None:
        """Atualiza bancos criados por versões anteriores do programa (acrescenta a coluna 'manual')."""
        colunas = {r["name"] for r in self._con.execute("PRAGMA table_info(evento)")}
        if "manual" not in colunas:
            with self._con:
                self._con.execute("ALTER TABLE evento ADD COLUMN manual INTEGER NOT NULL DEFAULT 0")

    def salvar(self, d: Disciplina) -> None:
        """Grava um 'retrato' completo da matéria, dentro de uma transação (tudo ou nada)."""
        with self._con:
            achada = self._con.execute("SELECT id FROM disciplina WHERE nome = ?", (d.nome,)).fetchone()
            dados = (d.professor, d.horario, d.local, str(d.notas.media_minima), d.frequencia.minima)
            if achada:
                did = achada["id"]
                self._con.execute("UPDATE disciplina SET professor=?, horario=?, local=?, "
                                  "media_minima=?, frequencia_minima=? WHERE id=?", (*dados, did))
                for tabela in ("evento", "presenca", "item_nota", "evento_removido"):
                    self._con.execute(f"DELETE FROM {tabela} WHERE disciplina_id = ?", (did,))
            else:
                did = self._con.execute(
                    "INSERT INTO disciplina (nome, professor, horario, local, media_minima, "
                    "frequencia_minima) VALUES (?, ?, ?, ?, ?, ?)", (d.nome, *dados)).lastrowid
            self._con.executemany(
                "INSERT INTO evento (disciplina_id, chave, data, tipo, texto, hora_inicio, hora_fim, "
                "origem_horario, segue_horario, manual) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(did, e.chave, e.data.isoformat(), type(e).__name__, e.texto,
                  f"{e.horario.inicio:%H:%M}" if e.horario else None,
                  f"{e.horario.fim:%H:%M}" if e.horario else None,
                  e.origem_horario, int(e.segue_horario), int(e.manual)) for e in d.calendario.todos()])
            self._con.executemany("INSERT INTO evento_removido (disciplina_id, chave) VALUES (?, ?)",
                                  [(did, chave) for chave in sorted(d.removidos)])
            self._con.executemany(
                "INSERT INTO presenca (disciplina_id, chave, status) VALUES (?, ?, ?)",
                [(did, chave, st.value) for chave, st in d.frequencia.registros().items()])
            self._con.executemany(
                "INSERT INTO item_nota (disciplina_id, ordem, nome, peso, nota) VALUES (?, ?, ?, ?, ?)",
                [(did, n, i.nome, str(i.peso), None if i.nota is None else str(i.nota))
                 for n, i in enumerate(d.notas.itens)])

    def carregar(self, nome: str) -> Optional[Disciplina]:
        linha = self._con.execute("SELECT * FROM disciplina WHERE nome = ?", (nome,)).fetchone()
        if not linha:
            return None
        did = linha["id"]
        disciplina = Disciplina(nome=linha["nome"], professor=linha["professor"],
                                horario=linha["horario"], local=linha["local"],
                                frequencia=ControleFrequencia(linha["frequencia_minima"]),
                                notas=Boletim(linha["media_minima"]))
        for r in self._con.execute("SELECT * FROM evento WHERE disciplina_id = ? ORDER BY data, id", (did,)):
            horario = Horario.de_texto(r["hora_inicio"], r["hora_fim"]) if r["hora_inicio"] else None
            evento = _TIPOS[r["tipo"]](date.fromisoformat(r["data"]), r["texto"], horario, r["origem_horario"],
                                         bool(r["manual"]))
            if not r["segue_horario"]:
                evento.segue_horario = False
            disciplina.calendario.adicionar(evento)
        disciplina.removidos = {r["chave"] for r in self._con.execute(
            "SELECT chave FROM evento_removido WHERE disciplina_id = ?", (did,))}
        disciplina.frequencia.carregar_registros(
            {r["chave"]: r["status"] for r in
             self._con.execute("SELECT chave, status FROM presenca WHERE disciplina_id = ?", (did,))})
        for r in self._con.execute("SELECT * FROM item_nota WHERE disciplina_id = ? ORDER BY ordem", (did,)):
            disciplina.notas.adicionar_item(r["nome"], Decimal(r["peso"]), r["nota"])
        return disciplina

    def listar(self) -> list[str]:
        return sorted((r["nome"] for r in self._con.execute("SELECT nome FROM disciplina")),
                      key=chave_alfabetica)

    def excluir(self, nome: str) -> None:
        with self._con:
            self._con.execute("DELETE FROM disciplina WHERE nome = ?", (nome,))   # filhos saem em cascata

    def fechar(self) -> None:
        self._con.close()
