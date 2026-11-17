"""Cria o APLICATIVO (um arquivo executável) com o PyInstaller: abre com duplo clique, sem precisar do Python.

Uso:    python criar_aplicativo.py            (gera a pasta dist/)
        python criar_aplicativo.py --simular  (só mostra o comando que seria executado)
O executável é feito para o sistema em que você roda o script (Windows gera .exe, macOS gera .app)."""
import importlib.util
import subprocess
import sys
from pathlib import Path

NOME = "CalendarioAcademico"
PACOTES_COM_DADOS = ("rapidocr_onnxruntime", "pdfplumber", "pdfminer", "pypdf")   # só os que estiverem instalados


def tem_pyinstaller() -> bool:
    return importlib.util.find_spec("PyInstaller") is not None


def montar_comando() -> list[str]:
    raiz = Path(__file__).resolve().parent
    comando = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NOME,
               "--distpath", str(raiz / "dist"), "--workpath", str(raiz / "build"), "--specpath", str(raiz / "build"),
               "--paths", str(raiz)]
    comando.append("--onedir" if sys.platform == "darwin" else "--onefile")           # no macOS gera o .app
    for pacote in PACOTES_COM_DADOS:
        if importlib.util.find_spec(pacote):
            comando += ["--collect-all", pacote]                                      # inclui modelos/arquivos de dados
    comando.append(str(raiz / "CalendarioAcademico.pyw"))
    return comando


def principal(argumentos: list[str]) -> int:
    comando = montar_comando()
    if "--simular" in argumentos:
        print(" ".join(comando))
        return 0
    if not tem_pyinstaller():
        print("O PyInstaller não está instalado. Instale com:  pip install pyinstaller  e rode este script de novo.")
        return 1
    print("Criando o aplicativo (pode levar alguns minutos)...")
    codigo = subprocess.run(comando).returncode
    if codigo == 0:
        final = {"win32": f"{NOME}.exe", "darwin": f"{NOME}.app"}.get(sys.platform, NOME)
        print(f"\nPronto! O aplicativo está em: {Path(__file__).resolve().parent / 'dist' / final}")
    return codigo


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
