import socket
import argparse

def menu():
    print("\n===== Sistema BitUESC (Distribuído) =====")
    print("1 - Criar conta")
    print("2 - Consultar saldo")
    print("3 - Depositar")
    print("4 - Sacar")
    print("5 - Transferir")
    print("9 - Trocar de servidor")
    print("0 - Sair")
    return input("Escolha uma opção: ")

def escolher_servidor(default_host=None, default_port=None):
    print("\n=== Escolha o servidor ===")
    print("1 - Node A (192.168.235.129:6001)")
    print("2 - Node B (192.168.235.130:6002)")
    print("3 - Node C (192.168.235.131:6003)")
    print("4 - Customizado")
    if default_host and default_port:
        print(f"5 - Padrão inicial ({default_host}:{default_port})")
    
    opcao = input("Escolha: ")

    if opcao == "1":
        return "192.168.235.129", 6001
    elif opcao == "2":
        return "192.168.235.130", 6002
    elif opcao == "3":
        return "192.168.235.131", 6003
    elif opcao == "4":
        host = input("Digite o host: ")
        porta = int(input("Digite a porta bancária: "))
        return host, porta
    elif opcao == "5" and default_host and default_port:
        return default_host, default_port
    else:
        print("Opção inválida. Usando Node A...")
        return "192.168.235.129", 6001

def enviar_mensagem(host, porta, msg):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as cliente:
            cliente.settimeout(5)
            cliente.connect((host, porta))
            cliente.send(msg.encode())
            return cliente.recv(1024).decode()

    except ConnectionRefusedError:
        return f"⚠️  Não foi possível conectar ao servidor {host}:{porta} (offline?)"
    except socket.timeout:
        return f"⚠️  Tempo de conexão esgotado (timeout)."
    except Exception as e:
        return f"⚠️  Erro inesperado: {e}"

def cliente():
    # Parser de argumentos de linha de comando
    parser = argparse.ArgumentParser(description='Cliente BitUESC')
    parser.add_argument('--server_host', type=str, default=None, 
                        help='Host do servidor inicial (ex: 192.168.235.129)')
    parser.add_argument('--server_port', type=int, default=None, 
                        help='Porta do servidor inicial (ex: 6001)')
    args = parser.parse_args()

    # Se argumentos foram fornecidos, usa-os como padrão inicial
    if args.server_host and args.server_port:
        host = args.server_host
        porta = args.server_port
        print(f"\n✓ Conectado ao servidor {host}:{porta}")
    else:
        host, porta = escolher_servidor()
        print(f"\n✓ Conectado ao servidor {host}:{porta}")

    initial_host = args.server_host
    initial_port = args.server_port

    while True:
        opcao = menu()

        if opcao == "1":
            numero = input("Número da nova conta: ")
            msg = f"CRIAR_CONTA;{numero}"

        elif opcao == "2":
            numero = input("Número da conta: ")
            msg = f"CONSULTAR_SALDO;{numero}"

        elif opcao in ["3", "4"]:
            numero = input("Número da conta: ")
            try:
                valor = float(input("Valor: "))
            except ValueError:
                print("⚠️  Valor inválido.")
                continue

            if opcao == "3":
                msg = f"DEPOSITAR;{numero};{valor}"
            else:
                msg = f"SACAR;{numero};{valor}"

        elif opcao == "5":
            origem = input("Conta de origem: ")
            destino = input("Conta de destino: ")
            try:
                valor = float(input("Valor: "))
            except ValueError:
                print("⚠️  Valor inválido.")
                continue
            msg = f"TRANSFERIR;{origem};{destino};{valor}"

        elif opcao == "9":
            host, porta = escolher_servidor(initial_host, initial_port)
            print(f"\n✓ Agora conectado ao servidor {host}:{porta}")
            continue

        elif opcao == "0":
            print("Saindo...")
            break

        else:
            print("⚠️  Opção inválida!")
            continue

        resposta = enviar_mensagem(host, porta, msg)
        print(f"\n[Servidor {host}:{porta}] → {resposta}")

if __name__ == "__main__":
    cliente()