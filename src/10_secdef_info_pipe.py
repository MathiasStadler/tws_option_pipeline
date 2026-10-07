#!/usr/bin/env python3
# Pipe-fähig: liest "underConid month strike right exchange" von stdin, schreibt JSON array mit contract details nach stdout

import sys
import json
import logging
import requests
import urllib3

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s : %(lineno)d - %(message)s')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def secdef_info(under_conid: str, month: str, strike: str, right: str = "P", exchange: str = "SMART") -> list:
    """
    Ruft Contract-Details für eine Option über die REST-API ab.
    Verwendet den Endpunkt /iserver/secdef/info.
    """
    url = f"https://localhost:4002/v1/api/iserver/secdef/info?conid={under_conid}&month={month}&strike={strike}&secType=OPT&right={right}&exchange={exchange}"
    try:
        resp = requests.get(url=url, verify=False, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        contracts = []
        for contract in data:
            contract_right = contract.get("right", right)
            contract_details = {
                "conid": contract["conid"],
                "symbol": contract["symbol"],
                "strike": contract["strike"],
                "maturityDate": contract["maturityDate"],
                "right": contract_right
            }
            contracts.append(contract_details)
        return contracts
    except Exception as e:
        return [{"error": str(e)}]


def main():
    # Erwarte Input: "underConid month strike right exchange" (5 Werte, durch Whitespace getrennt)
    # right und exchange sind optional (Defaults: P, SMART)
    line = sys.stdin.read().strip()
    if not line:
        sys.exit(1)
    parts = line.split()
    if len(parts) < 3:
        json.dump([{"error": "Expected 'underConid month strike [right] [exchange]' on stdin"}], sys.stdout)
        sys.stdout.write("\n")
        sys.exit(1)
    
    under_conid = parts[0]
    month = parts[1]
    strike = parts[2]
    right = parts[3] if len(parts) > 3 else "P"
    exchange = parts[4] if len(parts) > 4 else "SMART"
    
    try:
        result = secdef_info(under_conid, month, strike, right, exchange)
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
    except Exception as e:
        json.dump([{"error": str(e)}], sys.stdout)
        sys.stdout.write("\n")
        sys.exit(1)


if __name__ == "__main__":
    main()