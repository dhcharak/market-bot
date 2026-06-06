import os

# ── PASTE YOUR API KEY BELOW ──────────────────────────────────────
from google.colab import userdata
os.environ["ANTHROPIC_API_KEY"] = userdata.get('ANTHROPIC_API_KEY')
# ─────────────────────────────────────────────────────────────────

PAPER_TRADING       = True
BANKROLL            = 5000
MIN_EDGE            = 0.10
KELLY_FRACTION      = 0.25
MAX_POSITION        = 500
MAX_MARKETS         = 500
SCANS_TO_RUN        = 999
SCAN_PAUSE_SECONDS  = 30

print("✅ Config ready")
print(f"   Bankroll : ${BANKROLL:,} USDC")
print(f"   Markets  : {MAX_MARKETS} per scan")
print(f"   Scans    : {SCANS_TO_RUN}")
