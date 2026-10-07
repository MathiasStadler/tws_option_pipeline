#!/usr/bin/env bash
# Loop über alle PUT-Strikes und rufe 10_secdef_info_pipe.py für jede Option auf
# Output: CSV mit Contract-Details

set -euo pipefail

SCRIPT_DIR="/home/hermes/docker-script-runner/src"

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <underConid> <month> [exchange]"
    exit 1
fi

UNDER_CONID="$1"
MONTH="$2"
EXCHANGE="${3:-SMART}"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
CSV_FILE="${SCRIPT_DIR}/option_contracts_${UNDER_CONID}_${MONTH}_${TIMESTAMP}.csv"

# Header schreiben
echo "conid,symbol,strike,maturityDate,right" > "$CSV_FILE"

# Strikes holen
STRIKES_JSON=$(echo "${UNDER_CONID} ${MONTH} ${EXCHANGE}" | python3 "${SCRIPT_DIR}/09_secdef_strikes_pipe.py")

# PUT-Strikes extrahieren mit jq
PUT_STRIKES=$(echo "$STRIKES_JSON" | jq -r '.put[]?')

if [[ -z "$PUT_STRIKES" ]]; then
    echo "No PUT strikes found"
    exit 1
fi

echo "Found PUT strikes: $(echo "$PUT_STRIKES" | tr '\n' ' ')"

# Für jeden Strike 10_secdef_info_pipe.py aufrufen
for STRIKE in $PUT_STRIKES; do
    INFO_INPUT="${UNDER_CONID} ${MONTH} ${STRIKE} P ${EXCHANGE}"
    RESULT=$(echo "$INFO_INPUT" | python3 "${SCRIPT_DIR}/10_secdef_info_pipe.py")
    
    # JSON parsen und CSV-Zeile extrahieren
    echo "$RESULT" | jq -r '.[] | select(has("error") | not) | [.conid, .symbol, .strike, .maturityDate, .right] | @csv' >> "$CSV_FILE"
done

echo "CSV written: $CSV_FILE"
echo "Total contracts: $(($(wc -l < "$CSV_FILE") - 1))"
echo "$CSV_FILE"