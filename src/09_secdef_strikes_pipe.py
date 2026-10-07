#!/usr/bin/env python3
# Pipe-fähig: liest "underConid month exchange" von stdin, schreibt JSON array mit strikes nach stdout

import sys
import json
import logging
import requests
import urllib3

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s : %(lineno)d - %(message)s')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def secdef_strikes(under_conid: str, month: str, exchange: str = "SMART") -> list:
    """
    Ruft verfügbare Strikes für eine Option über die REST-API ab.
    Verwendet den Endpunkt /iserver/secdef/strikes.
    """
    url = f"https://localhost:4002/v1/api/iserver/secdef/strikes?conid={under_conid}&secType=OPT&month={month}&exchange={exchange}"
    try:
        resp = requests.get(url=url, verify=False, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # API gibt dict mit "put" und "call" Arrays zurück
        put_strikes = data.get("put", [])
        call_strikes = data.get("call", [])
        return {"put": put_strikes, "call": call_strikes}
    except Exception as e:
        return {"error": str(e)}


def main():
    # Erwarte Input: "underConid month [exchange]" (3 Werte, exchange optional, Default: SMART)
    line = sys.stdin.read().strip()
    if not line:
        sys.exit(1)
    parts = line.split()
    if len(parts) < 2:
        json.dump({"error": "Expected 'underConid month [exchange]' on stdin"}, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(1)
    
    under_conid = parts[0]
    month = parts[1]
    exchange = parts[2] if len(parts) > 2 else "SMART"
    
    try:
        result = secdef_strikes(under_conid, month, exchange)
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(1)


if __name__ == "__main__":
    main()