#!/usr/bin/env python3
# Pipe-fähig: authentifiziert Market Data Session beim IBKR Gateway
# Liest nichts von stdin, gibt JSON Status nach stdout

import sys
import json
import logging
import requests
import urllib3

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s : %(lineno)d - %(message)s')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def authenticate_market_data() -> dict:
    """
    Prüft und initialisiert die Market Data Session beim IBKR Gateway.
    Endpunkt: /v1/api/iserver/accounts
    """
    url = "https://localhost:4002/v1/api/iserver/accounts"
    try:
        resp = requests.get(url=url, verify=False, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "success": True,
            "authenticated": True,
            "accounts": data
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "authenticated": False,
            "error": "Connection refused - IBKR Gateway not running or not accessible"
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "authenticated": False,
            "error": "Timeout - IBKR Gateway not responding"
        }
    except Exception as e:
        return {
            "success": False,
            "authenticated": False,
            "error": str(e)
        }


def main():
    # Keine Eingabe erwartet, nur Authentifizierung durchführen
    result = authenticate_market_data()
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()