#!/usr/bin/env python3
"""SwingPilot: rules-based, end-of-day PAPER trader. No broker credentials/orders."""
import datetime as dt
import json
import math
import os
import pathlib
import statistics
import sys
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH = ROOT / 'docs' / 'data' / 'state.json'
CONFIG = ROOT / 'config.json'
TODAY = dt.datetime.now(dt.timezone.utc).date()


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8') + '\n'
    temp.replace(path)


def api_call(params):
    key = os.getenv('TWELVEDATA_API_KEY')
    if not key:
        raise RuntimeError('TWELVEDATA_API_KEY fehlt. Keine Kursdaten, keine Trades.')
    params['apikey'] = key
    url = 'https://api.twelvedata.com/' + params.pop('_endpoint') + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent':'SwingPilotPaper/0.2'})
    with urllib.request.urlopen(req, timeout=25) as response:
        result = json.load(response)
    if result.get('status') == 'error' or result.get('code'):
        raise RuntimeError(str(result.get('message', result)))
    return result


def candles(symbol):
    data = api_call({'_endpoint':'time_series','symbol':symbol,'interval':'1day','outputsize':95,'format':'JSON'})
    arr = []
    for row in data.get('values', []):
        try:
            date=dt.date.fromisoformat(row['datetime'][:10]); close=float(row['close']); high=float(row['high']); low=float(row['low'])
            if close>0 and math.isfinite(close) and math.isfinite(high) and math.isfinite(low):
                arr.append({'date':date.isoformat(),'close':close,'high':high,'low':low})
        except (ValueError,KeyError,TypeError):
            pass
    return sorted(arr,key=lambda x:x['date'])


def sma(values,n):
    return sum(values[-n:])/n if len(values)>=n else None


def rsi(values,n=14):
    if len(values) < n+1:return None
    diffs=[values[i]-values[i-1] for i in range(len(values)-n,len(values))]
    gain=sum(max(x,0) for x in diffs)/n; loss=sum(max(-x,0) for x in diffs)/n
    if loss==0:return 100.0 if gain>0 else 50.0
    return 100-100/(1+gain/loss)


def score(c):
    # Signal is computed using PRIOR completed session only; next session's close is used as a conservative proxy fill.
    p=c[:-1]
    if len(p)<51:return None
    closes=[x['close'] for x in p]
    ma20=sma(closes,20); ma50=sma(closes,50); r=rsi(closes)
    ret5=closes[-1]/closes[-6]-1
    buy=(closes[-1]>ma20>ma50 and 43<=r<=72 and ret5>0)
    sell=(closes[-1]<ma20 or r>=79)
    strength=(closes[-1]/ma20-1)*100 + ret5*100 + (ma20/ma50-1)*35
    return {'buy':buy,'sell':sell,'score':round(strength,3),'rsi':round(r,1),'sma20':round(ma20,3),'sma50':round(ma50,3),'prior_date':p[-1]['date']}


def fee(chf_gross,market):
    # User-confirmed illustrative Swissquote costs; not binding fee schedule.
    return 5.0 if market=='SIX' else 4.8


def main():
    cfg=load_json(CONFIG); state=load_json(PATH)
    today=TODAY.isoformat()
    if today>cfg['end_date']:
        state['status']='finished'; save_json(PATH,state);return
    if today<cfg['start_date']:
        print('Not started yet');return
    if not os.getenv('TWELVEDATA_API_KEY'):
        print('No data key; no changes');return
    series={}; problems=[]
    for item in cfg['universe']:
        try:
            a=candles(item['provider_symbol'])
            if len(a)<52:raise RuntimeError('weniger als 52 Tageskurse')
            series[item['ticker']]=a
        except Exception as e:
            problems.append(f"{item['ticker']}: {e}")
    try:
        fx=candles('USD/CHF')
        usdchf=fx[-1]['close'] if fx and fx[-1]['date']>= (TODAY-dt.timedelta(days=5)).isoformat() else None
    except Exception as e:
        usdchf=None; problems.append('USD/CHF: '+str(e))
    if not usdchf or not 0.5<usdchf<1.5:
        state['last_error']='Kein gültiger aktueller USD/CHF-Kurs. Keine Transaktionen. '+ '; '.join(problems)
        save_json(PATH,state); return
    # only use closed bars older than current UTC date, not provisional same-day prices
    closed={k:[x for x in v if x['date'] < today] for k,v in series.items()}
    candidates={k:v for k,v in closed.items() if len(v)>=52}
    if not candidates:
        state['last_error']='Keine belastbaren abgeschlossenen Kurse. '+'; '.join(problems)
        save_json(PATH,state);return
    latest=max(x[-1]['date'] for x in candidates.values())
    if any(h['date']==latest for h in state.get('history',[])):
        print('Already processed',latest);return
    assets={i['ticker']:i for i in cfg['universe']}
    valid={k:v for k,v in candidates.items() if v[-1]['date']==latest and len(v)>=52}
    prices={k:round(v[-1]['close']*(usdchf if assets[k]['currency']=='USD' else 1),5) for k,v in valid.items()}
    signals={k:score(v) for k,v in valid.items()}
    # one trade per session, maximum holding exposure 35%, minimum order 150 CHF
    nav=state['cash_chf']+sum(q*prices.get(k,state.get('marks_chf',{}).get(k,0)) for k,q in state['positions'].items())
    trade=None
    for k,qty in list(state['positions'].items()):
        if qty and k in signals and signals[k]['sell']:
            gross=qty*prices[k]; cost=fee(gross,assets[k]['market'])+gross*(.005 if assets[k]['currency']=='USD' else 0)
            state['cash_chf']=round(state['cash_chf']+gross-cost,2);state['positions'][k]=0
            trade={'date':latest,'ticker':k,'side':'SELL','qty':qty,'unit_chf':round(prices[k],4),'gross_chf':round(gross,2),'cost_chf':round(cost,2),'reason':'Signal vom Vortag: unter SMA20 oder RSI >=79'}
            break
    if trade is None:
        ranked=sorted(((s['score'],k) for k,s in signals.items() if s and s['buy'] and state['positions'].get(k,0)==0),reverse=True)
        for _,k in ranked:
            budget=min(state['cash_chf']-max(nav*.10,60),nav*.35)
            qty=int((budget-fee(budget,assets[k]['market']))/prices[k]/(1.005 if assets[k]['currency']=='USD' else 1))
            if qty<=0 or qty*prices[k]<150:continue
            gross=qty*prices[k];cost=fee(gross,assets[k]['market'])+gross*(.005 if assets[k]['currency']=='USD' else 0)
            if gross+cost>state['cash_chf']-max(nav*.10,60):continue
            state['cash_chf']=round(state['cash_chf']-gross-cost,2);state['positions'][k]=qty
            trade={'date':latest,'ticker':k,'side':'BUY','qty':qty,'unit_chf':round(prices[k],4),'gross_chf':round(gross,2),'cost_chf':round(cost,2),'reason':'Vortag: Kurs > SMA20 > SMA50, RSI 43–72, Momentum positiv'}
            break
    if trade:state['trades'].append(trade)
    state['marks_chf'].update(prices)
    nav=state['cash_chf']+sum(q*state['marks_chf'].get(k,0) for k,q in state['positions'].items())
    state['history'].append({'date':latest,'nav_chf':round(nav,2),'cash_chf':round(state['cash_chf'],2),'usdchf':round(usdchf,5)})
    state['last_update']=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    state['last_error']='; '.join(problems) if problems else None
    state['signals']={k:{**s,'price_chf':round(prices[k],2)} for k,s in signals.items()}
    state['data_source']='Twelve Data (nicht Swissquote), Tagesschlusskurse, approximierte Fills und modellierte Gebühren'
    save_json(PATH,state)
    print('Processed',latest,trade,'NAV',round(nav,2))

if __name__=='__main__':main()
