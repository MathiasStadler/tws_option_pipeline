#!/usr/bin/env python3
# Pipe-fähig: liest CSV (conid,symbol,strike,maturityDate,right,month) von stdin,
# holt Marktdaten (snapshot) für alle conids, schreibt erweitertes CSV nach stdout

import sys
import csv
import json
import logging
import requests
import urllib3
import time
from datetime import datetime

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s : %(lineno)d - %(message)s')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FIELD_MAP = {
    "84": "bid",
    "85": "ask",
    "86": "delta",
    "87": "gamma",
    "88": "theta",
    "89": "vega"
}
GENERIC_MAP = {
    "100": "volume",
    "101": "open_interest",
    "104": "historical_volatility",
    "106": "implied_volatility"
}

HEADERS = [
    "conid", "symbol", "right", "month", "strike", "maturityDate",
    "bid", "ask", "delta", "gamma", "theta", "vega",
    "volume", "open_interest", "historical_volatility", "implied_volatility"
]


def authenticate_market_data():
    url = "https://localhost:4002/v1/api/iserver/accounts"
    try:
        requests.get(url=url, verify=False, timeout=5)
    except Exception:
        pass


def subscribe_market_data(conids):
    """Subscribes to market data for given conids to enable Greeks."""
    url = "https://localhost:4002/v1/api/iserver/marketdata/subscribe"
    fields = list(FIELD_MAP.keys()) + list(GENERIC_MAP.keys())
    # Split into batches of 50 (API limit)
    for i in range(0, len(conids), 50):
        batch = conids[i:i+50]
        try:
            resp = requests.post(url, json={"conids": batch, "fields": fields}, verify=False, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            logging.error(f"Subscribe failed for batch: {e}")
    # Wait for data to populate
    time.sleep(2)


def get_option_snapshot_bulk(conids, batch_size=20):
    """Holt Marktdaten für alle conids in Batches."""
    if not conids:
        return {}
    
    authenticate_market_data()
    subscribe_market_data(conids)
    
    fields = ",".join(FIELD_MAP.keys())
    generic_ticks = ",".join(GENERIC_MAP.keys())
    
    all_data = {}
    total_batches = (len(conids) + batch_size - 1) // batch_size
    
    for i in range(0, len(conids), batch_size):
        batch = conids[i:i+batch_size]
        conid_str = ",".join(str(c) for c in batch)
        
        url = f'https://localhost:4002/v1/api/iserver/marketdata/snapshot?conids={conid_str}&fields={fields}&genericTickList={generic_ticks}&snapshot=0'
        
        batch_data = {}
        for attempt in range(2):
            try:
                resp = requests.get(url=url, verify=False, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                
                for item in data:
                    conid = item.get("conid")
                    if not conid:
                        continue
                    if conid not in batch_data:
                        batch_data[conid] = {}
                    
                    for f_id, f_name in FIELD_MAP.items():
                        val = item.get(f_id)
                        batch_data[conid][f_name] = val if val is not None else ""
                    
                    for g_id, g_name in GENERIC_MAP.items():
                        val = item.get(g_id)
                        batch_data[conid][g_name] = val if val is not None else ""
                
                # Zweite Anfrage für generische Ticks
                if attempt == 0:
                    time.sleep(1)
                    resp2 = requests.get(url=url, verify=False, timeout=15)
                    resp2.raise_for_status()
                    data2 = resp2.json()
                    for item in data2:
                        conid = item.get("conid")
                        if not conid:
                            continue
                        if conid not in batch_data:
                            batch_data[conid] = {}
                        for g_id, g_name in GENERIC_MAP.items():
                            val = item.get(g_id)
                            if val is not None:
                                batch_data[conid][g_name] = val
                
                break
            except Exception as e:
                if attempt == 1:
                    logging.error(f"Batch failed: {e}")
    
        # Formatiere Batch
        for conid, quote in batch_data.items():
            formatted = {}
            for f_name in FIELD_MAP.values():
                val = quote.get(f_name, "")
                if f_name in ["bid", "ask"]:
                    formatted[f_name] = str(val) if val not in ["", None] else ""
                else:
                    formatted[f_name] = val if val not in ["", None] else ""
            for g_name in GENERIC_MAP.values():
                formatted[g_name] = quote.get(g_name, "")
            all_data[conid] = formatted
    
    return all_data


def process_contracts(contracts_list):
    """Hauptlogik aus writeResult: Snapshot holen, Vorzeichen korrigieren, CSV bauen."""
    conid_to_contract = {int(c["conid"]): c for c in contracts_list}
    all_conids = list(conid_to_contract.keys())
    
    # Marktdaten holen
    snapshot_data = get_option_snapshot_bulk(all_conids)
    
    # Merge
    for conid, quote in snapshot_data.items():
        if conid in conid_to_contract:
            conid_to_contract[conid].update(quote)
    
    # Vorzeichenkorrektur für Puts
    for conid, contract in conid_to_contract.items():
        if contract.get("right") == "P":
            if "delta" in contract and contract["delta"]:
                try:
                    delta_val = float(contract["delta"])
                    if 0 <= delta_val <= 1:
                        contract["delta"] = -delta_val
                except (ValueError, TypeError):
                    pass
            if "gamma" in contract and contract["gamma"]:
                try:
                    gamma_val = float(contract["gamma"])
                    if gamma_val > 0:
                        contract["gamma"] = -gamma_val
                except (ValueError, TypeError):
                    pass
    
    # Nur PUTs (FORCE_PUT_ONLY = True)
    put_contracts = [c for c in contracts_list if c.get("right") == "P"]
    
    # Delta-Filter: -0.50 bis -0.10 (nur Puts mit sinnvollen Deltas)
    filtered = []
    for c in put_contracts:
        delta_raw = c.get("delta")
        if delta_raw is None or delta_raw == "":
            continue
        try:
            delta = float(delta_raw)
            if -0.50 <= delta <= -0.10:
                filtered.append(c)
        except (ValueError, TypeError):
            pass
    logging.info(f"Delta filter: {len(filtered)} contracts with delta -0.50..-0.10")
    final_contracts = filtered
    
    if not final_contracts:
        logging.warning("No contracts after delta filtering. CSV will have headers only.")
    
    # CSV bauen
    output_rows = []
    for c in final_contracts:
        row = {h: c.get(h, "") for h in HEADERS}
        output_rows.append(row)
    
    return output_rows


def main():
    # CSV von stdin lesen
    reader = csv.DictReader(sys.stdin)
    contracts = list(reader)
    
    if not contracts:
        sys.exit(1)
    
    # Verarbeiten
    output_rows = process_contracts(contracts)
    
    # CSV nach stdout
    writer = csv.DictWriter(sys.stdout, fieldnames=HEADERS)
    writer.writeheader()
    writer.writerows(output_rows)


if __name__ == "__main__":
    main()