# Lumen Dark

A dark pool order book on the Stellar network with on-chain settlement.

## Overview

Lumen Dark is a decentralized dark pool that enables private trading of Stellar-based tokens. Orders are matched off-chain for privacy, while settlement occurs on-chain via Soroban smart contracts for security and transparency.

**Key Features:**
- Private order book (orders not visible to other participants)
- Price-time priority matching
- On-chain settlement via Soroban smart contracts
- Cryptographic request signing with Stellar keypairs

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              STELLAR NETWORK                                │
│  ┌─────────────────────┐    ┌─────────────────────┐                        │
│  │   Token A Contract  │    │   Token B Contract  │                        │
│  └──────────┬──────────┘    └──────────┬──────────┘                        │
│             └──────────┬───────────────┘                                    │
│                        ▼                                                    │
│            ┌───────────────────────┐                                        │
│            │  OrderBook Contract   │                                        │
│            │  • deposit()          │◄─── User authorizes transfer           │
│            │  • withdraw()         │◄─── Admin authorizes                   │
│            │  • settle()           │◄─── Admin authorizes                   │
│            │  • get_balance()      │                                        │
│            └───────────┬───────────┘                                        │
│                        │ Events                                             │
└────────────────────────┼────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           BACKEND SERVICE                                   │
│  ┌──────────────────┐     ┌──────────────────────────────────────────────┐ │
│  │ Deposit Event    │     │              INCOMING QUEUE                  │ │
│  │ Listener         │────▶│  [deposit] [order] [cancel] [withdraw] ...   │ │
│  │ (Soroban RPC)    │     └──────────────────────┬───────────────────────┘ │
│  └──────────────────┘                            │                         │
│                                                  ▼                         │
│  ┌──────────────────┐     ┌──────────────────────────────────────────────┐ │
│  │ HTTP API         │     │              MAIN EXECUTOR                   │ │
│  │ (FastAPI)        │────▶│  ┌────────────┐  ┌────────────┐              │ │
│  │                  │     │  │ User Store │  │ Order Book │              │ │
│  │ POST /orders     │     │  │ (balances) │  │ (bids/asks)│              │ │
│  │ POST /orders/cancel    │  └────────────┘  └────────────┘              │ │
│  │ POST /withdrawals│     │         │              │                     │ │
│  │ GET /messages/{id}     │         └──────┬───────┘                     │ │
│  └──────────────────┘     │                ▼                             │ │
│                           │       ┌─────────────────┐                    │ │
│                           │       │ Matching Engine │                    │ │
│                           │       └────────┬────────┘                    │ │
│                           └────────────────┼─────────────────────────────┘ │
│                                            ▼                               │
│                           ┌──────────────────────────────────────────────┐ │
│                           │         OUTGOING PROCESSOR                   │ │
│                           │  Submit withdraw() / settle() transactions  │ │
│                           └──────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Testnet Deployment

The following contracts are deployed on Stellar Testnet:

| Contract | Address |
|----------|---------|
| Orderbook | `CDNTW7OWJF7LYWERWLQMUUCUIR5Q4XMFSXCHALRS3V3SN5KRDSCJT2DY` |
| Token A | `CCZXVH2AJO3X3ZIUXSN2VR5I3TZ4MNDUAI3JYDMTPOLXMCOOIVUMNKFW` |
| Token B | `CDRASGTVJWOQTWCXNXD2YHIHHK2BHUONJMQHHWE25HQMFONWBL4XCYE3` |

## Quick Start

### Prerequisites

- Python 3.9+
- Rust (for contract development)
- Stellar CLI (`stellar`)

### 1. Install Dependencies

```bash
# Backend
cd backend
pip install -e .

# Client
cd ../client
pip install -e .
```

### 2. Start the Backend

```bash
cd backend
ADMIN_SECRET_KEY="your_admin_secret_key" \
ORDERBOOK_CONTRACT_ID="CDNTW7OWJF7LYWERWLQMUUCUIR5Q4XMFSXCHALRS3V3SN5KRDSCJT2DY" \
SOROBAN_RPC_URL="https://soroban-testnet.stellar.org" \
uvicorn lumendark.api.app:app --host 0.0.0.0 --port 8000
```

### 3. Use the Client

```python
import asyncio
from stellar_sdk import Keypair
from lumendark_client import LumenDarkClient

async def main():
    # Create client with your keypair
    keypair = Keypair.from_secret("YOUR_SECRET_KEY")
    client = LumenDarkClient(
        base_url="http://localhost:8000",
        keypair=keypair,
    )

    # Submit a sell order: sell 100 Token A at price 2.0 (200 Token B per 100 Token A)
    message_id = await client.submit_order(
        side="sell",
        price="2.0",
        quantity="100",
    )
    print(f"Order submitted: {message_id}")

    # Check order status
    status = await client.get_status(message_id)
    print(f"Status: {status}")

asyncio.run(main())
```

## API Reference

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /orders` | Submit limit order | Returns `message_id` |
| `POST /orders/cancel` | Cancel order by `order_id` | Returns `message_id` |
| `POST /withdrawals` | Request withdrawal | Returns `message_id` |
| `GET /messages/{message_id}` | Query message status | Returns status details |
| `GET /health` | Health check | Returns `{"status": "healthy"}` |

### Authentication

All requests must be signed with the user's Stellar keypair:

```
X-Stellar-Address: <public_key>
X-Stellar-Signature: <signature_hex>
X-Timestamp: <unix_timestamp>
```

The signature is computed over: `{method}|{path}|{body_sha256}|{timestamp}`

### Order Request

```json
POST /orders
{
  "side": "buy",       // "buy" or "sell"
  "price": "10.5",     // price in Token B per Token A
  "quantity": "100"    // quantity of Token A
}
```

### Withdrawal Request

```json
POST /withdrawals
{
  "asset": "a",        // "a" or "b"
  "amount": "1000000"  // amount in base units (7 decimals)
}
```

## How It Works

### Deposit Flow

1. User calls `deposit()` on the orderbook contract directly
2. Contract transfers tokens from user and emits deposit event
3. Backend's event listener detects deposit and credits user balance

### Order Flow

1. User submits signed order via API
2. Backend validates balance and locks funds (available → liabilities)
3. Matching engine matches against resting orders (price-time priority)
4. For each trade, backend queues settlement transaction
5. Outgoing processor submits `settle()` transaction to contract

### Withdrawal Flow

1. User submits signed withdrawal request via API
2. Backend validates available balance and decreases it
3. Outgoing processor submits `withdraw()` transaction to contract

## Project Structure

```
lumendark/
├── contracts/                      # Soroban smart contract (Rust)
│   └── orderbook/
│       └── src/
│           ├── lib.rs              # Contract entry point
│           ├── types.rs            # DataKey, Asset enum
│           ├── storage.rs          # Storage helpers
│           └── events.rs           # Event emission
├── backend/                        # Python backend service
│   └── lumendark/
│       ├── models/                 # Order, User, Trade, Message
│       ├── storage/                # UserStore, OrderBook, MessageStore
│       ├── matching/               # Matching engine
│       ├── queues/                 # Incoming/Outgoing queues
│       ├── executor/               # MainExecutor, OutgoingProcessor
│       ├── blockchain/             # SorobanClient, EventListener, TransactionSubmitter
│       └── api/                    # FastAPI routes
└── client/                         # Python client library
    └── lumendark_client/
        └── client.py               # LumenDarkClient
```

## Smart Contract Functions

| Function | Auth | Description |
|----------|------|-------------|
| `initialize(admin, asset_a, asset_b)` | Admin | Set up contract with admin and token contracts |
| `deposit(user, asset, amount)` | User | Transfer tokens to contract, emit event |
| `withdraw(user, asset, amount)` | Admin | Transfer tokens back to user |
| `settle(buyer, seller, asset_sold, amount_sold, asset_bought, amount_bought, trade_id)` | Admin | Atomic balance update for trade |
| `get_balance(user, asset)` | None | Query user balance |

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `ADMIN_SECRET_KEY` | Admin keypair secret for signing settlements | Required |
| `ORDERBOOK_CONTRACT_ID` | Deployed orderbook contract address | Testnet default |
| `SOROBAN_RPC_URL` | Soroban RPC endpoint | `https://soroban-testnet.stellar.org` |

## Development

### Build Contract

```bash
cd contracts
stellar contract build
```

### Deploy Contract

```bash
stellar contract deploy \
  --wasm target/wasm32-unknown-unknown/release/orderbook.wasm \
  --source admin \
  --network testnet
```

### Run Tests

```bash
# Backend tests
cd backend
pytest

# Contract tests
cd contracts
cargo test
```

## Security Considerations

- Admin private key must be stored securely (environment variable)
- All API requests require signature verification
- Event deduplication prevents double-counting deposits
- Liability invariant: `liabilities <= available + pending_deposits`
- Atomic settlement updates prevent partial trades

## License

MIT
