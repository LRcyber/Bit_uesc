import socket
import threading
import json
import argparse
import time
import uuid
import os
import csv

def make_argparser():
    p = argparse.ArgumentParser(description='BitUESC integrated node (server + ring)')
    p.add_argument('--id', required=True, help='ID do nó (ex: node1)')
    p.add_argument('--host', default='0.0.0.0', help='Host para escutar')
    p.add_argument('--bank_port', type=int, required=True, help='Porta do servidor bancário')
    p.add_argument('--ring_port', type=int, required=True, help='Porta do anel')
    p.add_argument('--next_host', required=True, help='Host do próximo nó no anel')
    p.add_argument('--next_port', type=int, required=True, help='Porta do anel do próximo nó')
    return p

args = make_argparser().parse_args()
NODE_ID = args.id
LISTEN_HOST = args.host
BANK_PORT = args.bank_port
RING_PORT = args.ring_port
NEXT_HOST = args.next_host
NEXT_PORT = args.next_port

# Diretórios e arquivos
BLOCKS_DIR = f"blocks_{NODE_ID}"
ARQUIVO_CONTAS = f"contas_{NODE_ID}.csv"
LAST_BLOCK_ID_FILE = os.path.join(BLOCKS_DIR, "last_block_id.txt")
os.makedirs(BLOCKS_DIR, exist_ok=True)

# Estado compartilhado entre servidor bancário e anel
contas = {}
transaction_buffer = []
seen_tx_ids = set()
seen_block_ids = set()
rejected_blocks = set()  # NOVO: rastreia blocos rejeitados
TRANSACTIONS_PER_BLOCK = 6

# Locks
state_lock = threading.RLock()
next_sock = None
next_sock_lock = threading.Lock()

# === FUNÇÕES DE MINERAÇÃO ===
def fatores_primos(n):
    """Calcula os fatores primos de um número"""
    if n <= 1:
        return []
    factors = []
    while n % 2 == 0:
        factors.append(2)
        n //= 2
    i = 3
    while i * i <= n:
        while n % i == 0:
            factors.append(i)
            n //= i
        i += 2
    if n > 2:
        factors.append(n)
    return factors

def calcular_id_bloco(conteudo_bloco: str) -> int:
    """Calcula o ID do bloco baseado no conteúdo"""
    ID_LIM = 65535
    mult = 1
    conteudo_limpo = conteudo_bloco.rstrip()
    lista_de_bytes = conteudo_limpo.encode('utf-8')
    for byte_val in lista_de_bytes:
        byte_ajustado = byte_val if byte_val != 0 else 256
        mult = (mult * byte_ajustado) % ID_LIM
    return mult

def verificar_bloco_minerado(conteudo_bloco: str, block_num: int = None) -> bool:
    """
    Verifica se um bloco foi corretamente minerado.
    
    Validações:
    1. Estrutura do bloco (pelo menos 2 linhas finais: ID e fatores)
    2. ID calculado corresponde ao ID anexado
    3. Fatores primos estão corretos
    4. Produto dos fatores equals o ID
    
    Retorna True se válido, False caso contrário
    """
    linhas = conteudo_bloco.strip().splitlines()
    
    # Validação 1: Estrutura mínima
    if len(linhas) < 2:
        print(f"[{NODE_ID}] ❌ VERIFICAÇÃO FALHOU (Bloco {block_num}): Estrutura incompleta - menos de 2 linhas")
        return False
    
    try:
        # Extrai ID e fatores das últimas duas linhas
        id_anexado = int(linhas[-2].strip())
        fatores_anexados_str = linhas[-1].strip()
        fatores_anexados = [int(f) for f in fatores_anexados_str.split(',') if f.strip()]
    except (ValueError, IndexError) as e:
        print(f"[{NODE_ID}] ❌ VERIFICAÇÃO FALHOU (Bloco {block_num}): Formato inválido - {e}")
        return False
    
    # Validação 2: ID deve estar no range válido
    if id_anexado < 0 or id_anexado > 65535:
        print(f"[{NODE_ID}] ❌ VERIFICAÇÃO FALHOU (Bloco {block_num}): ID fora do range (0-65535): {id_anexado}")
        return False
    
    # Validação 3: Recalcula o ID do bloco
    conteudo_original = "\n".join(linhas[:-2])
    id_recalculado = calcular_id_bloco(conteudo_original)
    
    if id_recalculado != id_anexado:
        print(f"[{NODE_ID}] ❌ VERIFICAÇÃO FALHOU (Bloco {block_num}): ID recalculado ({id_recalculado}) != anexado ({id_anexado})")
        return False
    
    # Validação 4: Verifica os fatores primos
    fatores_recalculados = fatores_primos(id_recalculado)
    
    if fatores_recalculados != fatores_anexados:
        print(f"[{NODE_ID}] ❌ VERIFICAÇÃO FALHOU (Bloco {block_num}): Fatores incorretos")
        print(f"    Esperado: {fatores_recalculados}")
        print(f"    Recebido: {fatores_anexados}")
        return False
    
    # Validação 5: Verifica se o produto dos fatores resulta no ID
    produto = 1
    for f in fatores_anexados:
        produto *= f
    
    if produto != id_anexado:
        print(f"[{NODE_ID}] ❌ VERIFICAÇÃO FALHOU (Bloco {block_num}): Produto dos fatores ({produto}) != ID ({id_anexado})")
        return False
    
    # Todas as validações passaram!
    print(f"[{NODE_ID}] ✅ VERIFICAÇÃO SUCESSO (Bloco {block_num}): ID={id_anexado}, Fatores={fatores_anexados}")
    return True

# === FUNÇÕES DE CONTA ===
def carregar_contas():
    contas_local = {}
    if os.path.exists(ARQUIVO_CONTAS):
        with open(ARQUIVO_CONTAS, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for linha in reader:
                if len(linha) == 2:
                    numero_conta, saldo = linha
                    try:
                        contas_local[numero_conta] = float(saldo)
                    except:
                        contas_local[numero_conta] = 0.0
    return contas_local

def salvar_contas(contas_param):
    with open(ARQUIVO_CONTAS, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["numero_conta", "saldo"])
        for conta, saldo in contas_param.items():
            writer.writerow([conta, saldo])

def read_last_block_id():
    if os.path.exists(LAST_BLOCK_ID_FILE):
        with open(LAST_BLOCK_ID_FILE, "r", encoding="utf-8") as f:
            try:
                return int(f.read().strip())
            except:
                return -1
    return -1

def write_last_block_id(bid):
    with open(LAST_BLOCK_ID_FILE, "w", encoding="utf-8") as f:
        f.write(str(bid))

# Inicializa estado
contas = carregar_contas()
last_block_id = read_last_block_id()

def format_signed(value: float) -> str:
    return f"+{value:.2f}" if value >= 0 else f"{value:.2f}"

# === REPLICAÇÃO E MINERAÇÃO ===
def broadcast_transaction(tipo: str, conta: str, valor: float, conta_destino: str = None):
    tx_id = str(uuid.uuid4())
    tx_data = {
        'tipo': tipo,
        'conta': conta,
        'valor': valor,
        'conta_destino': conta_destino,
        'origin': NODE_ID
    }
    msg = {
        'type': 'TX',
        'tx_id': tx_id,
        'payload': json.dumps(tx_data)
    }
    print(f"[{NODE_ID}] 📤 Enviando transação {tipo} para o anel: {tx_id}")
    process_transaction_message(msg)

def process_transaction_message(msg):
    """Processa uma transação recebida (própria ou do anel)"""
    global transaction_buffer
    tx_id = msg.get('tx_id')
    if not tx_id:
        return

    with state_lock:
        if tx_id in seen_tx_ids:
            return
        seen_tx_ids.add(tx_id)

        payload = json.loads(msg.get('payload'))
        tipo = payload['tipo']
        conta = payload['conta']
        valor = payload['valor']
        origem = payload.get('origin')

        print(f"[{NODE_ID}] 📥 Processando TX {tx_id[:8]}... tipo={tipo} conta={conta} valor={valor} (origin={origem})")

        # Aplica a transação localmente
        if tipo == 'CRIAR_CONTA':
            if conta not in contas:
                contas[conta] = 0.0
                salvar_contas(contas)

        elif tipo == 'DEPOSITAR':
            if conta in contas:
                contas[conta] += float(valor)
                salvar_contas(contas)
                transaction_buffer.append(f"T{conta}{format_signed(float(valor))}")

        elif tipo == 'SACAR':
            if conta in contas:
                contas[conta] -= float(valor)
                salvar_contas(contas)
                transaction_buffer.append(f"T{conta}{format_signed(-float(valor))}")

        elif tipo == 'TRANSFERIR':
            conta_destino = payload.get('conta_destino')
            if conta in contas and conta_destino in contas:
                contas[conta] -= float(valor)
                contas[conta_destino] += float(valor)
                salvar_contas(contas)
                transaction_buffer.append(f"T{conta}{format_signed(-float(valor))}")
                transaction_buffer.append(f"T{conta_destino}{format_signed(float(valor))}")

        # Verifica se deve criar bloco
        if len(transaction_buffer) >= TRANSACTIONS_PER_BLOCK:
            print(f"[{NODE_ID}] 📦 Buffer cheio ({len(transaction_buffer)} txs) - Criando bloco...")
            create_and_mine_block()

    # Encaminha para o próximo nó
    forward_message(msg)

def create_and_mine_block():
    """Cria e minera um novo bloco"""
    global last_block_id, transaction_buffer

    new_id = last_block_id + 1

    # Monta conteúdo do bloco
    conteudo = f"{new_id}\n"

    # Adiciona transações
    for tx in transaction_buffer[:TRANSACTIONS_PER_BLOCK]:
        conteudo += f"{tx}\n"

    # Adiciona saldos finais
    for conta_num in sorted(contas.keys(), key=lambda x: int(x) if x.isdigit() else x):
        saldo = contas[conta_num]
        conteudo += f"S{conta_num}{format_signed(saldo)}\n"

    # Calcula ID e fatores primos (MINERAÇÃO)
    bloco_id = calcular_id_bloco(conteudo)
    fatores = fatores_primos(bloco_id)
    fatores_str = ",".join(map(str, fatores))

    # Adiciona prova de trabalho
    conteudo += f"{bloco_id}\n"
    conteudo += f"{fatores_str}\n"

    # Salva localmente
    block_filename = os.path.join(BLOCKS_DIR, f"block_{new_id}.txt")
    with open(block_filename, "w", encoding="utf-8") as f:
        f.write(conteudo)

    print(f"[{NODE_ID}] ⛏️  BLOCO {new_id} MINERADO: ID={bloco_id} Fatores={fatores_str}")

    # Atualiza estado
    last_block_id = new_id
    write_last_block_id(last_block_id)
    transaction_buffer = transaction_buffer[TRANSACTIONS_PER_BLOCK:]

    # Broadcast do bloco para o anel
    msg = {
        'type': 'BLOCK',
        'block_num': new_id,
        'content': conteudo
    }
    forward_message(msg)

def process_block_message(msg):
    """
    Processa um bloco recebido do anel.
    
    CRITÉRIO DE ACEITAÇÃO:
    1. Verifica se já vimos este bloco (evita loops)
    2. Verifica se foi rejeitado anteriormente
    3. VALIDA A PROVA DE TRABALHO (ID e fatores primos)
    4. Se válido: salva localmente e PROPAGA para o próximo nó
    5. Se inválido: DESCARTA e NÃO propaga
    """
    global last_block_id
    
    block_num = msg.get('block_num')
    content = msg.get('content')

    # Converte block_num para int
    try:
        block_num = int(block_num)
    except Exception:
        print(f"[{NODE_ID}] ⚠️  Block_num inválido recebido: {block_num}")
        return

    with state_lock:
        # Verifica se já processamos este bloco
        if block_num in seen_block_ids:
            print(f"[{NODE_ID}] 🔄 Bloco {block_num} já visto anteriormente (ignorando)")
            return
        
        # Verifica se já rejeitamos este bloco
        if block_num in rejected_blocks:
            print(f"[{NODE_ID}] 🚫 Bloco {block_num} já foi rejeitado anteriormente (ignorando)")
            return

        print(f"[{NODE_ID}] 📦 Bloco {block_num} recebido do anel")
        print(f"[{NODE_ID}] 🔍 Iniciando verificação da prova de trabalho...")

        # VALIDAÇÃO DA PROVA DE TRABALHO
        if verificar_bloco_minerado(content, block_num):
            # ✅ BLOCO VÁLIDO - Salva e propaga
            block_filename = os.path.join(BLOCKS_DIR, f"block_{block_num}.txt")
            with open(block_filename, "w", encoding="utf-8") as f:
                f.write(content)

            print(f"[{NODE_ID}] ✅ Bloco {block_num} ACEITO e salvo em {block_filename}")
            seen_block_ids.add(block_num)

            # Atualiza last_block_id se necessário
            if block_num > last_block_id:
                last_block_id = block_num
                write_last_block_id(last_block_id)

            # 🔄 PROPAGA para o próximo nó do anel
            print(f"[{NODE_ID}] 🔄 Propagando bloco {block_num} para o próximo nó...")
            forward_message(msg)
            
        else:
            # ❌ BLOCO INVÁLIDO - Descarta e NÃO propaga
            print(f"[{NODE_ID}] ❌ Bloco {block_num} REJEITADO: prova de trabalho inválida!")
            print(f"[{NODE_ID}] 🚫 Bloco {block_num} NÃO será propagado na rede")
            rejected_blocks.add(block_num)
            # NÃO chama forward_message() - bloco é descartado aqui

# === REDE - ANEL ===
def connect_to_next():
    global next_sock
    while True:
        with next_sock_lock:
            if next_sock:
                pass
            else:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(5)
                    s.connect((NEXT_HOST, NEXT_PORT))
                    s.settimeout(None)
                    next_sock = s
                    print(f"[{NODE_ID}] 🔗 Conectado ao próximo nó {NEXT_HOST}:{NEXT_PORT}")
                except Exception:
                    next_sock = None
        time.sleep(2)

def send_message_over_sock(s, msg_obj):
    try:
        raw = json.dumps(msg_obj) + '\n'
        s.sendall(raw.encode('utf-8'))
    except Exception as e:
        print(f"[{NODE_ID}] Erro ao enviar: {e}")
        raise

def forward_message(msg):
    """Encaminha uma mensagem para o próximo nó do anel"""
    global next_sock
    with next_sock_lock:
        s = next_sock
    if not s:
        print(f"[{NODE_ID}] ⚠️  Não conectado ao próximo nó - mensagem não enviada")
        return
    try:
        send_message_over_sock(s, msg)
    except Exception:
        with next_sock_lock:
            try:
                next_sock.close()
            except:
                pass
            next_sock = None

def handle_ring_conn(conn, addr):
    with conn:
        try:
            f = conn.makefile('r', encoding='utf-8', newline='\n')
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    mtype = msg.get('type')
                    if mtype == 'TX':
                        process_transaction_message(msg)
                    elif mtype == 'BLOCK':
                        process_block_message(msg)
                except Exception as e:
                    print(f"[{NODE_ID}] Erro ao processar mensagem: {e}")
        except Exception:
            pass

def ring_server_thread():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((LISTEN_HOST, RING_PORT))
    s.listen()
    print(f"[{NODE_ID}] 🔄 Servidor do anel escutando em {LISTEN_HOST}:{RING_PORT}")
    while True:
        conn, addr = s.accept()
        t = threading.Thread(target=handle_ring_conn, args=(conn, addr), daemon=True)
        t.start()

# === SERVIDOR BANCÁRIO ===
def atender_cliente_bancario(conexao, endereco):
    try:
        data = conexao.recv(4096)
        if not data:
            return
        try:
            msg = data.decode('utf-8').strip()
        except:
            msg = data.decode(errors='ignore').strip()
        if msg:
            partes = msg.split(";")
            comando = partes[0]
            resposta = "Comando inválido!"

            with state_lock:
                if comando == "CRIAR_CONTA":
                    numero_conta = partes[1]
                    if numero_conta in contas:
                        resposta = f"Conta {numero_conta} já existe!"
                    else:
                        broadcast_transaction('CRIAR_CONTA', numero_conta, 0.0)
                        resposta = f"Conta {numero_conta} criada. Replicando..."

                elif comando == "CONSULTAR_SALDO":
                    numero_conta = partes[1]
                    if numero_conta in contas:
                        saldo = contas[numero_conta]
                        resposta = f"Saldo da conta {numero_conta}: {saldo:.2f} BitUESC."
                    else:
                        resposta = "Conta não encontrada!"

                elif comando == "DEPOSITAR":
                    numero_conta = partes[1]
                    valor = float(partes[2])
                    if numero_conta in contas:
                        broadcast_transaction('DEPOSITAR', numero_conta, valor)
                        resposta = f"Depósito de {valor:.2f} BitUESC em processamento. Replicando..."
                    else:
                        resposta = "Conta não encontrada!"

                elif comando == "SACAR":
                    numero_conta = partes[1]
                    valor = float(partes[2])
                    if numero_conta in contas:
                        if contas[numero_conta] >= valor:
                            broadcast_transaction('SACAR', numero_conta, valor)
                            resposta = f"Saque de {valor:.2f} BitUESC em processamento. Replicando..."
                        else:
                            resposta = f"Saldo insuficiente na conta {numero_conta}."
                    else:
                        resposta = "Conta não encontrada!"

                elif comando == "TRANSFERIR":
                    origem = partes[1]
                    destino = partes[2]
                    valor = float(partes[3])
                    if origem not in contas:
                        resposta = "Conta de origem não encontrada!"
                    elif destino not in contas:
                        resposta = "Conta de destino não encontrada!"
                    elif contas[origem] < valor:
                        resposta = f"Saldo insuficiente na conta {origem}."
                    else:
                        broadcast_transaction('TRANSFERIR', origem, valor, destino)
                        resposta = f"Transferência de {valor:.2f} BitUESC em processamento. Replicando..."

            conexao.send(resposta.encode())
    except Exception as e:
        print(f"[{NODE_ID}] Erro com cliente {endereco}: {e}")
    finally:
        conexao.close()

def bank_server_thread():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((LISTEN_HOST, BANK_PORT))
    s.listen()
    print(f"[{NODE_ID}] 🏦 Servidor bancário escutando em {LISTEN_HOST}:{BANK_PORT}")
    while True:
        conexao, endereco = s.accept()
        t = threading.Thread(target=atender_cliente_bancario, args=(conexao, endereco), daemon=True)
        t.start()

# === CONSOLE INTERATIVO ===
def inject_invalid_block():
    """Injeta um bloco inválido para testar a validação"""
    global last_block_id
    
    fake_id = 9999
    print(f"\n[{NODE_ID}] 🧪 TESTE: Injetando bloco INVÁLIDO {fake_id} na rede...")
    
    # Cria conteúdo com fatores PROPOSITALMENTE ERRADOS
    conteudo = f"{fake_id}\n"
    conteudo += "T123+50.00\n"
    conteudo += "S123+50.00\n"
    conteudo += "12345\n"  # ID falso
    conteudo += "999,888,777\n"  # Fatores INCORRETOS propositalmente
    
    msg = {
        'type': 'BLOCK',
        'block_num': fake_id,
        'content': conteudo
    }
    
    print(f"[{NODE_ID}] 📤 Enviando bloco inválido para o anel...")
    forward_message(msg)
    print(f"[{NODE_ID}] ✓ Bloco inválido enviado! Aguarde as rejeições nos logs...\n")

def console_thread():
    print(f"\n[{NODE_ID}] Console ativo. Comandos: /contas, /buffer, /blocos, /status, /rejected, /test_invalid")
    while True:
        try:
            line = input()
        except EOFError:
            break
        line = line.strip()

        if line == '/test_invalid':
            inject_invalid_block()

        elif line == '/contas':
            with state_lock:
                print(f"\n[{NODE_ID}] === CONTAS ===")
                for conta, saldo in sorted(contas.items()):
                    print(f"  Conta {conta}: {saldo:.2f} BitUESC")

        elif line == '/buffer':
            with state_lock:
                print(f"\n[{NODE_ID}] === BUFFER ({len(transaction_buffer)}/6 transações) ===")
                for i, tx in enumerate(transaction_buffer, 1):
                    print(f"  {i}. {tx}")

        elif line == '/blocos':
            print(f"\n[{NODE_ID}] === BLOCOS SALVOS ===")
            files = sorted([f for f in os.listdir(BLOCKS_DIR) if f.startswith('block_')])
            for f in files:
                print(f"  {f}")

        elif line == '/rejected':
            with state_lock:
                print(f"\n[{NODE_ID}] === BLOCOS REJEITADOS ===")
                if rejected_blocks:
                    for bid in sorted(rejected_blocks):
                        print(f"  Bloco {bid}")
                else:
                    print("  Nenhum bloco rejeitado")

        elif line == '/status':
            with state_lock:
                print(f"\n[{NODE_ID}] === STATUS ===")
                print(f"  Contas: {len(contas)}")
                print(f"  Buffer: {len(transaction_buffer)}/6")
                print(f"  TXs vistas: {len(seen_tx_ids)}")
                print(f"  Blocos vistos: {len(seen_block_ids)}")
                print(f"  Blocos rejeitados: {len(rejected_blocks)}")
                print(f"  Último bloco: {last_block_id}")

# === MAIN ===
def main():
    t_bank = threading.Thread(target=bank_server_thread, daemon=True)
    t_bank.start()

    t_ring = threading.Thread(target=ring_server_thread, daemon=True)
    t_ring.start()

    t_connect = threading.Thread(target=connect_to_next, daemon=True)
    t_connect.start()

    t_console = threading.Thread(target=console_thread, daemon=True)
    t_console.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n[{NODE_ID}] Encerrando...")

if __name__ == '__main__':
    main()