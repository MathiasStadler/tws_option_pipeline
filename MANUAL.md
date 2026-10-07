# MANUAL.md - Vollständige Anleitung für TWS Option Pipeline

## 1. VORAUSSETZUNGEN

### 1.1 Remote Server (192.168.178.75)
- **TWS (Trader Workstation) installiert und läuft**
- **API aktiviert:**
  ```
  TWS → File → Global Configuration → API → Settings
  ☑ Enable ActiveX and Socket Clients
  ☑ Socket Port: 7496
  ☑ Read-Only API (empfohlen für Paper Trading)
  ☑ Allow connections from localhost only (optional, sicherer)
  ```
- **IBKR Gateway NICHT nötig** (nur für REST Pipeline)
- **User/Pass:** `trapapa` / `trapapa` (für SSH)

### 1.2 Lokaler Rechner
- Python 3.10+
- `sshpass` installiert (`apt install sshpass` oder `brew install hudochenkov/sshpass/sshpass`)
- Netzwerkzugriff auf 192.168.178.75 (Port 22 SSH, Port 7496 TWS)

### 1.3 Projekt-Setup (bereits erledigt)
```bash
cd /home/hermes/tws_option_pipeline
# venv existiert mit ib_insync
```

---

## 2. AUSFÜHRUNG - SCHRITT FÜR SCHRITT

### Schritt 1: SSH Tunnel aufbauen
```bash
# Einmalig pro Terminal-Session
sshpass -p trapapa ssh -L 7496:localhost:7496 -N -f \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  trapapa@192.168.178.75

# Prüfen ob Tunnel läuft:
ss -tlnp | grep 7496
# Sollte zeigen: LISTEN 127.0.0.1:7496 (ssh process)
```

### Schritt 2: Pipeline starten

#### A) TWS Pipeline (HAUPT-Pipeline - empfohlen)
```bash
cd /home/hermes/tws_option_pipeline

# US Aktien
./venv/bin/python3 src/tws_pipeline.py CROX 2 SMART USD
./venv/bin/python3 src/tws_pipeline.py AAPL 2 SMART USD

# Europäische Aktien (brauchen Market Data Subscription!)
./venv/bin/python3 src/tws_pipeline.py ALV 1 XETRA EUR
./venv/bin/python3 src/tws_pipeline.py ASML 1 AEB EUR
./venv/bin/python3 src/tws_pipeline.py SAP 1 XETRA EUR
```

#### B) REST Pipeline (Alternative - braucht IBKR Gateway auf Port 4002)
```bash
# SSH Tunnel für beide Ports
sshpass -p trapapa ssh -L 7496:localhost:7496 -L 4002:localhost:4002 -N -f \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  trapapa@192.168.178.75

# REST Pipeline
./src/full_pipeline.sh CROX
```

#### C) Einzelne Steps (für Debugging)
```bash
# 1. Symbol → underConid + months
echo "CROX" | ./venv/bin/python3 src/08_secdef_pipe.py

# 2. Stock Price
echo "37792836 CROX" | ./venv/bin/python3 src/08_stock_price_pipe.py

# 3. Strikes für Monat
echo "37792836 NOV26 SMART" | ./venv/bin/python3 src/09_secdef_strikes_pipe.py

# 4. Contract Info
echo "37792836 NOV26 110 P SMART" | ./venv/bin/python3 src/10_secdef_info_pipe.py

# 5. Alle PUTs + Greeks + Delta-Filter
cat contracts.csv | ./venv/bin/python3 src/12_write_result_pipe.py
```

---

## 3. PARAMETER ERKLÄRUNG

### TWS Pipeline
```bash
./venv/bin/python3 src/tws_pipeline.py <SYMBOL> [MONTH_INDEX] [EXCHANGE] [CURRENCY]
```

| Parameter | Werte | Erklärung |
|-----------|-------|-----------|
| SYMBOL | CROX, AAPL, ALV, ASML... | Ticker Symbol |
| MONTH_INDEX | 0, 1, 2, 3... | 0=erste Expir., 1=zweite, 2=dritte (monatlich) |
| EXCHANGE | SMART, XETRA, AEB, NYSE... | Börse |
| CURRENCY | USD, EUR | Währung |

**Month Index Beispiele (CROX):**
| Index | Expiration | Typ |
|-------|------------|-----|
| 0 | 2026-10-16 | Wöchentlich |
| 1 | 2026-11-20 | Monatlich |
| **2** | **2026-12-18** | **Monatlich (Standard)** |
| 3 | 2027-01-15 | Monatlich |

### REST Pipeline
```bash
./src/full_pipeline.sh <SYMBOL> [MONTH_INDEX] [EXCHANGE]
```
Standard: Month 0, SMART

---

## 4. OUTPUT

### CSV-Datei
**Pfad:** `/home/hermes/tws_option_pipeline/src/tws_option_contracts_<SYMBOL>_<TIMESTAMP>.csv`

**Spalten (23):**
```
conid, symbol, right, expiration, strike, multiplier,
bid, ask, last, close, volume,
delta, gamma, theta, vega, impliedVol,
bidSize, askSize, high, low, openPrice, openInterest
```

**Filter:** Nur PUTs mit Delta **-0.50 bis -0.10**

### Beispiel Output (CROX 2026-12-18):
```
Strike 90.0:  delta=-0.1061, bid=1.0, ask=1.55, vol=0, iv=0.5257
Strike 95.0:  delta=-0.1518, bid=1.55, ask=2.45, vol=0, iv=0.5136
Strike 100.0: delta=-0.2063, bid=2.45, ask=3.5,  vol=0, iv=0.5040
Strike 105.0: delta=-0.2739, bid=3.8,  ask=4.9,  vol=0, iv=0.4966
Strike 110.0: delta=-0.3462, bid=5.4,  ask=6.7,  vol=0, iv=0.4912
Strike 115.0: delta=-0.4249, bid=7.3,  ask=8.8,  vol=0, iv=0.4876
```

---

## 5. TROUBLESHOOTING

### Problem: "API connection failed: TimeoutError"
**Ursache:** Client IDs erschöpft (TWS merkt sich verwendete IDs)
**Lösung:**
```bash
# Option 1: TWS neu starten (File → Exit → neu starten)
# Option 2: Anderen clientId in tws_pipeline.py Zeile 46 ändern:
# ib.connect('127.0.0.1', 7496, clientId=999, ...)
```

### Problem: "No security definition has been found"
**Ursache:** Strike existiert nicht für diese Expiration
**Lösung:** Script filtert automatisch via `qualifyContracts` - nur Warnungen, keine Fehler

### Problem: SSH Tunnel "Address already in use"
```bash
pkill -f "ssh.*7496"
pkill -f "ssh.*4002"
# Dann Tunnel neu aufbauen
```

### Problem: "Error 10090 - Market data not subscribed"
**Ursache:** Paper Trading Account ohne Market Data Subscription
**Lösung:** Warten (3s Sleep im Script), nur delayed-frozen Daten verfügbar

### Problem: Keine Volume / OpenInterest bei europäischen Aktien
**Ursache:** Keine Market Data Subscription für EU-Börsen
**Lösung:** Subscription in TWS kaufen oder US-Aktien (SMART) nutzen

---

## 6. HÄUFIGE BEISPIELE

### Täglich (CROX monatlich):
```bash
sshpass -p trapapa ssh -L 7496:localhost:7496 -N -f -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null trapapa@192.168.178.75
/home/hermes/tws_option_pipeline/venv/bin/python3 src/tws_pipeline.py CROX 2 SMART USD
```

### Wöchentlich (AAPL):
```bash
/home/hermes/tws_option_pipeline/venv/bin/python3 src/tws_pipeline.py AAPL 0 SMART USD
```

### Europäisch (Allianz - braucht EU Market Data):
```bash
/home/hermes/tws_option_pipeline/venv/bin/python3 src/tws_pipeline.py ALV 1 XETRA EUR
```

---

## 7. DATEIEN ÜBERSICHT

```
/home/hermes/tws_option_pipeline/
├── README.md              # Kurzanleitung
├── MANUAL.md              # Diese Datei
├── venv/                  # Python venv (ib_insync)
└── src/
    ├── tws_pipeline.py    # HAUPT-Pipeline (TWS Socket)
    ├── 08_secdef_pipe.py  # REST: Symbol → conid+months
    ├── 08_stock_price_pipe.py  # REST: Stock price
    ├── 09_secdef_strikes_pipe.py  # REST: Strikes
    ├── 10_secdef_info_pipe.py  # REST: Contract details
    ├── 12_write_result_pipe.py  # REST: Greeks + Filter
    ├── 13_authenticate_market_data_pipe.py  # REST Auth
    ├── full_pipeline.sh   # Komplette REST Pipeline
    └── fetch_all_puts_loop.sh  # Bash Loop Contracts
```

---

## 8. QUICK START (Copy-Paste)

```bash
# 1. Tunnel
sshpass -p trapapa ssh -L 7496:localhost:7496 -N -f -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null trapapa@192.168.178.75

# 2. CROX Dezember (monatlich, Standard)
/home/hermes/tws_option_pipeline/venv/bin/python3 src/tws_pipeline.py CROX 2 SMART USD

# 3. Ergebnis ansehen
cat /home/hermes/tws_option_pipeline/src/tws_option_contracts_CROX_*.csv
```

---

**Version:** 1.0 | **Datum:** 2026-10-07 | **Autor:** Hermes Agent