import re
import sys

from Agent import LuciosAgent


def _formatar_para_terminal(texto: str) -> str:
    """Renderiza negrito Markdown como ANSI em terminais interativos."""
    if not sys.stdout.isatty():
        return texto
    return re.sub(r"\*\*(.+?)\*\*", "\033[1m\\1\033[0m", texto)

if __name__ == "__main__":
    lucios = LuciosAgent()
    print("Olá! Eu sou o Lucios, como posso ajudá-lo hoje?")
    while True:
        print("\n--------------------------------\n")
        user_input = input("Você: ")
        print("\n--------------------------------\n")
        if user_input.lower() in ["sair", "exit", "quit"]:
            print(lucios.end_conversation())
            print("Encerrando a conversa. Até logo!")
            break
        elif user_input.lower() == "limpar":
            print(lucios.chat("limpar"))
            break

        response = lucios.chat(user_input)
        print(f"Lucios: {_formatar_para_terminal(response)}")
