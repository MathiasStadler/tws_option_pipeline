#!/usr/bin/env python3
# Multi-Symbol Batch Pipeline: Sequentiell mit IBKR (kein Threading-Problem)
# Usage: python3 multi_symbol_batch.py [SYMBOLS...] [MONTH_INDICES...] [EXCHANGE] [CURRENCY]

import sys
import csv
import logging
import math
from datetime import datetime
from ib_insync import IB, Stock, Option

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s : %(message)s')
logger = logging.getLogger(__name__)

HEADERS = [
    "symbol", "expiration", "strike", "multiplier",
    "bid", "ask", "last", "close", "volume",
    "delta", "gamma", "theta", "vega", "impliedVol",
    "bidSize", "askSize", "high", "low", "openPrice", "openInterest",
    "put_profit"
]

SYMBOL_DEFAULTS = {
    'ALV':   {'exchange': 'XETRA', 'currency': 'EUR'},
    'ASML':  {'exchange': 'AEB',   'currency': 'EUR'},
    'SAP':   {'exchange': 'XETRA', 'currency': 'EUR'},
    'SIE':   {'exchange': 'XETRA', 'currency': 'EUR'},
    'VOW3':  {'exchange': 'XETRA', 'currency': 'EUR'},
    'BMW':   {'exchange': 'XETRA', 'currency': 'EUR'},
    'DTE':   {'exchange': 'XETRA', 'currency': 'EUR'},
    'BAYN':  {'exchange': 'XETRA', 'currency': 'EUR'},
    'BAS':   {'exchange': 'XETRA', 'currency': 'EUR'},
    'DHL':   {'exchange': 'XETRA', 'currency': 'EUR'},
    'CROX':  {'exchange': 'SMART', 'currency': 'USD'},
    'TREX':  {'exchange': 'SMART', 'currency': 'USD'},
    'AAPL':  {'exchange': 'SMART', 'currency': 'USD'},
    'MSFT':  {'exchange': 'SMART', 'currency': 'USD'},
    'TSLA':  {'exchange': 'SMART', 'currency': 'USD'},
    'NVDA':  {'exchange': 'SMART', 'currency': 'USD'},
    'AMD':   {'exchange': 'SMART', 'currency': 'USD'},
    'SPY':   {'exchange': 'SMART', 'currency': 'USD'},
    'QQQ':   {'exchange': 'SMART', 'currency': 'USD'},
}

# Black-Scholes Delta Approximation
def bs_put_delta(S, K, T, r, sigma):
    if sigma <= 0 or T <= 0:
        return None
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    delta = 0.5 * (1 + math.erf(d1 / math.sqrt(2))) - 1
    return delta

def estimate_atm_iv(chain, stock_price):
    if not chain.strikes:
        return 0.3
    atm_strike = min(chain.strikes, key=lambda x: abs(x - stock_price))
    strike_range = max(chain.strikes) - min(chain.strikes)
    relative_width = strike_range / stock_price
    estimated_iv = 0.2 + relative_width * 2
    return max(0.15, min(0.8, estimated_iv))

def get_strike_range_for_delta(chain, stock_price, expiration, min_delta=-0.50, max_delta=-0.10, r=0.05):
    try:
        exp_date = datetime.strptime(expiration, '%Y%m%d')
        T = (exp_date - datetime.now()).days / 365.0
        if T <= 0:
            return None, None
    except:
        return None, None
    
    sigma = estimate_atm_iv(chain, stock_price)
    logger.info(f"  {expiration}: est. IV={sigma:.2%}, T={T:.3f}y")
    
    valid_strikes = []
    for strike in chain.strikes:
        delta = bs_put_delta(stock_price, strike, T, 0.05, sigma)
        if delta is not None and min_delta <= delta <= max_delta:
            valid_strikes.append(strike)
    
    if not valid_strikes:
        return None, None
    return min(valid_strikes), max(valid_strikes)


def connect_ib(client_id):
    ib = IB()
    ib.connect('127.0.0.1', 7496, clientId=client_id, timeout=15, readonly=True)
    ib.reqMarketDataType(4)
    return ib


def get_defaults(symbol):
    return SYMBOL_DEFAULTS.get(symbol.upper(), {'exchange': 'SMART', 'currency': 'USD'})


def get_stock_and_chain(ib, symbol, month_index, exchange, currency):
    stock = Stock(symbol, exchange, currency)
    ib.qualifyContracts(stock)
    
    chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
    chain = [c for c in chains if c.exchange == exchange]
    if not chain:
        chain = [c for c in chains if c.expirations]
        if not chain:
            raise ValueError(f"No option chain for {symbol} on {exchange}")
        chain = chain[0]
    else:
        chain = chain[0]
    
    if month_index >= len(chain.expirations):
        raise ValueError(f"Month index {month_index} out of range")
    
    expiration = chain.expirations[month_index]
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


def get_valid_put_options(ib, symbol, expiration, chain, exchange, min_strike, max_strike):
    options = []
    for strike in chain.strikes:
        if min_strike is not None and strike < min_strike:
            continue
        if max_strike is not None and strike > max_strike:
            continue
        opt = Option(symbol, expiration, strike, 'P', exchange, tradingClass=chain.tradingClass, multiplier=chain.multiplier)
        options.append(opt)
    
    ib.qualifyContracts(*options)
    valid = [o for o in options if o.conId and o.conId > 0]
    return valid


def fetch_option_greeks_batch(ib, options):
    if not options:
        return []
    
    for opt in options:
        ib.reqMktData(opt, '', False, False)
    
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
    return [r for r in rows if r['delta'] is not None and min_delta <= r['delta'] <= max_delta]


def write_master_csv(results, filepath):
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        for res in results:
            if 'error' in res:
                continue
            for r in res['top5']:
                out_row = {}
                for h in HEADERS:
                    val = r.get(h)
                    if h == 'put_profit':
                        val = f'{val:.2f}%'
                    elif isinstance(val, float):
                        if h in {'bid', 'ask', 'last', 'close', 'bidSize', 'askSize', 'high', 'low', 'openPrice'}:
                            val = f'{val:.2f}'
                        elif h in {'delta', 'gamma', 'theta', 'vega', 'impliedVol'}:
                            val = f'{val:.6f}'
                        else:
                            val = f'{val:.6f}'
                    out_row[h] = val if val is not None else ''
                writer.writerow(out_row)


def process_symbol(symbol, month_indices, exchange, currency, client_id):
    """Verarbeitet ein einzelnes Symbol"""
    ib = None
    try:
        ib = connect_ib(client_id)
        
        stock, chain, _ = get_stock_and_chain(ib, symbol, month_indices[0], exchange, currency)
        stock_data = get_stock_data(ib, stock)
        stock_price = stock_data['last'] or stock_data['close']
        logger.info(f"{symbol}: Stock @ {stock_price} {currency}")
        
        all_rows = []
        
        for month_idx in month_indices:
            try:
                _, chain, expiration = get_stock_and_chain(ib, symbol, month_idx, exchange, currency)
                stock_price = stock_data['last'] or stock_data['close']
                
                min_strike, max_strike = get_strike_range_for_delta(chain, stock_price, expiration)
                if min_strike is None:
                    logger.warning(f"  {symbol} {expiration}: Keine Strikes im Delta-Bereich")
                    continue
                
                options = get_valid_put_options(ib, symbol, expiration, chain, exchange, min_strike, max_strike)
                if not options:
                    continue
                
                rows = fetch_option_greeks_batch(ib, options)
                filtered = filter_by_delta(rows)
                
                for r in filtered:
                    r['expiration'] = expiration
                    bid = r.get('bid')
                    strike = r.get('strike')
                    if bid and strike and strike != 0:
                        r['put_profit'] = (bid / strike) * 100
                    else:
                        r['put_profit'] = 0
                
                all_rows.extend(filtered)
                
            except Exception as e:
                logger.warning(f"  {symbol} {expiration} failed: {e}")
        
        # Top 5 nach put_profit
        all_rows.sort(key=lambda x: x.get('put_profit', 0), reverse=True)
        top5 = all_rows[:5]
        
        return {
            'symbol': symbol,
            'stock_price': stock_data['last'] or stock_data['close'],
            'currency': currency,
            'expirations_processed': len(month_indices),
            'total_options': len(all_rows),
            'top5': top5
        }
        
    except Exception as e:
        logger.error(f"{symbol} failed: {e}")
        return {'symbol': symbol, 'error': str(e)}
    finally:
        if ib and ib.isConnected():
            ib.disconnect()


def filter_by_delta(rows, min_delta=-0.50, max_delta=-0.10):
    return [r for r in rows if r['delta'] is not None and min_delta <= r['delta'] <= max_delta]


def write_master_csv(results, filepath):
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        for res in results:
            if 'error' in res:
                continue
            for r in res['top5']:
                out_row = {}
                for h in HEADERS:
                    val = r.get(h)
                    if h == 'put_profit':
                        val = f'{val:.2f}%'
                    elif isinstance(val, float):
                        if h in {'bid', 'ask', 'last', 'close', 'bidSize', 'askSize', 'high', 'low', 'openPrice'}:
                            val = f'{val:.2f}'
                        elif h in {'delta', 'gamma', 'theta', 'vega', 'impliedVol'}:
                            val = f'{val:.6f}'
                        else:
                            val = f'{val:.6f}'
                    out_row[h] = val if val is not None else ''
                writer.writerow(out_row)


def main():
    default_symbols = ['CROX', 'AAPL', 'TREX', 'TSLA', 'NVDA']
    default_month_indices = [0, 1, 2]
    
    if len(sys.argv) > 1:
        args = sys.argv[1:]
        symbols = []
        month_indices = []
        exchange = 'SMART'
        currency = 'USD'
        
        for arg in args:
            if arg.isdigit():
                month_indices.append(int(arg))
            elif arg in ['SMART', 'XETRA', 'AEB', 'NYSE', 'NASDAQ']:
                exchange = arg
            elif arg in ['USD', 'EUR']:
                currency = arg
            else:
                symbols.append(arg.upper())
        
        if not symbols:
            symbols = default_symbols
        if not month_indices:
            month_indices = default_month_indices
    else:
        symbols = default_symbols
        month_indices = default_month_indices
        exchange = 'SMART'
        currency = 'USD'
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = f"/home/hermes/tws_option_pipeline/src/multi_symbol_top5_{timestamp}.csv"
    
    logger.info(f"Multi-Symbol Batch: {len(symbols)} Symbole, {len(month_indices)} Expirations each")
    logger.info(f"Symbols: {symbols}")
    logger.info(f"Month indices: {month_indices}")
    
    results = []
    for i, symbol in enumerate(symbols):
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing {symbol} ({i+1}/{len(symbols)})...")
        
        defaults = SYMBOL_DEFAULTS.get(symbol, {'exchange': exchange, 'currency': currency})
        ex = exchange if exchange != 'SMART' else defaults['exchange']
        cur = currency if currency != 'USD' else defaults['currency']
        
        result = process_symbol(symbol, month_indices, ex, cur, 100 + i)
        results.append(result)
        
        if 'error' in result:
            logger.error(f"{symbol}: {result['error']}")
        else:
            logger.info(f"{symbol}: {len(result['top5'])} top options, stock={result['stock_price']} {result['currency']}")
    
    # Master CSV
    write_master_csv(results, csv_file)
    logger.info(f"Master CSV: {csv_file}")
    
    # Summary
    print(f"\n{'='*80}")
    print(f"MULTI-SYMBOL BATCH RESULTS - Top 5 per Symbol by Put Profit")
    print(f"{'='*80}")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"File: {csv_file}")
    print(f"{'='*80}")
    
    for res in results:
        if 'error' in res:
            print(f"\n❌ {res['symbol']}: {res['error']}")
            continue
        
        print(f"\n📈 {res['symbol']} @ {res['stock_price']} {res['currency']} ({res['expirations_processed']} expirations)")
        print(f"{'Strike':>8} | {'Exp':>10} | {'Delta':>7} | {'Bid':>6} | {'Ask':>6} | {'Vol':>5} | {'IV':>7} | {'Profit%':>8}")
        print("-" * 85)
        
        for r in res['top5']:
            exp_short = r['expiration'][4:] if len(r['expiration']) == 8 else r['expiration']
            print(f"{r['strike']:>8.1f} | {exp_short:>10} | {r['delta']:>7.4f} | {r['bid']:>6.2f} | {r['ask']:>6.2f} | {r['volume']:>5.0f} | {r['impliedVol']:>6.2%} | {r['put_profit']:>7.2f}%")
    
    print(f"\n✅ Master CSV: {csv_file}")


if __name__ == '__main__':
    main()