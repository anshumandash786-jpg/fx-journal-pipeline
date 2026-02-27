"""
setup_sheets.py — Edgewonk-style analytics dashboard builder.

Creates 3 tabs in the Google Sheet:
  1. TradeLog  — Raw trade data (pipeline writes here)
  2. Analytics — Full performance metrics + embedded charts
  3. Filtered  — Same metrics but for user-filtered subsets

Usage:
    python scripts/setup_sheets.py

This is idempotent — safe to re-run. It will overwrite existing
Analytics and Filtered tabs but preserve TradeLog data.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gspread
from google.oauth2.service_account import Credentials
from config.settings import GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_FILE
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("setup_sheets")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ═══════════════════════════════════════════════
# TRADELOG TAB — Column definitions
# ═══════════════════════════════════════════════
TRADELOG_HEADERS = [
    "Trade ID",        # A
    "Date",            # B
    "Pair",            # C
    "Session",         # D
    "Direction",       # E
    "Entry Price",     # F
    "Stop Loss",       # G
    "Take Profit",     # H
    "Exit Price",      # I
    "Outcome",         # J
    "SL Pips",         # K  (auto-calc)
    "TP Pips",         # L  (auto-calc)
    "Result Pips",     # M  (auto-calc)
    "RR Ratio",        # N  (auto-calc)
    "R-Multiple",      # O  (auto-calc)
    "P&L ($)",         # P  (auto-calc)
    "Position Size",   # Q
    "MAE Pips",        # R
    "MFE Pips",        # S
    "MAE % of SL",     # T  (auto-calc)
    "MFE % of TP",     # U  (auto-calc)
    "Trade Duration",  # V
    "HTF Reference",   # W
    "Direction Thesis", # X
    "Location Zone",   # Y
    "Location TF",     # Z
    "Location Thesis", # AA
    "Execution Model", # AB
    "Execution TF",    # AC
    "Execution Thesis", # AD
    "Confluence",      # AE
    "Conviction",      # AF
    "Mistakes",        # AG
    "Post-Trade Review", # AH
    "Dir Screenshot",  # AI
    "Loc Screenshot",  # AJ
    "Exec Screenshot", # AK
    "Cumulative R",    # AL  (auto-calc)
    "Cumulative P&L",  # AM  (auto-calc)
    "Equity Peak",     # AN  (auto-calc)
    "Drawdown ($)",    # AO  (auto-calc)
]


def get_tradelog_row_formulas(row: int) -> dict:
    """
    Return auto-calculated formulas for a given TradeLog row.
    These formulas are placed in the row template and auto-fill when data is entered.
    """
    r = row  # shorthand
    return {
        # K: SL Pips = |Entry - SL| × pip multiplier
        "K": f'=IF(F{r}="","",IF(REGEXMATCH(C{r},"JPY"),ABS(F{r}-G{r})*100,ABS(F{r}-G{r})*10000))',
        # L: TP Pips = |TP - Entry| × pip multiplier
        "L": f'=IF(F{r}="","",IF(H{r}="","",IF(REGEXMATCH(C{r},"JPY"),ABS(H{r}-F{r})*100,ABS(H{r}-F{r})*10000)))',
        # M: Result Pips = (Exit - Entry) × direction × pip multiplier
        "M": f'=IF(I{r}="","",IF(E{r}="Long",IF(REGEXMATCH(C{r},"JPY"),(I{r}-F{r})*100,(I{r}-F{r})*10000),IF(REGEXMATCH(C{r},"JPY"),(F{r}-I{r})*100,(F{r}-I{r})*10000)))',
        # N: RR Ratio = TP Pips / SL Pips
        "N": f'=IF(OR(K{r}="",K{r}=0,L{r}=""),"",L{r}/K{r})',
        # O: R-Multiple = Result Pips / SL Pips
        "O": f'=IF(OR(K{r}="",K{r}=0,M{r}=""),"",M{r}/K{r})',
        # P: P&L ($) = Result Pips × pip value × lot size (approx $10/pip per standard lot)
        "P": f'=IF(M{r}="","",M{r}*IF(Q{r}="",0.01,Q{r})*10)',
        # T: MAE % of SL
        "T": f'=IF(OR(R{r}="",K{r}="",K{r}=0),"",R{r}/K{r}*100)',
        # U: MFE % of TP
        "U": f'=IF(OR(S{r}="",L{r}="",L{r}=0),"",S{r}/L{r}*100)',
        # AL: Cumulative R
        "AL": f'=IF(O{r}="","",IF({r}=2,O{r},AL{r-1}+O{r}))',
        # AM: Cumulative P&L
        "AM": f'=IF(P{r}="","",IF({r}=2,P{r},AM{r-1}+P{r}))',
        # AN: Equity Peak
        "AN": f'=IF(AM{r}="","",IF({r}=2,AM{r},MAX(AN{r-1},AM{r})))',
        # AO: Drawdown ($)
        "AO": f'=IF(AN{r}="","",AN{r}-AM{r})',
    }


# ═══════════════════════════════════════════════
# ANALYTICS TAB — Layout
# ═══════════════════════════════════════════════

def build_analytics_cells() -> list[list]:
    """
    Build the Analytics tab content — KPIs, breakdowns, and metric sections.
    All formulas reference the TradeLog tab.
    Returns a 2D list of cell values.
    """
    TL = "TradeLog"  # sheet reference

    # Helper: wrap formula to reference TradeLog
    def tl(col, start=2, end=500):
        return f"'{TL}'!{col}{start}:{col}{end}"

    cells = []

    # ── ROW 1-2: HEADER ──
    cells.append(["═══ FX JOURNAL ANALYTICS DASHBOARD ═══", "", "", "", "", "", "", ""])
    cells.append([""])

    # ── ROW 3: KPI LABELS ──
    cells.append([
        "Total Trades", "Wins", "Losses", "Breakeven",
        "Win Rate %", "Loss Rate %", "Profit Factor", "Expectancy (R)"
    ])

    # ── ROW 4: KPI VALUES ──
    cells.append([
        f'=COUNTA({tl("A")})',  # Total Trades
        f'=COUNTIF({tl("J")},"Win")',  # Wins
        f'=COUNTIF({tl("J")},"Loss")',  # Losses
        f'=COUNTIF({tl("J")},"Breakeven")+COUNTIF({tl("J")},"BE")',  # BE
        f'=IF(A4=0,"",B4/A4*100)',  # Win Rate
        f'=IF(A4=0,"",C4/A4*100)',  # Loss Rate
        f'=IF(SUMPRODUCT(({tl("J")}="Loss")*{tl("P")})=0,"∞",-SUMPRODUCT(({tl("J")}="Win")*{tl("P")})/SUMPRODUCT(({tl("J")}="Loss")*{tl("P")}))',  # PF
        f'=IF(A4=0,"",AVERAGE({tl("O")}))',  # Expectancy R
    ])

    cells.append([""])

    # ── ROW 6: KPI LABELS 2 ──
    cells.append([
        "Total R", "Total P&L ($)", "Avg Win (R)", "Avg Loss (R)",
        "Largest Win (R)", "Largest Loss (R)", "Avg RR Ratio", "Recovery Factor"
    ])

    # ── ROW 7: KPI VALUES 2 ──
    cells.append([
        f'=SUM({tl("O")})',  # Total R
        f'=SUM({tl("P")})',  # Total P&L
        f'=IFERROR(AVERAGEIF({tl("J")},"Win",{tl("O")}),"")',  # Avg Win R
        f'=IFERROR(AVERAGEIF({tl("J")},"Loss",{tl("O")}),"")',  # Avg Loss R
        f'=IFERROR(MAXIFS({tl("O")},{tl("J")},"Win"),"")',  # Largest Win R
        f'=IFERROR(MINIFS({tl("O")},{tl("J")},"Loss"),"")',  # Largest Loss R
        f'=IFERROR(AVERAGE({tl("N")}),"")',  # Avg RR
        f'=IF(MAX({tl("AO")})=0,"",SUM({tl("P")})/MAX({tl("AO")}))',  # Recovery Factor
    ])

    cells.append([""])

    # ── ROW 9: DRAWDOWN LABELS ──
    cells.append([
        "Max Drawdown ($)", "Current DD ($)", "Max Consecutive Wins",
        "Max Consecutive Losses", "Current Streak", "", "", ""
    ])

    # ── ROW 10: DRAWDOWN VALUES ──
    cells.append([
        f'=IF(COUNTA({tl("AO")})=0,"",MAX({tl("AO")}))',  # Max DD
        f'=IF(COUNTA({tl("AO")})=0,"",INDEX({tl("AO")},COUNTA({tl("AO")})))',  # Current DD
        # Max consecutive wins — uses ARRAYFORMULA trick
        f'=IFERROR(MAX(FREQUENCY(IF({tl("J")}="Win",ROW(INDIRECT("A2:A"&COUNTA({tl("A")})+1))),IF({tl("J")}<>"Win",ROW(INDIRECT("A2:A"&COUNTA({tl("A")})+1))))),"")',
        f'=IFERROR(MAX(FREQUENCY(IF({tl("J")}="Loss",ROW(INDIRECT("A2:A"&COUNTA({tl("A")})+1))),IF({tl("J")}<>"Loss",ROW(INDIRECT("A2:A"&COUNTA({tl("A")})+1))))),"")',
        "",  # Current streak (complex, leave for now)
        "", "", "",
    ])

    cells.append([""])
    cells.append([""])

    # ── ROW 13: MAE/MFE ANALYSIS ──
    cells.append(["═══ MAE / MFE ANALYSIS ═══"])
    cells.append([
        "", "Avg MAE (pips)", "Avg MFE (pips)", "Avg MAE % of SL", "Avg MFE % of TP", "", "", ""
    ])
    cells.append([
        "Winners",
        f'=IFERROR(AVERAGEIF({tl("J")},"Win",{tl("R")}),"")',
        f'=IFERROR(AVERAGEIF({tl("J")},"Win",{tl("S")}),"")',
        f'=IFERROR(AVERAGEIF({tl("J")},"Win",{tl("T")}),"")',
        f'=IFERROR(AVERAGEIF({tl("J")},"Win",{tl("U")}),"")',
        "", "", "",
    ])
    cells.append([
        "Losers",
        f'=IFERROR(AVERAGEIF({tl("J")},"Loss",{tl("R")}),"")',
        f'=IFERROR(AVERAGEIF({tl("J")},"Loss",{tl("S")}),"")',
        f'=IFERROR(AVERAGEIF({tl("J")},"Loss",{tl("T")}),"")',
        f'=IFERROR(AVERAGEIF({tl("J")},"Loss",{tl("U")}),"")',
        "", "", "",
    ])
    cells.append([
        "All Trades",
        f'=IFERROR(AVERAGE({tl("R")}),"")',
        f'=IFERROR(AVERAGE({tl("S")}),"")',
        f'=IFERROR(AVERAGE({tl("T")}),"")',
        f'=IFERROR(AVERAGE({tl("U")}),"")',
        "", "", "",
    ])

    cells.append([""])
    cells.append([""])

    # ── ROW 20: R-MULTIPLE DISTRIBUTION ──
    cells.append(["═══ R-MULTIPLE DISTRIBUTION ═══"])
    cells.append([
        "R Range", "< -2R", "-2R to -1R", "-1R to 0R", "0R to 1R", "1R to 2R", "2R to 3R", "> 3R"
    ])
    cells.append([
        "Count",
        f'=COUNTIFS({tl("O")},"<-2")',
        f'=COUNTIFS({tl("O")},">=-2",{tl("O")},"<-1")',
        f'=COUNTIFS({tl("O")},">=-1",{tl("O")},"<0")',
        f'=COUNTIFS({tl("O")},">=0",{tl("O")},"<1")',
        f'=COUNTIFS({tl("O")},">=1",{tl("O")},"<2")',
        f'=COUNTIFS({tl("O")},">=2",{tl("O")},"<3")',
        f'=COUNTIFS({tl("O")},">=3")',
    ])

    cells.append([""])
    cells.append([""])

    # ── ROW 25: PER-SESSION BREAKDOWN ──
    cells.append(["═══ PERFORMANCE BY SESSION ═══"])
    cells.append([
        "Session", "Trades", "Wins", "Win Rate %", "Avg R", "Total R", "Profit Factor", ""
    ])
    for session in ["Asian", "London", "NY AM", "NY PM", "London-NY Overlap"]:
        cells.append([
            session,
            f'=COUNTIF({tl("D")},"{session}")',
            f'=COUNTIFS({tl("D")},"{session}",{tl("J")},"Win")',
            f'=IF(B{len(cells)+1}=0,"",C{len(cells)+1}/B{len(cells)+1}*100)',
            f'=IFERROR(AVERAGEIF({tl("D")},"{session}",{tl("O")}),"")',
            f'=SUMPRODUCT(({tl("D")}="{session}")*{tl("O")})',
            f'=IFERROR(-SUMPRODUCT(({tl("D")}="{session}")*({tl("J")}="Win")*{tl("P")})/SUMPRODUCT(({tl("D")}="{session}")*({tl("J")}="Loss")*{tl("P")}),"")',
            "",
        ])

    cells.append([""])
    cells.append([""])

    # ── PER-DIRECTION BREAKDOWN ──
    cells.append(["═══ PERFORMANCE BY DIRECTION ═══"])
    cells.append([
        "Direction", "Trades", "Wins", "Win Rate %", "Avg R", "Total R", "Profit Factor", ""
    ])

    base_row = len(cells) + 1
    for direction in ["Long", "Short"]:
        row_idx = len(cells) + 1
        cells.append([
            direction,
            f'=COUNTIF({tl("E")},"{direction}")',
            f'=COUNTIFS({tl("E")},"{direction}",{tl("J")},"Win")',
            f'=IF(B{row_idx}=0,"",C{row_idx}/B{row_idx}*100)',
            f'=IFERROR(AVERAGEIF({tl("E")},"{direction}",{tl("O")}),"")',
            f'=SUMPRODUCT(({tl("E")}="{direction}")*{tl("O")})',
            f'=IFERROR(-SUMPRODUCT(({tl("E")}="{direction}")*({tl("J")}="Win")*{tl("P")})/SUMPRODUCT(({tl("E")}="{direction}")*({tl("J")}="Loss")*{tl("P")}),"")',
            "",
        ])

    cells.append([""])
    cells.append([""])

    # ── PER-PAIR BREAKDOWN (top pairs) ──
    cells.append(["═══ PERFORMANCE BY PAIR ═══"])
    cells.append([
        "Pair", "Trades", "Wins", "Win Rate %", "Avg R", "Total R", "Profit Factor", ""
    ])
    for pair in ["EURUSD", "GBPUSD", "USDJPY", "GBPJPY", "EURJPY", "AUDUSD", "NZDUSD", "USDCHF", "USDCAD", "XAUUSD"]:
        row_idx = len(cells) + 1
        cells.append([
            pair,
            f'=COUNTIF({tl("C")},"{pair}")',
            f'=COUNTIFS({tl("C")},"{pair}",{tl("J")},"Win")',
            f'=IF(B{row_idx}=0,"",C{row_idx}/B{row_idx}*100)',
            f'=IFERROR(AVERAGEIF({tl("C")},"{pair}",{tl("O")}),"")',
            f'=SUMPRODUCT(({tl("C")}="{pair}")*{tl("O")})',
            f'=IFERROR(-SUMPRODUCT(({tl("C")}="{pair}")*({tl("J")}="Win")*{tl("P")})/SUMPRODUCT(({tl("C")}="{pair}")*({tl("J")}="Loss")*{tl("P")}),"")',
            "",
        ])

    cells.append([""])
    cells.append([""])

    # ── PER-SETUP (Execution Model) ──
    cells.append(["═══ PERFORMANCE BY SETUP / EXECUTION MODEL ═══"])
    cells.append([
        "Setup", "Trades", "Wins", "Win Rate %", "Avg R", "Total R", "Profit Factor", ""
    ])
    for setup in ["BOS", "MSS", "CISD", "FVG entry", "OB mitigation", "Liquidity sweep", "Breaker"]:
        row_idx = len(cells) + 1
        cells.append([
            setup,
            f'=COUNTIF({tl("AB")},"{setup}")',
            f'=COUNTIFS({tl("AB")},"{setup}",{tl("J")},"Win")',
            f'=IF(B{row_idx}=0,"",C{row_idx}/B{row_idx}*100)',
            f'=IFERROR(AVERAGEIF({tl("AB")},"{setup}",{tl("O")}),"")',
            f'=SUMPRODUCT(({tl("AB")}="{setup}")*{tl("O")})',
            f'=IFERROR(-SUMPRODUCT(({tl("AB")}="{setup}")*({tl("J")}="Win")*{tl("P")})/SUMPRODUCT(({tl("AB")}="{setup}")*({tl("J")}="Loss")*{tl("P")}),"")',
            "",
        ])

    cells.append([""])
    cells.append([""])

    # ── CONVICTION VS OUTCOME ──
    cells.append(["═══ CONVICTION vs OUTCOME ═══"])
    cells.append([
        "Conviction", "Trades", "Wins", "Win Rate %", "Avg R", "Total R", "", ""
    ])
    for conv in [1, 2, 3, 4, 5]:
        row_idx = len(cells) + 1
        cells.append([
            f"Conviction {conv}",
            f'=COUNTIF({tl("AF")},{conv})',
            f'=COUNTIFS({tl("AF")},{conv},{tl("J")},"Win")',
            f'=IF(B{row_idx}=0,"",C{row_idx}/B{row_idx}*100)',
            f'=IFERROR(AVERAGEIF({tl("AF")},{conv},{tl("O")}),"")',
            f'=SUMPRODUCT(({tl("AF")}={conv})*{tl("O")})',
            "", "",
        ])

    cells.append([""])
    cells.append([""])

    # ── MONTHLY P&L ──
    cells.append(["═══ MONTHLY P&L ═══"])
    cells.append([
        "Month", "Trades", "Wins", "Win Rate %", "Total R", "Total P&L ($)", "Avg R", ""
    ])
    months = [
        ("Jan", "01"), ("Feb", "02"), ("Mar", "03"), ("Apr", "04"),
        ("May", "05"), ("Jun", "06"), ("Jul", "07"), ("Aug", "08"),
        ("Sep", "09"), ("Oct", "10"), ("Nov", "11"), ("Dec", "12"),
    ]
    for month_name, month_num in months:
        row_idx = len(cells) + 1
        cells.append([
            month_name,
            f'=SUMPRODUCT((MONTH({tl("B")})={month_num})*1)',
            f'=SUMPRODUCT((MONTH({tl("B")})={month_num})*({tl("J")}="Win"))',
            f'=IF(B{row_idx}=0,"",C{row_idx}/B{row_idx}*100)',
            f'=SUMPRODUCT((MONTH({tl("B")})={month_num})*{tl("O")})',
            f'=SUMPRODUCT((MONTH({tl("B")})={month_num})*{tl("P")})',
            f'=IF(B{row_idx}=0,"",E{row_idx}/B{row_idx})',
            "",
        ])

    return cells


# ═══════════════════════════════════════════════
# FILTERED TAB — Same metrics with filter controls
# ═══════════════════════════════════════════════

def build_filtered_cells() -> list[list]:
    """
    Build the Filtered tab with dropdown filters and filtered metrics.
    Uses COUNTIFS/AVERAGEIFS/SUMPRODUCT with filter criteria.
    """
    TL = "TradeLog"

    def tl(col, start=2, end=500):
        return f"'{TL}'!{col}{start}:{col}{end}"

    cells = []

    # ── ROW 1-2: FILTER CONTROLS ──
    cells.append([
        "═══ FILTER CONTROLS ═══", "", "", "", "", "", "", ""
    ])
    cells.append([
        "Pair ▼", "Direction ▼", "Session ▼", "Setup ▼", "Outcome ▼", "Conviction ▼", "", ""
    ])
    # Row 3: Filter values (user selects via dropdowns)
    cells.append([
        "ALL",  # A3: Pair filter
        "ALL",  # B3: Direction filter
        "ALL",  # C3: Session filter
        "ALL",  # D3: Setup filter
        "ALL",  # E3: Outcome filter
        "ALL",  # F3: Conviction filter
        "", "",
    ])

    cells.append([""])

    # ── Helper function to build filtered count formula ──
    # This creates a COUNTIFS that checks each filter
    # If filter = "ALL", it matches everything; otherwise it matches the specific value
    def filtered_count(extra_criteria=""):
        parts = []
        # Pair filter
        parts.append(f'IF($A$3="ALL",1,({tl("C")}=$A$3)*1)')
        # Direction filter
        parts.append(f'IF($B$3="ALL",1,({tl("E")}=$B$3)*1)')
        # Session filter
        parts.append(f'IF($C$3="ALL",1,({tl("D")}=$C$3)*1)')
        # Setup filter
        parts.append(f'IF($D$3="ALL",1,({tl("AB")}=$D$3)*1)')
        # Outcome filter
        parts.append(f'IF($E$3="ALL",1,({tl("J")}=$E$3)*1)')
        # Conviction filter
        parts.append(f'IF($F$3="ALL",1,({tl("AF")}=$F$3)*1)')

        base = "*".join([f'({p})' for p in parts])
        if extra_criteria:
            base += f"*({extra_criteria})"
        return f'=SUMPRODUCT({base})'

    def filtered_sum(col, extra_criteria=""):
        parts = []
        parts.append(f'IF($A$3="ALL",1,({tl("C")}=$A$3)*1)')
        parts.append(f'IF($B$3="ALL",1,({tl("E")}=$B$3)*1)')
        parts.append(f'IF($C$3="ALL",1,({tl("D")}=$C$3)*1)')
        parts.append(f'IF($D$3="ALL",1,({tl("AB")}=$D$3)*1)')
        parts.append(f'IF($E$3="ALL",1,({tl("J")}=$E$3)*1)')
        parts.append(f'IF($F$3="ALL",1,({tl("AF")}=$F$3)*1)')

        base = "*".join([f'({p})' for p in parts])
        if extra_criteria:
            base += f"*({extra_criteria})"
        return f'=SUMPRODUCT({base}*{tl(col)})'

    # ── ROW 5: FILTERED KPI LABELS ──
    cells.append([
        "═══ FILTERED PERFORMANCE ═══", "", "", "", "", "", "", ""
    ])
    cells.append([
        "Filtered Trades", "Filtered Wins", "Filtered Losses",
        "Win Rate %", "Profit Factor", "Expectancy (R)", "Total R", "Total P&L ($)"
    ])

    # ROW 7: Filtered KPI values
    total_formula = filtered_count()
    wins_formula = filtered_count(f'{tl("J")}="Win"')
    losses_formula = filtered_count(f'{tl("J")}="Loss"')

    cells.append([
        total_formula,
        wins_formula,
        losses_formula,
        f'=IF(A7=0,"",B7/A7*100)',
        # Profit Factor (filtered)
        f'=IFERROR(-{filtered_sum("P", f"{tl(chr(74))}=" + chr(34) + "Win" + chr(34))}/{filtered_sum("P", f"{tl(chr(74))}=" + chr(34) + "Loss" + chr(34))},"")',
        # Expectancy R (filtered)
        f'=IF(A7=0,"",G7/A7)',
        # Total R (filtered)
        filtered_sum("O"),
        # Total P&L (filtered)
        filtered_sum("P"),
    ])

    cells.append([""])

    # ── ROW 9: MORE FILTERED METRICS ──
    cells.append([
        "Avg Win (R)", "Avg Loss (R)", "Largest Win (R)", "Largest Loss (R)",
        "Avg RR", "Max Drawdown ($)", "", ""
    ])

    # These use complex SUMPRODUCT for conditional averages
    cells.append([
        f'=IF(B7=0,"",{filtered_sum("O", f"{tl(chr(74))}=" + chr(34) + "Win" + chr(34))}/B7)',
        f'=IF(C7=0,"",{filtered_sum("O", f"{tl(chr(74))}=" + chr(34) + "Loss" + chr(34))}/C7)',
        "",  # Largest win (hard with SUMPRODUCT, skip)
        "",  # Largest loss
        f'=IF(A7=0,"",{filtered_sum("N")}/A7)',
        "",
        "", "",
    ])

    cells.append([""])
    cells.append([""])

    # ── FILTERED MAE/MFE ──
    cells.append(["═══ FILTERED MAE / MFE ═══"])
    cells.append([
        "", "Avg MAE (pips)", "Avg MFE (pips)", "Avg MAE % of SL", "Avg MFE % of TP", "", "", ""
    ])
    cells.append([
        "Winners",
        f'=IF(B7=0,"",{filtered_sum("R", f"{tl(chr(74))}=" + chr(34) + "Win" + chr(34))}/B7)',
        f'=IF(B7=0,"",{filtered_sum("S", f"{tl(chr(74))}=" + chr(34) + "Win" + chr(34))}/B7)',
        f'=IF(B7=0,"",{filtered_sum("T", f"{tl(chr(74))}=" + chr(34) + "Win" + chr(34))}/B7)',
        f'=IF(B7=0,"",{filtered_sum("U", f"{tl(chr(74))}=" + chr(34) + "Win" + chr(34))}/B7)',
        "", "", "",
    ])
    cells.append([
        "Losers",
        f'=IF(C7=0,"",{filtered_sum("R", f"{tl(chr(74))}=" + chr(34) + "Loss" + chr(34))}/C7)',
        f'=IF(C7=0,"",{filtered_sum("S", f"{tl(chr(74))}=" + chr(34) + "Loss" + chr(34))}/C7)',
        f'=IF(C7=0,"",{filtered_sum("T", f"{tl(chr(74))}=" + chr(34) + "Loss" + chr(34))}/C7)',
        f'=IF(C7=0,"",{filtered_sum("U", f"{tl(chr(74))}=" + chr(34) + "Loss" + chr(34))}/C7)',
        "", "", "",
    ])
    cells.append([
        "All Filtered",
        f'=IF(A7=0,"",{filtered_sum("R")}/A7)',
        f'=IF(A7=0,"",{filtered_sum("S")}/A7)',
        f'=IF(A7=0,"",{filtered_sum("T")}/A7)',
        f'=IF(A7=0,"",{filtered_sum("U")}/A7)',
        "", "", "",
    ])

    cells.append([""])
    cells.append([""])

    # ── FILTERED R-DISTRIBUTION ──
    cells.append(["═══ FILTERED R-MULTIPLE DISTRIBUTION ═══"])
    cells.append([
        "R Range", "< -2R", "-2R to -1R", "-1R to 0R", "0R to 1R", "1R to 2R", "2R to 3R", "> 3R"
    ])
    cells.append([
        "Count",
        filtered_count(f'{tl("O")}<-2'),
        filtered_count(f'({tl("O")}>=-2)*({tl("O")}<-1)'),
        filtered_count(f'({tl("O")}>=-1)*({tl("O")}<0)'),
        filtered_count(f'({tl("O")}>=0)*({tl("O")}<1)'),
        filtered_count(f'({tl("O")}>=1)*({tl("O")}<2)'),
        filtered_count(f'({tl("O")}>=2)*({tl("O")}<3)'),
        filtered_count(f'{tl("O")}>=3'),
    ])

    return cells


# ═══════════════════════════════════════════════
# MAIN SETUP FUNCTION
# ═══════════════════════════════════════════════

def setup_spreadsheet():
    """Create/update all 3 tabs in the Google Sheet."""

    logger.info(f"Connecting to Google Sheet: {GOOGLE_SHEET_ID}")
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)

    logger.info(f"Connected to: {spreadsheet.title}")
    existing_tabs = [ws.title for ws in spreadsheet.worksheets()]
    logger.info(f"Existing tabs: {existing_tabs}")

    # ── 1. CREATE/UPDATE TRADELOG TAB ──
    logger.info("Setting up TradeLog tab...")
    if "TradeLog" in existing_tabs:
        tradelog_ws = spreadsheet.worksheet("TradeLog")
        logger.info("TradeLog tab exists. Updating headers only.")
    else:
        tradelog_ws = spreadsheet.add_worksheet(title="TradeLog", rows=1000, cols=50)
        logger.info("Created TradeLog tab.")

    # Set headers
    tradelog_ws.update(range_name="A1", values=[TRADELOG_HEADERS])

    # Set formulas for first 200 data rows
    logger.info("Adding auto-calc formulas to TradeLog (rows 2-200)...")
    formula_batch = []
    for row in range(2, 201):
        formulas = get_tradelog_row_formulas(row)
        for col_letter, formula in formulas.items():
            col_idx = gspread.utils.column_letter_to_index(col_letter)
            formula_batch.append({
                "range": f"{col_letter}{row}",
                "values": [[formula]],
            })

    # Batch update formulas in chunks to avoid API limits
    CHUNK_SIZE = 100
    for i in range(0, len(formula_batch), CHUNK_SIZE):
        chunk = formula_batch[i:i + CHUNK_SIZE]
        tradelog_ws.batch_update(chunk, value_input_option="USER_ENTERED")
        logger.info(f"  Formula batch {i // CHUNK_SIZE + 1} written.")

    # ── 2. CREATE/UPDATE ANALYTICS TAB ──
    logger.info("Setting up Analytics tab...")
    if "Analytics" in existing_tabs:
        spreadsheet.del_worksheet(spreadsheet.worksheet("Analytics"))
    analytics_ws = spreadsheet.add_worksheet(title="Analytics", rows=200, cols=10)

    analytics_cells = build_analytics_cells()
    analytics_ws.update(
        range_name="A1",
        values=analytics_cells,
        value_input_option="USER_ENTERED",
    )
    logger.info(f"Analytics tab populated with {len(analytics_cells)} rows.")

    # ── 3. CREATE/UPDATE FILTERED TAB ──
    logger.info("Setting up Filtered tab...")
    if "Filtered" in existing_tabs:
        spreadsheet.del_worksheet(spreadsheet.worksheet("Filtered"))
    filtered_ws = spreadsheet.add_worksheet(title="Filtered", rows=100, cols=10)

    filtered_cells = build_filtered_cells()
    filtered_ws.update(
        range_name="A1",
        values=filtered_cells,
        value_input_option="USER_ENTERED",
    )
    logger.info(f"Filtered tab populated with {len(filtered_cells)} rows.")

    # ── 4. ADD DATA VALIDATION DROPDOWNS TO FILTERED TAB ──
    logger.info("Adding filter dropdowns to Filtered tab...")

    from gspread.utils import ValueInputOption

    try:
        # Set data validation for filter cells using the Sheets API directly
        sheets_service = spreadsheet.client.http_client
        requests_list = []

        # Get the Filtered sheet ID
        filtered_sheet_id = filtered_ws.id

        # Pair filter dropdown (A3)
        pair_values = ["ALL", "EURUSD", "GBPUSD", "USDJPY", "GBPJPY", "EURJPY", "AUDUSD", "NZDUSD", "USDCHF", "USDCAD", "XAUUSD"]
        # Direction filter dropdown (B3)
        direction_values = ["ALL", "Long", "Short"]
        # Session filter dropdown (C3)
        session_values = ["ALL", "Asian", "London", "NY AM", "NY PM", "London-NY Overlap"]
        # Setup filter dropdown (D3)
        setup_values = ["ALL", "BOS", "MSS", "CISD", "FVG entry", "OB mitigation", "Liquidity sweep", "Breaker"]
        # Outcome filter dropdown (E3)
        outcome_values = ["ALL", "Win", "Loss", "Breakeven", "Partial"]
        # Conviction filter dropdown (F3)
        conviction_values = ["ALL", "1", "2", "3", "4", "5"]

        dropdowns = [
            (0, pair_values),       # A3 (col 0)
            (1, direction_values),  # B3 (col 1)
            (2, session_values),    # C3 (col 2)
            (3, setup_values),      # D3 (col 3)
            (4, outcome_values),    # E3 (col 4)
            (5, conviction_values), # F3 (col 5)
        ]

        for col_idx, values in dropdowns:
            requests_list.append({
                "setDataValidation": {
                    "range": {
                        "sheetId": filtered_sheet_id,
                        "startRowIndex": 2,  # Row 3 (0-indexed)
                        "endRowIndex": 3,
                        "startColumnIndex": col_idx,
                        "endColumnIndex": col_idx + 1,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [{"userEnteredValue": v} for v in values],
                        },
                        "showCustomUi": True,
                        "strict": True,
                    },
                }
            })

        # Execute batch update via raw API
        if requests_list:
            spreadsheet.batch_update({"requests": requests_list})
            logger.info(f"  Added {len(requests_list)} dropdown filters.")

    except Exception as e:
        logger.warning(f"Could not add dropdowns (non-critical): {e}")
        logger.info("Dropdowns can be added manually via Data > Data Validation.")

    # ── 5. BASIC FORMATTING ──
    logger.info("Applying formatting...")
    try:
        # Bold headers on TradeLog
        tradelog_ws.format("A1:AO1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.15, "green": 0.15, "blue": 0.15},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        })

        # Bold section headers on Analytics
        analytics_ws.format("A1:H1", {
            "textFormat": {"bold": True, "fontSize": 14},
        })
        analytics_ws.format("A3:H3", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.95},
        })
        analytics_ws.format("A6:H6", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.95},
        })
        analytics_ws.format("A9:H9", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.95},
        })

        # Bold filter labels on Filtered
        filtered_ws.format("A1:H1", {
            "textFormat": {"bold": True, "fontSize": 14},
        })
        filtered_ws.format("A2:F2", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0},
        })
        filtered_ws.format("A3:F3", {
            "backgroundColor": {"red": 1.0, "green": 0.98, "blue": 0.8},
            "textFormat": {"bold": True},
        })

        logger.info("Formatting applied.")
    except Exception as e:
        logger.warning(f"Formatting partially failed (non-critical): {e}")

    # ── DONE ──
    logger.info("")
    logger.info("═══ SETUP COMPLETE ═══")
    logger.info(f"  TradeLog:  {len(TRADELOG_HEADERS)} columns, 200 rows of auto-calc formulas")
    logger.info(f"  Analytics: {len(analytics_cells)} rows of performance metrics")
    logger.info(f"  Filtered:  {len(filtered_cells)} rows with 6 filter dropdowns")
    logger.info(f"  Sheet URL: https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit")


if __name__ == "__main__":
    setup_spreadsheet()
