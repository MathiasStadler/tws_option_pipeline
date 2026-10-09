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


def check_margin(ib, option, quantity=1, price=None):
    """
    Prüft ob genügend Margin für Short PUT verfügbar ist.
    Verwendet whatIfOrder für exakte Margin-Berechnung.
    Returns: (ok: bool, required_margin: float, available: float, msg: str)
    """
    from ib_insync import Order
    
    # Account Summary holen
    acct = ib.accountSummary()
    available = 0.0
    for v in acct:
        if v.tag == 'AvailableFunds':
            available = float(v.value)
            break
    
    if available <= 0:
        return False, 0, 0, "Keine AvailableFunds gefunden"
    
    # WhatIf Order für Margin-Check
    test_order = Order()
    test_order.action = 'SELL'
    test_order.orderType = 'LMT'
    test_order.totalQuantity = quantity
    test_order.lmtPrice = round(price, 2) if price else 0
    test_order.tif = 'DAY'
    test_order.whatIf = True  # WICHTIG: nur Simulierung
    
    try:
        whatif_trade = ib.placeOrder(option, test_order)
        ib.sleep(1.5)  # Warten auf Margin-Berechnung
        
        # Margin aus whatIf Trade lesen
        required = 0.0
        if whatif_trade.orderStatus.marginChange is not None:
            required = abs(whatif_trade.orderStatus.marginChange)
        elif whatif_trade.orderStatus.initMarginChange is not None:
            required = abs(whatif_trade.orderStatus.initMarginChange)
        elif whatif_trade.orderStatus.maintMarginChange is not None:
            required = abs(whatif_trade.orderStatus.maintMarginChange)
        
        # Fallback: Rough estimate für Short PUT (~20% von Strike * 100)
        if required == 0 and price:
            required = option.strike * 100 * 0.20
        
        # Safety buffer: nur 80% der verfügbaren Funds nutzen
        max_allowed = available * 0.80
        
        if required > max_allowed:
            return False, required, available, f"Margin ${required:,.0f} > 80% Available ${max_allowed:,.0f}"
        
        return True, required, available, f"OK: Margin ${required:,.0f} <= ${max_allowed:,.0f}"
        
    except Exception as e:
        # Fallback auf Schätzung
        est_required = option.strike * 100 * 0.20 if price else 0
        max_allowed = available * 0.80
        if est_required > max_allowed:
            return False, est_required, available, f"Est. Margin ${est_required:,.0f} > 80% Available ${max_allowed:,.0f}"
        return True, est_required, available, f"Est. OK: ${est_required:,.0f} <= ${max_allowed:,.0f}"


def place_option_order(ib, option, action='SELL', quantity=1, order_type='LMT', limit_price=None, auto_transmit=False):
    """
    Platziert eine Option Order in TWS mit Bestätigung.
    Returns: True wenn Order platziert, False sonst.
    """
    from ib_insync import Order
    
    if limit_price is None:
        # Zuerst Marktdaten anfordern, dann Bid/Ask lesen
        ib.reqMktData(option, '', False, False)
        ib.sleep(2)  # Warten auf Marktdaten
        
        ticker = ib.ticker(option)
        if ticker is None:
            logger.warning(f"Kein Ticker für {option.localSymbol}")
            return False
            
        limit_price = ticker.bid if action == 'SELL' else ticker.ask
        ib.cancelMktData(option)
    
    if limit_price is None or limit_price <= 0:
        logger.warning(f"Kein gültiger Limit-Preis für {option.localSymbol}")
        return False
    
    # MARGIN CHECK vor Auto-Order
    if auto_transmit and action == 'SELL' and option.right == 'P':
        ok, required, available, msg = check_margin(ib, option, quantity, limit_price)
        print(f"🔍 Margin Check: {msg}")
        if not ok:
            logger.warning(f"Margin Check fehlgeschlagen: {msg}")
            print(f"❌ Order übersprungen: {msg}")
            return False
    
    order = Order()
    order.action = action
    order.orderType = order_type
    order.totalQuantity = quantity
    order.lmtPrice = round(limit_price, 2)
    order.tif = 'DAY'  # Explizit DAY setzen um Error 10349 zu vermeiden
    
    if auto_transmit:
        trade = ib.placeOrder(option, order)
        ib.sleep(1)
        logger.info(f"Auto-Order platziert: {trade.orderStatus.status}")
        print(f"✅ Auto-Order gesendet: {option.localSymbol} @ ${limit_price:.2f} ({trade.orderStatus.status})")
        return True
    else:
        order.transmit = False  # Nicht sofort senden
        
        # Trade Objekt erstellen (aber nicht senden)
        trade = ib.placeOrder(option, order)
        
        # Bestätigung anfordern
        print(f"\n{'='*60}")
        print(f"ORDER BESTÄTIGUNG")
        print(f"{'='*60}")
        print(f"Symbol:     {option.symbol}")
        print(f"Expiration: {option.lastTradeDateOrContractMonth}")
        print(f"Strike:     {option.strike}")
        print(f"Right:      {option.right}")
        print(f"Action:     {action}")
        print(f"Quantity:   {quantity}")
        print(f"OrderType:  {order_type}")
        print(f"LimitPrice: ${limit_price:.2f}")
        print(f"Contract:   {option.localSymbol}")
        print(f"{'='*60}")
        
        while True:
            confirm = input("Order platzieren? (y/n): ").strip().lower()
            if confirm in ['y', 'yes', 'j', 'ja']:
                trade.transmit = True
                ib.sleep(1)
                logger.info(f"Order platziert: {trade.orderStatus.status}")
                return True
            elif confirm in ['n', 'no', 'nein']:
                ib.cancelOrder(trade.order)
                logger.info("Order abgebrochen")
                return False
            else:
                print("Bitte 'y' oder 'n' eingeben.")


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


def process_symbol(symbol, month_indices, exchange, currency, client_id, keep_connected=False, delta_min=-0.50, delta_max=-0.10, num_chains=0):
    """Verarbeitet ein einzelnes Symbol"""
    ib = None
    try:
        ib = connect_ib(client_id)
        
        stock, chain, _ = get_stock_and_chain(ib, symbol, month_indices[0], exchange, currency)
        stock_data = get_stock_data(ib, stock)
        stock_price = stock_data['last'] or stock_data['close']
        logger.info(f"{symbol}: Stock @ {stock_price} {currency}")
        
        # If num_chains specified, get all available expirations and use first N
        if num_chains > 0:
            all_chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
            chain = [c for c in all_chains if c.exchange == exchange]
            if not chain:
                chain = [c for c in all_chains if c.expirations]
            if chain:
                chain = chain[0]
                available_expirations = chain.expirations[:num_chains]
                logger.info(f"  Using first {num_chains} of {len(chain.expirations)} available chains: {available_expirations}")
                month_indices = list(range(len(available_expirations)))
            else:
                available_expirations = []
        
        all_rows = []
        
        for month_idx in month_indices:
            try:
                _, chain, expiration = get_stock_and_chain(ib, symbol, month_idx, exchange, currency)
                stock_price = stock_data['last'] or stock_data['close']
                
                min_strike, max_strike = get_strike_range_for_delta(chain, stock_price, expiration, min_delta=delta_min, max_delta=delta_max)
                if min_strike is None:
                    logger.warning(f"  {symbol} {expiration}: Keine Strikes im Delta-Bereich")
                    continue
                
                options = get_valid_put_options(ib, symbol, expiration, chain, exchange, min_strike, max_strike)
                if not options:
                    continue
                
                rows = fetch_option_greeks_batch(ib, options)
                filtered = filter_by_delta(rows, min_delta=delta_min, max_delta=delta_max)
                
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
        
        result = {
            'symbol': symbol,
            'stock_price': stock_data['last'] or stock_data['close'],
            'currency': currency,
            'expirations_processed': len(month_indices),
            'total_options': len(all_rows),
            'top5': top5
        }
        
        if keep_connected:
            result['ib'] = ib
            ib = None  # Don't disconnect in finally
        
        return result
        
    except Exception as e:
        logger.error(f"{symbol} failed: {e}")
        return {'symbol': symbol, 'error': str(e)}
    finally:
        if ib and ib.isConnected():
            ib.disconnect()


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


def write_master_html(results, filepath):
    """Erzeugt HTML-Report parallel zur CSV"""
    html_path = filepath.replace('.csv', '.html')
    
    # Daten für HTML aufbereiten
    rows = []
    for res in results:
        if 'error' in res:
            continue
        for r in res['top5']:
            row = {}
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
                row[h] = val if val is not None else ''
            rows.append(row)
    
    if not rows:
        return
    
    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>Option Scan Results</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 20px; background: #fafafa; }}
        h1 {{ color: #333; }}
        .meta {{ color: #666; margin-bottom: 20px; }}
        table {{ border-collapse: collapse; width: 100%; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th, td {{ padding: 10px 12px; text-align: right; border-bottom: 1px solid #eee; }}
        th {{ background: #f5f5f5; font-weight: 600; text-align: right; }}
        td.symbol {{ text-align: left; font-weight: 500; }}
        td.expiration {{ text-align: center; }}
        tr:hover {{ background: #fafafa; }}
        .profit {{ font-weight: 600; color: #2e7d32; }}
        .delta {{ color: #1565c0; }}
        .symbol-group {{ background: #f9f9f9; }}
    </style>
</head>
<body>
    <h1>Multi-Symbol Option Scan</h1>
    <p class="meta">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <table>
        <thead>
            <tr>
                {''.join(f'<th>{h}</th>' for h in HEADERS)}
            </tr>
        </thead>
        <tbody>
"""
    current_symbol = None
    for row in rows:
        sym = row.get('symbol', '')
        if sym != current_symbol:
            current_symbol = sym
            html += f'        <tr class="symbol-group"><td colspan="{len(HEADERS)}"><strong>{sym}</strong></td></tr>\n'
        html += '        <tr>\n'
        for h, val in row.items():
            cls = ''
            if h == 'symbol':
                cls = 'symbol'
            elif h == 'expiration':
                cls = 'expiration'
            elif h == 'put_profit':
                cls = 'profit'
            elif h == 'delta':
                cls = 'delta'
            html += f'            <td class="{cls}">{val}</td>\n'
        html += '        </tr>\n'
    
    html += """        </tbody>
    </table>
</body>
</html>"""
    
    with open(html_path, 'w') as f:
        f.write(html)
    
    logger.info(f"HTML Report: {html_path}")


def main():
    default_symbols = ['CROX', 'AAPL', 'TREX', 'TSLA', 'NVDA']
    default_month_indices = [0, 1, 2]
    
    # Argument parsing
    manual_mode = False
    delta_min = -0.50
    delta_max = -0.10
    num_chains = 0  # 0 = auto (use month_indices or default)
    if len(sys.argv) > 1:
        args = sys.argv[1:]
        symbols = []
        month_indices = []
        exchange = 'SMART'
        currency = 'USD'
        
        # Filter out -m/--manual flag
        filtered_args = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in ['-m', '--manual']:
                manual_mode = True
            elif arg in ['--delta-min', '--dmin'] and i + 1 < len(args):
                delta_min = float(args[i + 1])
                i += 1
            elif arg in ['--delta-max', '--dmax'] and i + 1 < len(args):
                delta_max = float(args[i + 1])
                i += 1
            elif arg in ['--chains', '--num-chains'] and i + 1 < len(args):
                num_chains = int(args[i + 1])
                i += 1
            else:
                filtered_args.append(arg)
            i += 1
        
        args = filtered_args
        
        for arg in args:
            if arg.isdigit():
                month_indices.append(int(arg))
            elif arg in ['SMART', 'XETRA', 'AEB', 'NYSE', 'NASDAQ', 'FWB', 'IBIS']:
                exchange = arg
            elif arg in ['USD', 'EUR']:
                currency = arg
            else:
                symbols.append(arg.upper())
        
        if not symbols:
            symbols = default_symbols
        if not month_indices and num_chains == 0:
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
    last_ib = None
    for i, symbol in enumerate(symbols):
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing {symbol} ({i+1}/{len(symbols)})...")
        
        defaults = SYMBOL_DEFAULTS.get(symbol, {'exchange': exchange, 'currency': currency})
        ex = exchange if exchange != 'SMART' else defaults['exchange']
        cur = currency if currency != 'USD' else defaults['currency']
        
        # Keep connection alive for the LAST symbol to reuse for orders
        keep_conn = (i == len(symbols) - 1)
        result = process_symbol(symbol, month_indices, ex, cur, 100 + i, keep_connected=keep_conn, delta_min=delta_min, delta_max=delta_max, num_chains=num_chains)
        results.append(result)
        
        if 'error' in result:
            logger.error(f"{symbol}: {result['error']}")
        else:
            logger.info(f"{symbol}: {len(result['top5'])} top options, stock={result['stock_price']} {result['currency']}")
            if keep_conn and 'ib' in result:
                last_ib = result['ib']
    
    # Master CSV
    write_master_csv(results, csv_file)
    write_master_html(results, csv_file)
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
    
    # Collect all top options for auto-order
        all_top_options = []
        for res in results:
            if 'error' in res:
                continue
            for r in res['top5']:
                all_top_options.append(r)
    
        if manual_mode:
            # MANUAL MODE: User selects which option(s) to trade
            print(f"\n{'='*80}")
            print(f"MANUAL MODE: Wählen Sie Option(en) zum Handeln")
            print(f"{'='*80}")
        
            # Show all options with numbers
            print(f"\nVerfügbare Optionen (Top 5 pro Symbol):")
            for idx, r in enumerate(all_top_options):
                exp_short = r['expiration'][4:] if len(r['expiration']) == 8 else r['expiration']
                # Calculate DTE (Days to Expiration)
                try:
                    exp_date = datetime.strptime(r['expiration'], '%Y%m%d')
                    dte = (exp_date - datetime.now()).days
                except:
                    dte = '?'
                print(f"  [{idx+1}] {r['symbol']} {r['strike']:.0f}P {exp_short} | DTE={dte}d | Delta={r['delta']:.4f} | Bid=${r['bid']:.2f} | Ask=${r['ask']:.2f} | Vol={r['volume']:.0f} | IV={r['impliedVol']:.1%} | Profit={r['put_profit']:.2f}%")
        
            print(f"\nEingabe: Nummern (z.B. '1', '1,3', '1 3') oder 'q' zum Beenden")
        
            ib = last_ib
            if not ib or not ib.isConnected():
                print("⚠️ Keine aktive Connection für Order.")
            else:
                while True:
                    choice = input("\nOption(en) wählen: ").strip().lower()
                    if choice in ['q', 'quit', 'exit']:
                        break
                
                    parts = choice.replace(',', ' ').split()
                    try:
                        indices = [int(p) - 1 for p in parts]
                        valid = [i for i in indices if 0 <= i < len(all_top_options)]
                        invalid = [i for i in indices if i < 0 or i >= len(all_top_options)]
                    
                        if invalid:
                            print(f"Ungültige Nummern: {[i+1 for i in invalid]}. Gültig: 1-{len(all_top_options)}")
                    
                        for idx in valid:
                            selected = all_top_options[idx]
                            # Place order for selected option
                            defaults = SYMBOL_DEFAULTS.get(selected['symbol'].upper(), {'exchange': 'SMART', 'currency': 'USD'})
                            exchange = defaults['exchange']
                            currency = defaults['currency']
                        
                            opt = Option(selected['symbol'], selected['expiration'], selected['strike'], 'P', exchange, tradingClass=selected['symbol'], multiplier=selected['multiplier'])
                            ib.qualifyContracts(opt)
                        
                            # Get mark price
                            ib.reqMktData(opt, '', False, False)
                            ib.sleep(2)
                            ticker = ib.ticker(opt)
                            mark_price = None
                            if hasattr(ticker, 'markPrice') and ticker.markPrice and not math.isnan(ticker.markPrice):
                                mark_price = ticker.markPrice
                            elif ticker.bid and ticker.ask and ticker.bid > 0 and ticker.ask > 0:
                                mark_price = (ticker.bid + ticker.ask) / 2
                            elif ticker.close and ticker.close > 0:
                                mark_price = ticker.close
                            else:
                                mark_price = ticker.bid
                            ib.cancelMktData(opt)
                        
                            limit_price = round(mark_price - 0.05, 2) if mark_price and mark_price > 0 else selected['bid']
                            print(f"\n>>> Platzieren SELL 1 {opt.localSymbol} @ ${limit_price:.2f} LMT (Mark: ${mark_price:.2f} - $0.05)")
                            placed = place_option_order(ib, opt, action='SELL', quantity=1, order_type='LMT', limit_price=limit_price, auto_transmit=False)
                            if placed:
                                print(f"✅ {selected['symbol']} PUT Order erfolgreich platziert!")
                            else:
                                print(f"❌ {selected['symbol']} Order nicht platziert.")
                    
                        if valid:
                            # Refresh positions
                            pass
                        
                    except ValueError:
                        print("Eingabe: Nummern (z.B. '1', '1,3', '1 3') oder 'q'")
        else:
            # AUTO MODE: Best PUT per Symbol
            print(f"\n{'='*80}")
            print(f"AUTO-ORDER: Best PUT Options per Symbol")
            print(f"{'='*80}")
        
            # Find best option per symbol - nur für gescannte Symbole
            for symbol in symbols:
                symbol_options = [r for r in all_top_options if r['symbol'] == symbol]
                if not symbol_options:
                    continue
            
                best = max(symbol_options, key=lambda x: x['put_profit'])
                print(f"\nBeste {symbol} Option: {best['symbol']} {best['strike']:.0f}P {best['expiration'][4:]}")
                print(f"Delta={best['delta']:.4f} | Bid=${best['bid']:.2f} | Put_Profit={best['put_profit']:.2f}%")
            
                # Use last connection
                ib = last_ib
                if ib and ib.isConnected():
                    try:
                        # Restore option contract
                        defaults = SYMBOL_DEFAULTS.get(best['symbol'].upper(), {'exchange': 'SMART', 'currency': 'USD'})
                        exchange = defaults['exchange']
                        currency = defaults['currency']
                    
                        opt = Option(best['symbol'], best['expiration'], best['strike'], 'P', exchange, tradingClass=best['symbol'], multiplier=best['multiplier'])
                        ib.qualifyContracts(opt)
                    
                        # Auto-place order (SELL 1 contract at MARK - 0.05) mit Bestätigung
                        # Marktdaten anfordern für Mark Price
                        ib.reqMktData(opt, '', False, False)
                        ib.sleep(2)
                        ticker = ib.ticker(opt)
                        # Fallback-Kette: markPrice -> mid (bid+ask)/2 -> close -> bid
                        mark_price = None
                        if hasattr(ticker, 'markPrice') and ticker.markPrice and not math.isnan(ticker.markPrice):
                            mark_price = ticker.markPrice
                        elif ticker.bid and ticker.ask and ticker.bid > 0 and ticker.ask > 0:
                            mark_price = (ticker.bid + ticker.ask) / 2
                        elif ticker.close and ticker.close > 0:
                            mark_price = ticker.close
                        else:
                            mark_price = ticker.bid
                        ib.cancelMktData(opt)
                    
                        limit_price = round(mark_price - 0.05, 2) if mark_price and mark_price > 0 else best['bid']
                        print(f">>> Platzieren SELL 1 {opt.localSymbol} @ ${limit_price:.2f} LMT (Mark: ${mark_price:.2f} - $0.05)")
                        placed = place_option_order(ib, opt, action='SELL', quantity=1, order_type='LMT', limit_price=limit_price, auto_transmit=False)
                        if placed:
                            print(f"✅ {symbol} PUT Order erfolgreich platziert!")
                        else:
                            print(f"❌ {symbol} Order nicht platziert.")
                    except Exception as e:
                        logger.error(f"Auto-Order {symbol} fehlgeschlagen: {e}")
                        print(f"Fehler: {e}")
                else:
                    print("⚠️ Keine aktive Connection für Auto-Order.")
                    break
    
        print(f"\n✅ Fertig!")


if __name__ == '__main__':
    main()