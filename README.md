# BitUESC: Distributed Banking System with Ring Replication

Educational distributed system written in Python (UESC coursework). Multiple nodes are connected in a ring and replicate bank transactions over TCP sockets. Transactions are grouped into blocks that are sealed with a simplified proof-of-work and validated by every node.

## Features

- Bank server over TCP: create account, check balance, deposit, withdraw, transfer
- Ring topology: each node forwards transactions and blocks to the next node
- Blocks of 6 transactions, saved per node in `blocks_<node_id>/`
- Simplified proof-of-work: block ID (hash of the content, modulo 65535) plus its prime factorization
- Block validation: invalid blocks are rejected and not propagated
- Interactive node console and a CLI client with server switching

## Files

| File | Description |
|------|-------------|
| `server.py` | Node: bank server + ring communication + block creation/validation |
| `client.py` | Menu-based client that talks to any node's bank port |

## How to run (3 nodes on localhost)

Open three terminals:

```bash
python server.py --id node1 --bank_port 6001 --ring_port 7001 --next_host 127.0.0.1 --next_port 7002
python server.py --id node2 --bank_port 6002 --ring_port 7002 --next_host 127.0.0.1 --next_port 7003
python server.py --id node3 --bank_port 6003 --ring_port 7003 --next_host 127.0.0.1 --next_port 7001
```

Then run the client in a fourth terminal:

```bash
python client.py --server_host 127.0.0.1 --server_port 6001
```

Requires Python 3 (standard library only).

## Node console commands

`/contas`, `/buffer`, `/blocos`, `/status`, `/rejected`, `/test_invalid`

`/test_invalid` injects a block with wrong factors to show that the network rejects it.

## Limitations

This is a teaching project, not a production blockchain: the proof-of-work has no adjustable difficulty, there is no consensus protocol, and the client's built-in server list uses fixed IPs from a lab VM setup (use `--server_host`/`--server_port` or the "Custom" option).
