#!/usr/bin/env python3
# Pipe-fähig: liest Symbol von stdin, schreibt JSON (underConid, months) nach stdout

import sys
import json
import logging
import requests
import urllib3

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s : %(lineno)d - %(message)s')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PREFERRED_EXCHANGES = (
    "AMEX", "ARCA", "BATS", "IEX", "NASDAQ", "NYSE", "SMART",
)


def secdef_search(symbol: str) -> dict:
    url = f"https://localhost:4002/v1/api/iserver/secdef/search?symbol={symbol}"
    try:
        resp = requests.get(url=url, verify=False, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise ValueError(f"API request failed for {symbol}: {e}")

    if not isinstance(data, list):
        raise ValueError(f"Unexpected API response for {symbol}: {data}")

    selected = None
    for contract in data:
        if not isinstance(contract, dict):
            continue
        desc = contract.get("description", "")
        if desc in PREFERRED_EXCHANGES:
            for sec in contract.get("sections", []):
                if sec.get("secType") == "OPT":
                    selected = contract
                    break
            if selected:
                break

    if not selected:
        for contract in data:
            if not isinstance(contract, dict):
                continue
            for sec in contract.get("sections", []):
                if sec.get("secType") == "OPT":
                    selected = contract
                    break
            if selected:
                break

    if not selected:
        raise ValueError(f"No option contract found for {symbol}")

    under_conid = selected.get("conid")
    if not under_conid:
        raise ValueError(f"No conid for {symbol}")

    months = []
    for sec in selected.get("sections", []):
        if sec.get("secType") == "OPT":
            months_str = sec.get("months", "")
            if months_str:
                months = months_str.split(";")
            break

    if not months:
        raise ValueError(f"No option months for {symbol}")

    return {"underConid": under_conid, "symbol": symbol, "months": months}


def main():
    symbol = sys.stdin.read().strip()
    if not symbol:
        sys.exit(1)
    try:
        result = secdef_search(symbol)
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(1)


if __name__ == "__main__":
    main()