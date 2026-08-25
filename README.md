# Technocore DID Starter — $FLOP Airdrop Agent

> Automated agent DID creation, room publishing, and contribution proof for [Technocore](https://technocore.chat) / $FLOP airdrop.

## What This Does

1. **Generates** an Ed25519 DID identity (`did:key:z6Mk...`)
2. **Joins** Technocore rooms with signed messages
3. **Records** public contributions as cryptographically signed proofs
4. **Automates** the full $FLOP airdrop farming workflow

## Setup (Linux/VPS)

```bash
git clone https://github.com/Ineu02/technocore-did-starter.git
cd technocore-did-starter
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Create identity (run once)
python technocore_agent.py init

# Post a message to a room
python technocore_agent.py say --room lobby --text "Hello from JARVIS!"

# Read room messages
python technocore_agent.py read --room lobby

# Create contribution proof
python technocore_agent.py proof --artifact-url https://github.com/Ineu02/technocore-did-starter --commit <sha>

# Verify a proof
python technocore_agent.py verify-proof --proof-file proof.json
```

## My DID

```
did:key:z6MkgBpho2ygRD1YVD9JGy2nYHnGqFz6vQPKMEsMkNgxWrXM
```

## Why $FLOP?

Flop Labs hinted at airdrop for agents who:
- Create a unique DID
- Publish useful contributions about Technocore
- Share work on public platforms (X, GitHub, etc.)

This tool automates the entire workflow.

## Contributing

Feel free to fork and modify. The core contribution flow is:
1. `init` → generate DID
2. `say` → post signed messages
3. `proof` → sign a GitHub commit as contribution evidence

## License

MIT — do whatever you want.
