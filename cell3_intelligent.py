import requests
import json
import time
import re
from datetime import datetime, timezone, timedelta
import anthropic

GAMMA_API = "https://gamma-api.polymarket.com"
client = anthropic.Anthropic()
paper_trades = []
seen_pairs = set()
price_cache = {}
PRICE_MOVE_THRESHOLD = 0.04

def fetch_crypto():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids":"bitcoin,ethereum,solana,ripple","vs_currencies":"usd","include_24hr_change":"true"},
            timeout=10, headers={"User-Agent":"Mozilla/5.0"}
        )
        data = r.json()
        lines = []
        for coin, info in data.items():
            chg = info.get("usd_24h_change", 0) or 0
            arrow = "UP" if chg > 0 else "DOWN"
            lines.append(f"{coin.upper()}: ${info.get('usd',0):,.0f} ({arrow} {abs(chg):.1f}% 24h)")
        return "CRYPTO PRICES:\n" + "\n".join(lines)
    except Exception as e:
        return f"CRYPTO: unavailable ({e})"

def fetch_stocks():
    try:
        results = []
        for ticker, name in [("SPY","S&P500"),("QQQ","Nasdaq"),("DIA","Dow")]:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                params={"interval":"1d","range":"1d"},
                timeout=8, headers={"User-Agent":"Mozilla/5.0"}
            )
            data = r.json()
            meta = data.get("chart",{}).get("result",[{}])[0].get("meta",{})
            price = meta.get("regularMarketPrice", 0)
            prev = meta.get("previousClose", price)
            chg = ((price - prev) / prev * 100) if prev else 0
            arrow = "UP" if chg > 0 else "DOWN"
            results.append(f"{name}: ${price:.2f} ({arrow} {abs(chg):.1f}%)")
        return "STOCK MARKET:\n" + "\n".join(results)
    except Exception as e:
        return f"STOCKS: unavailable ({e})"

def fetch_news():
    try:
        headlines = []
        for url, source in [
            ("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC"),
            ("https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "NYT"),
        ]:
            try:
                r = requests.get(url, timeout=8, headers={"User-Agent":"Mozilla/5.0"})
                items = r.text.split("<item>")[1:6]
                for item in items:
                    if "<title>" in item:
                        title = item.split("<title>")[1].split("</title>")[0]
                        title = title.replace("<![CDATA[","").replace("]]>","").strip()
                        if title and len(title) > 15:
                            headlines.append(f"[{source}] {title}")
            except:
                continue
        if headlines:
            return "BREAKING NEWS:\n" + "\n".join(headlines[:8])
        return "NEWS: unavailable"
    except Exception as e:
        return f"NEWS: unavailable ({e})"

def fetch_sports():
    try:
        results = []
        endpoints = [
            ("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard", "NBA"),
            ("https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard", "MLB"),
        ]
        for url, league in endpoints:
            try:
                r = requests.get(url, timeout=8, headers={"User-Agent":"Mozilla/5.0"})
                data = r.json()
                for ev in data.get("events", [])[:5]:
                    comps = ev.get("competitions", [{}])[0]
                    competitors = comps.get("competitors", [])
                    status_obj = ev.get("status", {})
                    status = status_obj.get("type", {}).get("description", "")
                    clock = status_obj.get("displayClock", "")
                    period = status_obj.get("period", "")
                    status_full = f"Period {period} | {clock} remaining | {status}"
                    if len(competitors) == 2:
                        t1, t2 = competitors[0], competitors[1]
                        t1_name = t1.get("team", {}).get("abbreviation", "")
                        t1_score = t1.get("score", "")
                        t2_name = t2.get("team", {}).get("abbreviation", "")
                        t2_score = t2.get("score", "")
                        s = f"[{league}] {t1_name} {t1_score} vs {t2_name} {t2_score} | {status_full}"
                        results.append(s)
            except:
                continue
        return "SPORTS:\n" + "\n".join(results) if results else "SPORTS: no live games"
    except Exception as e:
        return f"SPORTS: unavailable ({e})"

def fetch_markets(limit=MAX_MARKETS):
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"active":"true","closed":"false","limit":limit,"order":"volume24hr","ascending":"false"},
            timeout=15
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  Market fetch failed: {e}")
        return []

def build_summary(markets):
    summary = []
    for m in markets:
        try:
            prices = m.get("outcomePrices", ["0.5","0.5"])
            yes_price = float(prices[0]) if prices else 0.5
        except:
            yes_price = 0.5
        total_vol = float(m.get("volume", 0) or 0)
        vol_24hr = float(m.get("volume24hr", 0) or 0)
        if total_vol < 5000:
            continue
        if yes_price == 0.5 and total_vol < 10000:
            continue
        q = m.get("question","").replace('"',"'").replace('\n',' ')[:100]
        summary.append({
            "id": m.get("conditionId","")[:16],
            "q": q,
            "y": round(yes_price, 2),
            "vol": round(total_vol),
            "vol_24hr": round(vol_24hr)
        })
    return summary

def find_changed_markets(summary):
    changed = []
    new_markets = []
    for m in summary:
        mid = m["id"]
        current_price = m["y"]
        if mid not in price_cache:
            new_markets.append(m)
            price_cache[mid] = current_price
        else:
            old_price = price_cache[mid]
            move = abs(current_price - old_price)
            if move >= PRICE_MOVE_THRESHOLD:
                changed.append(m)
                print(f"  PRICE MOVE: {m['q'][:50]} | {old_price*100:.0f}% -> {current_price*100:.0f}%")
                price_cache[mid] = current_price
    return changed, new_markets

def claude_identify_needs(titles):
    try:
        titles_text = "\n".join([f"- {t}" for t in titles[:50]])
        prompt = f"""These Polymarket markets need analysis. What real-world data do you need?

{titles_text}

Respond with ONLY this JSON:
{{"need_crypto": true, "need_stocks": true, "need_sports": true, "need_news": true}}"""
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            messages=[{"role":"user","content":prompt}]
        )
        raw = response.content[0].text.strip()
        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1:
            return json.loads(raw[start:end+1])
    except:
        pass
    return {"need_crypto":True,"need_stocks":True,"need_sports":True,"need_news":True}

def build_context(needs):
    ast_tz = timezone(timedelta(hours=-4))
    now_ast = datetime.now(ast_tz)
    sections = [f"DATE/TIME: {now_ast.strftime('%A %B %d, %Y %H:%M')} Puerto Rico Time (AST)"]
    if needs.get("need_crypto"):
        sections.append(fetch_crypto())
    if needs.get("need_stocks"):
        sections.append(fetch_stocks())
    if needs.get("need_news"):
        sections.append(fetch_news())
    if needs.get("need_sports"):
        sections.append(fetch_sports())
    return "\n\n".join(sections)

def ask_claude(markets_to_analyze, all_markets, context):
    if not markets_to_analyze:
        return []
    all_text = "\n".join([
        f"{m['y']*100:.0f}% YES | vol:${m['vol']:,} | 24h:${m['vol_24hr']:,} | {m['q']} | id={m['id']}"
        for m in all_markets
    ])
    focus_text = "\n".join([
        f"*** TRIGGERED: {m['y']*100:.0f}% YES | {m['q']} | id={m['id']}"
        for m in markets_to_analyze
    ])
    prompt = f"""You are a prediction market arbitrage expert.

REAL WORLD CONTEXT:
{context}

MARKETS THAT TRIGGERED THIS SCAN:
{focus_text}

ALL ACTIVE MARKETS FOR COMPARISON:
{all_text}

Find opportunities:
1. LOGICAL_ARBITRAGE: Mathematically impossible pricing between related markets
2. REALITY_MISPRICING: Market price conflicts with real-world context above
   - For sports: Use score and time remaining to assess win probability naturally
   - For crypto: Use actual prices from context
   - For news: Use breaking headlines and deadlines vs current date/time

Return ONLY valid JSON array:
[
  {{
    "a_id": "id",
    "a_q": "question",
    "a_y": 0.50,
    "b_id": "",
    "b_q": "",
    "b_y": 0.0,
    "type": "logical_arbitrage or reality_mispricing",
    "action": "buy_no_A or buy_yes_A or buy_no_B or buy_yes_B",
    "edge": 0.15,
    "conf": 0.80,
    "reason": "specific reason with data from context"
  }}
]

Only include edge >= 0.08 AND conf >= 0.60. If nothing qualifies return: []"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role":"user","content":prompt}]
        )
        raw = response.content[0].text.strip()
        start = raw.find('[')
        end = raw.rfind(']')
        if start != -1 and end != -1:
            json_str = raw[start:end+1]
            try:
                opps = json.loads(json_str)
                if isinstance(opps, list):
                    return opps
            except:
                json_str = re.sub(r',\s*}', '}', json_str)
                json_str = re.sub(r',\s*]', ']', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass
    except Exception as e:
        print(f"  Claude error: {e}")
    return []

def kelly_size(edge, conf):
    adj = edge * conf
    if adj <= 0:
        return 0
    k = (adj / (1 - adj)) * KELLY_FRACTION
    return round(min(BANKROLL * k, MAX_POSITION), 2)

def show_opportunity(opp, position):
    print("\n" + "="*62)
    print(f"  OPPORTUNITY: {opp.get('type','').upper()}")
    print(f"  Market A : {opp.get('a_q','')[:65]}")
    print(f"  Price A  : {opp.get('a_y',0)*100:.0f}% YES")
    if opp.get('b_q'):
        print(f"  Market B : {opp.get('b_q','')[:65]}")
        print(f"  Price B  : {opp.get('b_y',0)*100:.0f}% YES")
    print(f"  Action   : {opp.get('action','')}")
    print(f"  Edge     : {opp.get('edge',0)*100:.1f}%  |  Conf: {opp.get('conf',0)*100:.0f}%")
    print(f"  Size     : ${position} USDC")
    print(f"  Reason   : {opp.get('reason','')}")
    print("="*62)

def run_scan(scan_num):
    print(f"\n{'─'*62}")
    print(f"  SCAN #{scan_num} | {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'─'*62}")
    markets = fetch_markets()
    if not markets:
        return 0
    summary = build_summary(markets)
    print(f"  {len(summary)} markets with total volume > $5,000")
    changed, new_markets = find_changed_markets(summary)
    total_triggers = len(changed) + len(new_markets)
    if new_markets:
        print(f"  {len(new_markets)} NEW markets discovered")
    if changed:
        print(f"  {len(changed)} markets with significant price moves")
    if total_triggers == 0:
        print(f"  No changes — skipping Claude | Cache: {len(price_cache)} markets tracked")
        return 0
    print(f"  Triggered! Calling Claude to analyze {total_triggers} markets...")
    markets_to_analyze = changed + new_markets
    titles = [m["q"] for m in markets_to_analyze]
    needs = claude_identify_needs(titles)
    context = build_context(needs)
    opps = ask_claude(markets_to_analyze, summary, context)
    new_count = 0
    for opp in opps:
        edge = float(opp.get("edge", 0))
        conf = float(opp.get("conf", 0))
        if edge < 0.08 or conf < 0.6:
            continue
        pair_key = tuple(sorted([opp.get("a_q","")[:50], opp.get("b_q","")[:50]]))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        pos = kelly_size(edge, conf)
        show_opportunity(opp, pos)
        paper_trades.append({
            "scan": scan_num,
            "timestamp": datetime.now().isoformat(),
            "type": opp.get("type"),
            "market_a": opp.get("a_q","")[:100],
            "market_b": opp.get("b_q","")[:100],
            "action": opp.get("action"),
            "edge": edge,
            "conf": conf,
            "position_usdc": pos,
            "reason": opp.get("reason","")
        })
        new_count += 1
    print(f"  {new_count} new opportunities logged")
    return new_count

print("POLYMARKET BOT V3 LOADED")
print("  Price-change triggered scanning")
print("  Sports: clock + period + score in context")
print("  Sports: Claude judges timing naturally")
print("  Min total volume: $5,000 | Skips 50/50 defaults under $10k")
print("  Timezone: Puerto Rico AST (UTC-4)")
