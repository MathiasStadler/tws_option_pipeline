#!/usr/bin/env python3
# Pipe-fähig: liest "conid symbol" von stdin, schreibt JSON (last, bid, ask, timestamp) nach stdout

import sys
import json
import logging
import requests
import urllib3
from datetime import datetime

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s : %(lineno)d - %(message)s')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_stock_price(conid: str, symbol: str) -> dict:
    """
    Ruft den aktuellen Aktienkurs (Underlying) über die REST-API ab.
    Verwendet den Endpunkt /iserver/marketdata/snapshot.
    """
    # Stelle sicher, dass die Session authentifiziert ist
    auth_url = "https://localhost:4002/v1/api/iserver/accounts"
    try:
        requests.get(auth_url, verify=False, timeout=5)
    except Exception:
        pass  # ignore auth errors, snapshot will fail if needed

    url = "https://localhost:4002/v1/api/iserver/marketdata/snapshot"
    params = {
        "conids": conid,
        "fields": "31,84,86"   # 31 = last, 84 = bid, 86 = ask
    }
    try:
        resp = requests.get(url, params=params, verify=False, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data and isinstance(data, list) and len(data) > 0:
            item = data[0]
            last = item.get("31", "N/A")
            bid = item.get("84", "N/A")
            ask = item.get("86", "N/A")
            return {
                "symbol": symbol,
                "conid": conid,
                "last": last,
                "bid": bid,
                "ask": ask,
                "timestamp": datetime.now().isoformat()
            }
        else:
            return None
    except Exception as e:
        return {"error": str(e)}


def main():
    # Erwarte Input: "conid symbol" (zwei Werte, durch Whitespace getrennt)
    line = sys.stdin.read().strip()
    if not line:
        sys.exit(1)
    parts = line.split()
    if len(parts) != 2:
        json.dump({"error": "Expected 'conid symbol' on stdin"}, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(1)
    conid, symbol = parts[0], parts[1]
    try:
        result = get_stock_price(conid, symbol)
        if result is None:
            json.dump({"error": "No data returned"}, sys.stdout)
        else:
            json.dump(result, sys.stdout)
        sys.stdout.write("\n")
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(1)


if __name__ == "__main__":
    main()