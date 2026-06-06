print("🤖 POLYMARKET INTELLIGENT BOT STARTING")
print(f"   Mode     : {'PAPER TRADING ✅' if PAPER_TRADING else '⚠️  LIVE'}")
print(f"   Bankroll : ${BANKROLL:,} USDC")
print(f"   Scans    : {SCANS_TO_RUN}")
print()

total = 0
for scan_num in range(1, SCANS_TO_RUN + 1):
    found = run_scan(scan_num)
    total += found
    if scan_num < SCANS_TO_RUN:
        print(f"\n  Waiting {SCAN_PAUSE_SECONDS}s...")
        time.sleep(SCAN_PAUSE_SECONDS)

print(f"\n{'='*62}")
print(f"  DONE")
print(f"  Total scans       : {SCANS_TO_RUN}")
print(f"  New opportunities : {total}")
print(f"  Unique pairs seen : {len(seen_pairs)}")
print(f"  Paper trades log  : {len(paper_trades)}")
print(f"{'='*62}")

# Print summary
if paper_trades:
    print(f"\n📊 ALL OPPORTUNITIES FOUND:\n")
    for i, t in enumerate(paper_trades, 1):
        print(f"[{i}] {t['type'].upper()}")
        print(f"    A: {t['market_a'][:70]}")
        if t['market_b']:
            print(f"    B: {t['market_b'][:70]}")
        print(f"    Action: {t['action']} | Edge: {t['edge']*100:.0f}% | Conf: {t['conf']*100:.0f}% | Size: ${t['position_usdc']}")
        print(f"    Reason: {t['reason'][:100]}")
        print()
