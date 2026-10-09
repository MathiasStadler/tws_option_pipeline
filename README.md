# TWS Option Pipeline

Pipeline für Option Greeks (Delta, Gamma, Theta, Vega, IV) + Market Data (Bid/Ask/Volume) via IBKR TWS Socket API (Port 7496).

## Struktur

```
tws_option_pipeline/
├── README.md
├── venv/                    # Python virtual environment
└── src/
    └── tws_pipeline.py      # Main pipeline script
```

## Voraussetzungen

1. **TWS läuft auf Remote-Server** (192.168.178.75) mit API aktiviert:
   - File → Global Configuration → API → Settings
   - ☑ Enable ActiveX and Socket Clients
   - Port: 7496
   - ☑ Read-Only API (für Paper Trading)

2. **SSH Tunnel** von lokal zu Remote:
   ```bash
   sshpass -p trapapa ssh -L 7496:localhost:7496 -N -f -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null trapapa@192.168.178.75
   ```

## Installation

```bash
cd /home/hermes/tws_option_pipeline
# venv already created with ib_insync installed
```

## Ausführung

```bash
# 1. SSH Tunnel aufbauen (einmalig pro Session)
sshpass -p trapapa ssh -L 7496:localhost:7496 -N -f -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null trapapa@192.168.178.75

# 2. Pipeline starten
# Syntax: python3 src/tws_pipeline.py <SYMBOL> [MONTH_INDEX] [EXCHANGE] [CURRENCY]

# US Aktien (CROX, AAPL, etc.)
/home/hermes/tws_option_pipeline/venv/bin/python3 src/tws_pipeline.py CROX 2 SMART USD
/home/hermes/tws_option_pipeline/venv/bin/python3 src/tws_pipeline.py AAPL 2 SMART USD

# Europäische Aktien (wenn Market Data Subscription vorhanden)
/home/hermes/tws_option_pipeline/venv/bin/python3 src/tws_pipeline.py ALV 1 XETRA EUR
/home/hermes/tws_option_pipeline/venv/bin/python3 src/tws_pipeline.py ASML 1 AEB EUR
```

### Parameter

| Parameter | Beschreibung | Standard |
|-----------|--------------|----------|
| SYMBOL | Ticker Symbol (z.B. CROX, AAPL, ALV) | - |
| MONTH_INDEX | 0=nächste Expir., 1=übernächste, 2=überübernächste | 0 |
| EXCHANGE | Börse (SMART, XETRA, AEB, etc.) | SMART |
| CURRENCY | Währung (USD, EUR) | USD |

### Month Index Beispiele für CROX:
- `0` = 2026-10-16 (wöchentlich)
- `1` = 2026-11-20 (monatlich)
- `2` = 2026-12-18 (monatlich) ← **empfohlen für Standard-Monatsoptionen**
- `3` = 2027-01-15

## Output

CSV-Datei in `/home/hermes/tws_option_pipeline/src/tws_option_contracts_<SYMBOL>_<TIMESTAMP>.csv`

**Spalten (23):**
- conid, symbol, right, expiration, strike, multiplier
- bid, ask, last, close, volume
- delta, gamma, theta, vega, impliedVol
- bidSize, askSize, high, low, openPrice, openInterest

**Filter:** Nur PUTs mit Delta -0.50 bis -0.10

## Bekannte Limitationen

- **OpenInterest** = `nan` (Delayed Data bei Paper Trading)
- Client IDs können erschöpft sein → TWS neu starten oder `clientId` in `connect_ib()` ändern
- Für europäische Aktien (ALV, ASML) braucht man Market Data Subscription

## work sample

/home/hermes/tws_option_pipeline/venv/bin/python3 /home/hermes/tws_option_pipeline/src/close_position.py

-close
/home/hermes/tws_option_pipeline/venv/bin/python3 /home/hermes/tws_option_pipeline/src/multi_symbol_batch.py ANET 0 1 S

- open
/home/hermes/tws_option_pipeline/venv/bin/python3 /home/hermes/tws_option_pipeline/src/multi_symbol_batch.py ANET 0 1 SMART USD

# 3 Option Chains scannen
/home/hermes/tws_option_pipeline/venv/bin/python3 /home/hermes/tws_option_pipeline/src/multi_symbol_batch.py CRWD --chains 3 0 1 SMART USD

# Kurzform
/home/hermes/tws_option_pipeline/venv/bin/python3 /home/hermes/tws_option_pipeline/src/multi_symbol_batch.py CRWD --num-chains 3 0 1 SMART USD

# Kombiniert mit Delta-Range und Manual Mode
/home/hermes/tws_option_pipeline/venv/bin/python3 /home/hermes/tws_option_pipeline/src/multi_symbol_batch.py CRWD --chains 5 --delta-min -0.30 --delta-max -0.10 -m 0 1 SMART USD


/home/hermes/tws_option_pipeline/venv/bin/python3 /home/hermes/tws_option_pipeline/src/multi_symbol_batch.py FAST --chains 3 --delta-min -0.30 --delta-max -0.10 -m 0 1 SMART USD