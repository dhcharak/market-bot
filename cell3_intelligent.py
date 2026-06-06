import requests
import json
import time
import re
from datetime import datetime
import anthropic
 
GAMMA_API = "https://gamma-api.polymarket.com"
client = anthropic.Anthropic()
paper_trades = []
seen_pairs = set()
 
 
# ── DATA FETCHERS ─────────────────────────────────────────────────────────────
 
def fetch_crypto():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids":"bitcoin,ethereum,solana,ripple,dogecoin","vs_currencies":"usd","include_24hr_change":"true"},
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
            return "BREAKING NEWS:\n" + "\n".join(headlines[:10])
        return "NEWS: unavailable"
    except Exception as e:
        return f"NEWS: unavailable ({e})"
 
def fetch_sports():
    try:
        results = []
        endpoints = [
            ("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard","NBA"),
            ("https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard","MLB"),
            ("https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard","MLS"),
        ]
        for url, league in endpoints:
            try:
                r = requests.get(url, timeout=8, headers={"User-Agent":"Mozilla/5.0"})
                data = r.json()
                events = data.get("events", [])[:3]
                for ev in events:
                    comps = ev.get("competitions",[{}])[0]
                    competitors = comps.get("competitors",[])
                    status = ev.get("status",{}).get("type",{}).get("description","")
                    if len(competitors) == 2:
                        t1, t2 = competitors[0], competitors[1]
                        s = f"[{league}] {t1.get('team',{}).get('abbreviation','')} {t1.get('score','')} vs {t2.get('team',{}).get('abbreviation','')} {t2.get('score','')} ({status})"
                        results.append(s)
            except:
                continue
        if results:
            return "SPORTS SCORES:\n" + "\n".join(results)
        return "SPORTS: no live games"
    except Exception as e:
        return f"SPORTS: unavailable ({e})"
 
def fetch_spacex():
    try:
        r = requests.get("https://api.spacexdata.com/v5/launches/next", timeout=8)
        data = r.json()
        name = data.get("name","")
        date = data.get("date_utc","")[:10]
        return f"SPACEX NEXT LAUNCH: {name} on {date}"
    except:
        return "SPACEX: unavailable"
 
def fetch_weather_major_cities():
    try:
        cities = [
            ("New York", 40.71, -74.01),
            ("London", 51.51, -0.13),
            ("Miami", 25.77, -80.19),
        ]
        results = []
        for city, lat, lon in cities:
            r = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude":lat,"longitude":lon,"current_weather":True},
                timeout=8
            )
            data = r.json()
            temp_c = data.get("current_weather",{}).get("temperature","?")
            temp_f = round(temp_c * 9/5 + 32) if isinstance(temp_c, (int,float)) else "?"
            results.append(f"{city}: {temp_f}°F")
        return "WEATHER: " + " | ".join(results)
    except Exception as e:
        return f"WEATHER: unavailable ({e})"
 
 
# ── STEP 1: CLAUDE DECIDES WHAT CONTEXT IS NEEDED ────────────────────────────
 
def claude_identify_context_needs(market_titles):
    """Send just the market titles to Claude and ask what real-world data it needs."""
    titles_text = "\n".join([f"- {t}" for t in market_titles[:80]])
 
    prompt = f"""You are analyzing Polymarket prediction markets. Here are the active market titles:
 
{titles_text}
 
To accurately assess whether these markets are correctly priced, what real-world data do you need RIGHT NOW?
 
Respond with ONLY a JSON object listing what data sources would help:
{{
  "need_crypto": true or false,
  "need_stocks": true or false,
  "need_sports": true or false,
  "need_news": true or false,
  "need_spacex": true or false,
  "need_weather": true or false,
  "key_questions": ["list of 3-5 specific real-world facts that would most help you find mispricings"]
}}
 
Be selective — only request what is genuinely relevant to these specific markets."""
 
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role":"user","content":prompt}]
        )
        raw = response.content[0].text.strip()
        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1:
            return json.loads(raw[start:end+1])
    except Exception as e:
        print(f"  ⚠️ Context identification failed: {e}")
 
    # Default — fetch everything
    return {"need_crypto":True,"need_stocks":True,"need_sports":True,"need_news":True,"need_spacex":False,"need_weather":False,"key_questions":[]}
 
 
# ── STEP 2: FETCH ONLY WHAT'S NEEDED ─────────────────────────────────────────
 
def build_smart_context(needs):
    """Fetch only the data sources Claude said it needs."""
    print("  🌍 Fetching targeted real-world context...")
    sections = [f"CURRENT DATE/TIME: {datetime.now().strftime('%A %B %d, %Y %H:%M UTC')}"]
 
    if needs.get("need_crypto"):
        print("     → crypto prices")
        sections.append(fetch_crypto())
 
    if needs.get("need_stocks"):
        print("     → stock market")
        sections.append(fetch_stocks())
 
    if needs.get("need_news"):
        print("     → breaking news")
        sections.append(fetch_news())
 
    if needs.get("need_sports"):
        print("     → sports scores")
        sections.append(fetch_sports())
 
    if needs.get("need_spacex"):
        print("     → SpaceX")
        sections.append(fetch_spacex())
 
    if needs.get("need_weather"):
        print("     → weather")
        sections.append(fetch_weather_major_cities())
 
    if needs.get("key_questions"):
        sections.append("KEY QUESTIONS CLAUDE FLAGGED:\n" + "\n".join([f"- {q}" for q in needs["key_questions"]]))
 
    return "\n\n".join(sections)
 
 
# ── POLYMARKET DATA ───────────────────────────────────────────────────────────
 
def fetch_markets():
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"active":"true","closed":"false","limit":MAX_MARKETS,"order":"volume24hr","ascending":"false"},
            timeout=15
        )
        resp.raise_for_status()
        markets = resp.json()
        print(f"  ✅ Fetched {len(markets)} markets")
        return markets
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return []
 
def build_summary(markets):
    summary = []
    for m in markets:
        try:
            prices = m.get("outcomePrices", ["0.5","0.5"])
            yes_price = float(prices[0]) if prices else 0.5
        except:
            yes_price = 0.5
        vol = float(m.get("volume", 0) or 0)
        if vol < 500:
            continue
        q = m.get("question","").replace('"',"'").replace('\n',' ')[:100]
        summary.append({"id":m.get("conditionId","")[:16],"q":q,"y":round(yes_price,2),"vol":round(vol)})
    return summary
 
 
# ── STEP 3: CLAUDE FINDS OPPORTUNITIES WITH FULL CONTEXT ─────────────────────
 
def ask_claude(summary, context):
    all_opps = []
    batch_size = 25
    for i in range(0, len(summary), batch_size):
        batch = summary[i:i+batch_size]
        batch_num = (i // batch_size) + 1
        print(f"  Analyzing batch {batch_num} ({len(batch)} markets)...")
 
        lines = [f"{j+1}. {m['y']*100:.0f}% YES | vol:${m['vol']:,} | {m['q']} | id={m['id']}" for j,m in enumerate(batch)]
        market_text = "\n".join(lines)
 
        prompt = f"""You are a prediction market arbitrage expert.
 
═══ REAL WORLD CONTEXT ═══
{context}
══════════════════════════
 
MARKETS:
{market_text}
 
Find TWO types of opportunities:
 
1. LOGICAL_ARBITRAGE — mathematically impossible pricing between related markets
   The stricter/harder condition MUST always be priced lower
   "BTC above $70k" cannot be >= "BTC above $68k"
   "wins championship" cannot be >= "reaches finals"
   "event by June 30" cannot be >= "event by Dec 31"
 
2. REALITY_MISPRICING — market priced near 50% but real-world context makes outcome clear
   Use the context above to determine if outcome is nearly certain or nearly impossible
   If nearly IMPOSSIBLE → action is buy_no (you buy NO at ~50 cents, collect $1 when it fails)
   If nearly CERTAIN → action is buy_yes (you buy YES at ~50 cents, collect $1 when it happens)
 
Always explain WHY using specific numbers from the context.
 
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
    "action": "buy_no_A or buy_yes_A or buy_no_B or buy_yes_B or buy_no_A_and_no_B or buy_yes_A_and_no_B",
    "edge": 0.20,
    "conf": 0.85,
    "reason": "specific reason using real numbers from context"
  }}
]
 
If nothing qualifies return: []
Only include edge >= 0.10 AND conf >= 0.60"""
 
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                messages=[{"role":"user","content":prompt}]
            )
            raw = response.content[0].text.strip()
            start = raw.find('[')
            end = raw.rfind(']')
            if start != -1 and end != -1 and end > start:
                json_str = raw[start:end+1]
                try:
                    batch_opps = json.loads(json_str)
                    if isinstance(batch_opps, list) and batch_opps:
                        all_opps.extend(batch_opps)
                        print(f"  🎯 {len(batch_opps)} opportunities in batch {batch_num}!")
                except json.JSONDecodeError:
                    json_str = re.sub(r',\s*}', '}', json_str)
                    json_str = re.sub(r',\s*]', ']', json_str)
                    try:
                        batch_opps = json.loads(json_str)
                        if isinstance(batch_opps, list) and batch_opps:
                            all_opps.extend(batch_opps)
                    except:
                        print(f"  ⚠️ Could not parse batch {batch_num}")
        except Exception as e:
            print(f"  ⚠️ Batch {batch_num} error: {e}")
    return all_opps
 
 
# ── POSITION SIZING + DISPLAY ─────────────────────────────────────────────────
 
def kelly_size(edge, conf):
    adj = edge * conf
    if adj <= 0: return 0
    k = (adj / (1 - adj)) * KELLY_FRACTION
    return round(min(BANKROLL * k, MAX_POSITION), 2)
 
def show_opportunity(opp, position):
    print("\n" + "="*62)
    print(f"  🎯 {opp.get('type','').upper()}")
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
 
 
# ── MAIN SCAN ─────────────────────────────────────────────────────────────────
 
def run_scan(scan_num):
    print(f"\n{'─'*62}")
    print(f"  SCAN #{scan_num} | {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'─'*62}")
 
    # Fetch markets first
    markets = fetch_markets()
    if not markets: return 0
    summary = build_summary(markets)
    print(f"  📊 {len(summary)} markets with volume > $500")
 
    # Step 1 — Claude identifies what context it needs
    print("  🧠 Claude identifying what context is needed...")
    titles = [m["q"] for m in summary]
    needs = claude_identify_context_needs(titles)
    print(f"  📋 Needs: crypto={needs.get('need_crypto')} stocks={needs.get('need_stocks')} news={needs.get('need_news')} sports={needs.get('need_sports')}")
 
    # Step 2 — Fetch only what's needed
    context = build_smart_context(needs)
 
    # Step 3 — Claude analyzes with full context
    opps = ask_claude(summary, context)
 
    new_count = 0
    total_found = 0
    for opp in opps:
        edge = float(opp.get("edge",0))
        conf = float(opp.get("conf",0))
        if edge < MIN_EDGE or conf < 0.6: continue
        total_found += 1
        pair_key = tuple(sorted([opp.get("a_q","")[:50], opp.get("b_q","")[:50]]))
        if pair_key in seen_pairs:
            print(f"  ⏭️  Already logged: {opp.get('a_q','')[:45]}...")
            continue
        seen_pairs.add(pair_key)
        pos = kelly_size(edge, conf)
        show_opportunity(opp, pos)
        paper_trades.append({
            "scan":scan_num,
            "timestamp":datetime.now().isoformat(),
            "type":opp.get("type"),
            "market_a":opp.get("a_q","")[:100],
            "market_b":opp.get("b_q","")[:100],
            "action":opp.get("action"),
            "edge":edge,
            "conf":conf,
            "position_usdc":pos,
            "reason":opp.get("reason","")
        })
        new_count += 1
 
    print(f"\n  ✅ {new_count} NEW | {total_found} found | {len(seen_pairs)} unique pairs tracked")
    if total_found == 0:
        print("  No opportunities this scan")
    return new_count
 
print("✅ INTELLIGENT BOT LOADED")
print("   Step 1: Claude reads market titles → decides what context it needs")
print("   Step 2: Bot fetches ONLY that context (crypto/stocks/news/sports/weather/SpaceX)")
print("   Step 3: Claude analyzes markets with full real-world awareness")
print("   Sources: CoinGecko + Yahoo Finance + BBC/NYT RSS + ESPN + Open-Meteo + SpaceX API")
