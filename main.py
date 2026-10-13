from Agent import LuciosAgent

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
            lucios.clear_memory()
            print("Memória do agente limpa.")
            break

        response = lucios.chat(user_input)
        print(f"Lucios: {response}")