#!/usr/bin/env python3
# Pure TWS Pipeline: nur ib_insync, Strikes via qualifyContracts filtern
# Usage: python3 tws_pipeline.py <SYMBOL> [MONTH_INDEX] [EXCHANGE] [CURRENCY]
# Examples:
#   python3 tws_pipeline.py ALV 0 XETRA EUR      # Allianz (German, XETRA)
#   python3 tws_pipeline.py CROX 0 SMART USD      # Crocs (US, SMART)
#   python3 tws_pipeline.py ASML 0 AEB EUR        # ASML (Dutch, AEB/Amsterdam)

import sys
import csv
import logging
from datetime import datetime
from ib_insync import IB, Stock, Option

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s : %(message)s')
logger = logging.getLogger(__name__)

HEADERS = [
    "conid", "symbol", "right", "expiration", "strike", "multiplier",
    "bid", "ask", "last", "close", "volume",
    "delta", "gamma", "theta", "vega", "impliedVol",
    "bidSize", "askSize", "high", "low", "openPrice", "openInterest"
]

# Default exchange/currency mapping for common symbols
SYMBOL_DEFAULTS = {
    'ALV':   {'exchange': 'XETRA', 'currency': 'EUR'},   # Allianz (Germany)
    'ASML':  {'exchange': 'AEB',   'currency': 'EUR'},   # ASML (Netherlands)
    'SAP':   {'exchange': 'XETRA', 'currency': 'EUR'},   # SAP (Germany)
    'SIE':   {'exchange': 'XETRA', 'currency': 'EUR'},   # Siemens (Germany)
    'VOW3':  {'exchange': 'XETRA', 'currency': 'EUR'},   # Volkswagen (Germany)
    'BMW':   {'exchange': 'XETRA', 'currency': 'EUR'},   # BMW (Germany)
    'DTE':   {'exchange': 'XETRA', 'currency': 'EUR'},   # Deutsche Telekom (Germany)
    'BAYN':  {'exchange': 'XETRA', 'currency': 'EUR'},   # Bayer (Germany)
    'BAS':   {'exchange': 'XETRA', 'currency': 'EUR'},   # BASF (Germany)
    'DHL':   {'exchange': 'XETRA', 'currency': 'EUR'},   # DHL (Germany)
    'CROX':  {'exchange': 'SMART', 'currency': 'USD'},   # Crocs (US)
    'TREX':  {'exchange': 'SMART', 'currency': 'USD'},   # Trex (US)
    'AAPL':  {'exchange': 'SMART', 'currency': 'USD'},   # Apple (US)
    'MSFT':  {'exchange': 'SMART', 'currency': 'USD'},   # Microsoft (US)
}


def connect_ib(client_id=1):
    ib = IB()
    ib.connect('127.0.0.1', 7496, clientId=client_id, timeout=15, readonly=True)
    ib.reqMarketDataType(4)  # delayed-frozen for paper
    return ib


def get_defaults(symbol):
    """Get default exchange/currency for symbol."""
    return SYMBOL_DEFAULTS.get(symbol.upper(), {'exchange': 'SMART', 'currency': 'USD'})


def get_stock_and_chain(ib, symbol, month_index=0, exchange='SMART', currency='USD'):
    stock = Stock(symbol, exchange, currency)
    ib.qualifyContracts(stock)
    
    chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
    chain = [c for c in chains if c.exchange == exchange]
    if not chain:
        # Try to find any chain with options
        chain = [c for c in chains if c.expirations]
        if not chain:
            raise ValueError(f"No option chain found for {symbol} on {exchange}")
        chain = chain[0]
        logger.info(f"Using chain from exchange: {chain.exchange}")
    else:
        chain = chain[0]
    
    if month_index >= len(chain.expirations):
        raise ValueError(f"Month index {month_index} out of range (max {len(chain.expirations)-1})")
    
    expiration = chain.expirations[month_index]
    logger.info(f"Chain: {chain.tradingClass}, Expiration: {expiration}, All strikes: {len(chain.strikes)}")
    return stock, chain, expiration


def get_stock_data(ib, stock):
    ticker = ib.reqMktData(stock, '', False, False)
    ib.sleep(2)
    data = {
        'conid': stock.conId, 'symbol': stock.symbol,
        'bid': ticker.bid, 'ask': ticker.ask, 'last': ticker.last,
        'close': ticker.close, 'volume': ticker.volume,
        'high': ticker.high, 'low': ticker.low,
    }
    ib.cancelMktData(stock)
    return data


def get_valid_put_options(ib, symbol, expiration, chain, exchange='SMART'):
    """Create ALL put options, qualify, keep only valid (conId > 0)."""
    options = []
    for strike in chain.strikes:
        opt = Option(symbol, expiration, strike, 'P', exchange, tradingClass=chain.tradingClass, multiplier=chain.multiplier)
        options.append(opt)
    
    ib.qualifyContracts(*options)
    valid = [o for o in options if o.conId and o.conId > 0]
    logger.info(f"Qualified {len(valid)} of {len(options)} put options for {expiration}")
    return valid


def fetch_option_greeks(ib, options):
    """Fetch market data and Greeks for all options with proper delayed data handling."""
    # First, subscribe to all options to start market data flow
    for opt in options:
        ib.reqMktData(opt, '', False, False)
    
    # Wait for data to populate
    ib.sleep(3)
    
    results = []
    for opt in options:
        ticker = ib.ticker(opt)
        
        greeks = ticker.modelGreeks
        row = {
            'conid': opt.conId, 'symbol': opt.symbol, 'right': opt.right,
            'expiration': opt.lastTradeDateOrContractMonth, 'strike': opt.strike,
            'multiplier': opt.multiplier,
            'bid': ticker.bid, 'ask': ticker.ask, 'last': ticker.last,
            'close': ticker.close, 'volume': ticker.volume,
            'bidSize': ticker.bidSize, 'askSize': ticker.askSize,
            'high': ticker.high, 'low': ticker.low, 'openPrice': ticker.open,
            'openInterest': getattr(ticker, 'putOpenInterest', None) or getattr(ticker, 'openInterest', None),
        }
        
        if greeks:
            row['delta'] = greeks.delta
            row['gamma'] = greeks.gamma
            row['theta'] = greeks.theta
            row['vega'] = greeks.vega
            row['impliedVol'] = greeks.impliedVol
        else:
            row['delta'] = row['gamma'] = row['theta'] = row['vega'] = row['impliedVol'] = None
        
        results.append(row)
        ib.cancelMktData(opt)
    
    return results


def filter_by_delta(rows, min_delta=-0.50, max_delta=-0.10):
    filtered = [r for r in rows if r['delta'] is not None and min_delta <= r['delta'] <= max_delta]
    return filtered


def write_csv(rows, filepath):
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        for r in rows:
            out_row = {h: (f'{r[h]:.6f}' if isinstance(r.get(h), float) else (r[h] if r.get(h) is not None else '')) for h in HEADERS}
            writer.writerow(out_row)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tws_pipeline.py <SYMBOL> [MONTH_INDEX] [EXCHANGE] [CURRENCY]")
        print("Examples:")
        print("  python3 tws_pipeline.py ALV 0 XETRA EUR      # Allianz (Germany)")
        print("  python3 tws_pipeline.py ASML 0 AEB EUR       # ASML (Netherlands)")
        print("  python3 tws_pipeline.py CROX 0 SMART USD     # Crocs (US)")
        sys.exit(1)
    
    symbol = sys.argv[1].upper()
    month_index = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    
    # Use defaults if not provided
    defaults = get_defaults(symbol)
    exchange = sys.argv[3] if len(sys.argv) > 3 else defaults['exchange']
    currency = sys.argv[4] if len(sys.argv) > 4 else defaults['currency']
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = f"/home/hermes/docker-script-runner/src/tws_option_contracts_{symbol}_{timestamp}.csv"
    
    logger.info(f"Starting TWS pipeline for {symbol} (month_index={month_index}, exchange={exchange}, currency={currency})")
    
    ib = None
    try:
        ib = connect_ib()
        logger.info(f"Connected to TWS, server version: {ib.client.serverVersion()}")
        
        stock, chain, expiration = get_stock_and_chain(ib, symbol, month_index, exchange, currency)
        stock_data = get_stock_data(ib, stock)
        logger.info(f"Stock: {stock.symbol} @ {stock_data['last'] or stock_data['close']} {currency}")
        
        options = get_valid_put_options(ib, symbol, expiration, chain, exchange)
        logger.info(f"Fetching Greeks for {len(options)} options...")
        
        rows = fetch_option_greeks(ib, options)
        filtered = filter_by_delta(rows)
        logger.info(f"Delta filter (-0.50 to -0.10): {len(filtered)} of {len(rows)}")
        
        write_csv(filtered, csv_file)
        logger.info(f"CSV written: {csv_file}")
        
        print(f"\n=== RESULT: {len(filtered)} PUT options with delta -0.50 to -0.10 ===")
        print(f"File: {csv_file}")
        print(f"Underlying: {symbol} @ {stock_data['last'] or stock_data['close']} {currency}")
        print(f"Expiration: {expiration}")
        for r in filtered:
            print(f"  Strike {r['strike']}: delta={r['delta']:.4f}, bid={r['bid']}, ask={r['ask']}, vol={r['volume']}, OI={r.get('openInterest','N/A')}, iv={r['impliedVol']:.4f}")
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        sys.exit(1)
    finally:
        if ib and ib.isConnected():
            ib.disconnect()


if __name__ == '__main__':
    main()