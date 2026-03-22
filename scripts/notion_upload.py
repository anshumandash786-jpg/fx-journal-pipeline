"""
notion_upload.py — Notion integration for the backtesting pipeline.

Creates rich trade journal pages in a Notion database with:
- Trade properties (Pair, Date, R Multiple, Select status)
- Page body with narrative sections (Direction, Location, Entry, Comment)
- Embedded screenshots from Google Drive

Requires:
    - A Notion Internal Integration (API key starting with ntn_)
    - The integration connected to the target database
    - NOTION_API_KEY and NOTION_DATABASE_ID in .env

Usage:
    Called programmatically by process_video.py (Step 6)
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import NOTION_API_KEY, NOTION_DATABASE_ID, NOTION_ENABLED

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("notion_upload")


def _get_notion_client():
    """Create and return a Notion API client."""
    try:
        from notion_client import Client
    except ImportError:
        raise ImportError(
            "notion-client not installed. Install with:\n"
            "  pip install notion-client"
        )

    if not NOTION_API_KEY:
        raise ValueError(
            "NOTION_API_KEY not set. Add it to your .env file:\n"
            "  NOTION_API_KEY=ntn_your-key-here\n\n"
            "Get one at: https://www.notion.so/profile/integrations"
        )

    return Client(auth=NOTION_API_KEY)


def _build_page_properties(trade: dict, trade_id: str) -> dict:
    """
    Build Notion database page properties from trade data.

    Exact property names matched to the user's '2 0 2 6' database:
      - Trade (title)       — e.g., "W2-T1" or trade_id
      - Date (date)         — trade date
      - Pair (select)       — currency pair
      - Profit/Loss         — FORMULA, skip (Notion computes it)
      - R Mulitple (number) — R-multiple value (note: user's typo preserved)
      - Select (select)     — trade status: Taken / Missed / Invalid Trade
    """
    properties = {}

    # Title property — "Trade" column
    properties["Trade"] = {
        "title": [{"text": {"content": trade_id}}]
    }

    # Date
    if trade.get("date"):
        properties["Date"] = {
            "date": {"start": trade["date"]}
        }

    # Pair (Select)
    if trade.get("pair"):
        properties["Pair"] = {
            "select": {"name": trade["pair"].upper().replace("/", "")}
        }

    # R Mulitple (Number) — note: uses the user's exact spelling "Mulitple"
    r_multiple = trade.get("r_multiple") or trade.get("max_r_available")
    if r_multiple is not None:
        try:
            properties["R Mulitple"] = {
                "number": float(r_multiple)
            }
        except (ValueError, TypeError):
            pass

    # Select (trade status) — default to "Taken" for automated entries
    properties["Select"] = {
        "select": {"name": "Taken"}
    }

    return properties


def _build_page_body(trade: dict, screenshot_links: dict) -> list:
    """
    Build Notion block children (page body content).

    Matches the user's 'T R A D E S' template structure:
      - Direction:   (H3 heading + paragraph + screenshot)
      - Location:    (H3 heading + paragraph + screenshot)
      - Entry:       (H3 heading + paragraph + screenshot)
      - Comment:     (quote block with post-trade review/mistakes)
    """
    blocks = []

    # ── Direction Section ───────────────────────────
    blocks.append({
        "type": "heading_3",
        "heading_3": {
            "rich_text": [{"type": "text", "text": {"content": "Direction:"}}]
        }
    })

    direction_thesis = trade.get("direction_thesis", "")
    direction_text = trade.get("direction", "")
    htf_ref = trade.get("htf_reference", "")

    # Build direction content
    dir_content_parts = []
    if direction_text:
        dir_content_parts.append(direction_text)
    if htf_ref:
        dir_content_parts.append(f"HTF: {htf_ref}")
    if direction_thesis:
        dir_content_parts.append(direction_thesis)

    dir_content = " — ".join(dir_content_parts) if dir_content_parts else ""
    if dir_content:
        blocks.append({
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": dir_content}}]
            }
        })

    # Direction screenshot
    dir_link = screenshot_links.get("direction", "")
    if dir_link and dir_link.startswith("http"):
        blocks.append({
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": dir_link}
            }
        })

    # Spacer
    blocks.append({"type": "paragraph", "paragraph": {"rich_text": []}})

    # ── Location Section ────────────────────────────
    blocks.append({
        "type": "heading_3",
        "heading_3": {
            "rich_text": [{"type": "text", "text": {"content": "Location:"}}]
        }
    })

    location_thesis = trade.get("location_thesis", "")
    zone_type = trade.get("location_zone_type", "")
    location_tf = trade.get("location_timeframe", "")

    loc_content_parts = []
    if zone_type:
        loc_content_parts.append(f"Zone: {zone_type}")
    if location_tf:
        loc_content_parts.append(f"TF: {location_tf}")
    if location_thesis:
        loc_content_parts.append(location_thesis)

    loc_content = " — ".join(loc_content_parts) if loc_content_parts else ""
    if loc_content:
        blocks.append({
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": loc_content}}]
            }
        })

    # Location screenshot
    loc_link = screenshot_links.get("location", "")
    if loc_link and loc_link.startswith("http"):
        blocks.append({
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": loc_link}
            }
        })

    # Spacer
    blocks.append({"type": "paragraph", "paragraph": {"rich_text": []}})

    # ── Entry Section ───────────────────────────────
    blocks.append({
        "type": "heading_3",
        "heading_3": {
            "rich_text": [{"type": "text", "text": {"content": "Entry:"}}]
        }
    })

    execution_thesis = trade.get("execution_thesis", "")
    exec_model = trade.get("execution_model_name", "")
    exec_tf = trade.get("execution_timeframe", "")

    entry_content_parts = []
    if exec_model:
        entry_content_parts.append(f"Model: {exec_model}")
    if exec_tf:
        entry_content_parts.append(f"TF: {exec_tf}")
    if execution_thesis:
        entry_content_parts.append(execution_thesis)

    entry_content = " — ".join(entry_content_parts) if entry_content_parts else ""
    if entry_content:
        blocks.append({
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": entry_content}}]
            }
        })

    # Execution screenshot
    exec_link = screenshot_links.get("execution", "")
    if exec_link and exec_link.startswith("http"):
        blocks.append({
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": exec_link}
            }
        })

    # Spacer
    blocks.append({"type": "paragraph", "paragraph": {"rich_text": []}})

    # ── Comment Section (Quote Block) ───────────────
    # Combine confluence, mistakes, and post-trade review into the comment
    comment_parts = []

    # Confluence
    pos_conf = trade.get("positive_confluence_list", "")
    neg_conf = trade.get("negative_confluence_list", "")
    if pos_conf:
        comment_parts.append(f"✅ Positive: {pos_conf}")
    if neg_conf:
        comment_parts.append(f"❌ Negative: {neg_conf}")

    # Mistakes
    mistakes = trade.get("mistakes_noted", "")
    if mistakes:
        comment_parts.append(f"⚠️ Mistakes: {mistakes}")

    # Post-trade review
    review = trade.get("post_trade_review", "")
    if review:
        comment_parts.append(f"📝 Review: {review}")

    # Outcome summary
    outcome = trade.get("outcome", "")
    if outcome:
        comment_parts.append(f"Result: {outcome}")

    comment_text = "\n".join(comment_parts) if comment_parts else "No comments."

    blocks.append({
        "type": "quote",
        "quote": {
            "rich_text": [{"type": "text", "text": {"content": f"Comment:\n{comment_text}"}}]
        }
    })

    return blocks


def create_notion_trade_page(
    trade: dict,
    screenshot_links: dict,
    trade_id: str,
) -> str | None:
    """
    Create a single trade journal page in the Notion database.

    Args:
        trade: Trade dict from parse_trade.py
        screenshot_links: Dict of {type: URL} from upload.py
        trade_id: Trade ID string (e.g., 'EURUSD-2026-014')

    Returns:
        The Notion page ID if successful, None if failed.
    """
    if not NOTION_ENABLED:
        logger.warning("Notion not configured. Skipping.")
        return None

    client = _get_notion_client()

    properties = _build_page_properties(trade, trade_id)
    children = _build_page_body(trade, screenshot_links)

    try:
        response = client.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties=properties,
            children=children,
        )
        page_id = response["id"]
        logger.info(f"Created Notion page for {trade_id} (ID: {page_id})")
        return page_id
    except Exception as e:
        logger.error(f"Failed to create Notion page for {trade_id}: {e}")
        return None


def append_trades_to_notion(
    trades: list[dict],
    all_screenshot_links: list[dict],
    trade_ids: list[str],
) -> int:
    """
    Create Notion pages for one or more trades.

    Args:
        trades: List of trade dicts from parse_trade.py
        all_screenshot_links: List of screenshot link dicts (one per trade)
        trade_ids: List of trade ID strings

    Returns:
        Number of pages successfully created.
    """
    if not NOTION_ENABLED:
        logger.info("Notion integration disabled (no API key / database ID).")
        return 0

    pages_created = 0
    for i, trade in enumerate(trades):
        screenshot_links = all_screenshot_links[i] if i < len(all_screenshot_links) else {}
        trade_id = trade_ids[i] if i < len(trade_ids) else f"TRADE-{i+1}"

        page_id = create_notion_trade_page(trade, screenshot_links, trade_id)
        if page_id:
            pages_created += 1

    logger.info(f"Notion: {pages_created}/{len(trades)} pages created.")
    return pages_created


# ─────────────────────────────────────────────
# Daily Markups Integration
# ─────────────────────────────────────────────

def create_daily_markup_page(date_str: str, week_num: int, day_name: str, markup_data: dict, screenshot_links: list[str]) -> bool:
    """
    Create a new daily markup page in the dedicated Automated Daily Markups database.
    This provides a 100% hands-free experience (no manual toggle creation needed).
    """
    from config.settings import NOTION_DAILY_MARKUPS_DATABASE_ID
    if not NOTION_ENABLED or not NOTION_DAILY_MARKUPS_DATABASE_ID:
        logger.warning("Notion Daily Markups Database ID not configured.")
        return False

    client = _get_notion_client()
    
    # 1. Build Properties
    properties = {
        "Date": {
            "title": [{"text": {"content": date_str}}]
        },
        "Week": {
            "select": {"name": f"W{week_num}"}
        },
        "Day": {
            "select": {"name": day_name}
        }
    }
    
    # 2. Build Page Body
    blocks = []
    
    # ── Pre-Market ──
    blocks.append({
        "type": "heading_3",
        "heading_3": {"rich_text": [{"type": "text", "text": {"content": "PRE MARKET:"}}]}
    })
    
    for pt in markup_data.get("pre_market", []):
        blocks.append({
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": pt}}]}
        })
        
    blocks.append({"type": "paragraph", "paragraph": {"rich_text": []}})
    
    # ── Session Recording ──
    blocks.append({
        "type": "heading_3",
        "heading_3": {"rich_text": [{"type": "text", "text": {"content": "Session Recording:"}}]}
    })
    
    events = markup_data.get("session_events", [])
    for i, event in enumerate(events):
        ts = event.get("timestamp", "")
        desc = event.get("description", "")
        text = f"[{ts}] {desc}" if ts else desc
        blocks.append({
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        })
        
        # Insert corresponding screenshot if available
        if i < len(screenshot_links) and screenshot_links[i]:
            blocks.append({
                "type": "image",
                "image": {"type": "external", "external": {"url": screenshot_links[i]}}
            })
            
    blocks.append({"type": "paragraph", "paragraph": {"rich_text": []}})
    
    # ── Post-Market ──
    blocks.append({
        "type": "heading_3",
        "heading_3": {"rich_text": [{"type": "text", "text": {"content": "POST MARKET:"}}]}
    })
    
    for pt in markup_data.get("post_market", []):
        blocks.append({
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": pt}}]}
        })

    # 3. Create Page
    try:
        response = client.pages.create(
            parent={"database_id": NOTION_DAILY_MARKUPS_DATABASE_ID},
            properties=properties,
            children=blocks,
        )
        logger.info(f"Successfully created daily markup page for {date_str} (ID: {response['id']})")
        return True
    except Exception as e:
        logger.error(f"Failed to create daily markup page: {e}")
        return False


def test_notion_connection() -> bool:
    """
    Quick connection test — query the database to verify credentials.
    """
    if not NOTION_ENABLED:
        print("❌ Notion not configured. Set NOTION_API_KEY and NOTION_DATABASE_ID in .env")
        return False

    try:
        client = _get_notion_client()
        db = client.databases.retrieve(database_id=NOTION_DATABASE_ID)
        title = "".join(
            t.get("plain_text", "") for t in db.get("title", [])
        )
        print(f"✅ Notion Connection: SUCCESS")
        print(f"   Database: {title or '(untitled)'}")
        print(f"   Properties: {', '.join(db.get('properties', {}).keys())}")
        return True
    except Exception as e:
        print(f"❌ Notion Connection: FAILED — {e}")
        return False


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    test_notion_connection()
