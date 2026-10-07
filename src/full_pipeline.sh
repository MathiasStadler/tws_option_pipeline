#!/usr/bin/env bash
# Vollständige Pipeline: Symbol -> gefilterte PUT-Optionen mit Delta -0.50 bis -0.10
# Usage: ./full_pipeline.sh <SYMBOL> [MONTH_INDEX] [EXCHANGE]

set -euo pipefail

SCRIPT_DIR="/home/hermes/docker-script-runner/src"

SYMBOL="${1:-CROX}"
MONTH_INDEX="${2:-0}"  # 0 = erster Monat
EXCHANGE="${3:-SMART}"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

echo "=== Pipeline für $SYMBOL (Monat Index $MONTH_INDEX) ==="

# 1. Authentifizierung
echo "1. Authentifizierung..."
python3 "$SCRIPT_DIR/13_authenticate_market_data_pipe.py" > /dev/null

# 2. SecDef Search (Symbol -> underConid + months)
echo "2. SecDef Search..."
SECDEF_OUT=$(echo "$SYMBOL" | python3 "$SCRIPT_DIR/08_secdef_pipe.py")
UNDER_CONID=$(echo "$SECDEF_OUT" | jq -r '.underConid')
MONTH=$(echo "$SECDEF_OUT" | jq -r ".months[$MONTH_INDEX]")
SYMBOL_OUT=$(echo "$SECDEF_OUT" | jq -r '.symbol')

echo "   underConid: $UNDER_CONID, Monat: $MONTH"

# 3. Stock Price
echo "3. Stock Price..."
echo "$UNDER_CONID $SYMBOL_OUT" | python3 "$SCRIPT_DIR/08_stock_price_pipe.py" > /dev/null

# 4. Strikes für den Monat
echo "4. Strikes holen..."
STRIKES_JSON=$(echo "$UNDER_CONID $MONTH $EXCHANGE" | python3 "$SCRIPT_DIR/09_secdef_strikes_pipe.py")

# 5. Contract Info für alle PUT-Strikes
echo "5. Contract Info für PUT-Strikes..."
PUT_STRIKES=$(echo "$STRIKES_JSON" | jq -r '.put[]?')
if [[ -z "$PUT_STRIKES" ]]; then
    echo "Keine PUT-Strikes gefunden"
    exit 1
fi

CONTRACTS_CSV="$SCRIPT_DIR/contracts_${UNDER_CONID}_${MONTH}_${TIMESTAMP}.csv"
echo "conid,symbol,strike,maturityDate,right" > "$CONTRACTS_CSV"

for STRIKE in $PUT_STRIKES; do
    INFO_INPUT="$UNDER_CONID $MONTH $STRIKE P $EXCHANGE"
    RESULT=$(echo "$INFO_INPUT" | python3 "$SCRIPT_DIR/10_secdef_info_pipe.py")
    echo "$RESULT" | jq -r '.[] | select(has("error") | not) | [.conid, .symbol, .strike, .maturityDate, .right] | @csv' >> "$CONTRACTS_CSV"
done

CONTRACT_COUNT=$(($(wc -l < "$CONTRACTS_CSV") - 1))
echo "   $CONTRACT_COUNT Contracts in $CONTRACTS_CSV"

# 6. Marktdaten + Greeks + Delta-Filter
echo "6. Marktdaten & Greeks holen (Delta-Filter -0.50 bis -0.10)..."
FINAL_CSV="$SCRIPT_DIR/option_contracts_filtered_${SYMBOL_OUT}_${MONTH}_${TIMESTAMP}.csv"
cat "$CONTRACTS_CSV" | python3 "$SCRIPT_DIR/12_write_result_pipe.py" > "$FINAL_CSV"

FINAL_COUNT=$(($(wc -l < "$FINAL_CSV") - 1))
echo "   $FINAL_COUNT Contracts nach Delta-Filter in $FINAL_CSV"

# Ergebnis anzeigen
echo ""
echo "=== ERGEBNIS ==="
cat "$FINAL_CSV"
echo ""
echo "Datei: $FINAL_CSV"