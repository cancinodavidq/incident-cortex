from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import json
import sqlite3
import os

app = FastAPI(title="Slack Mock")

DB_PATH = os.environ.get("SLACK_DB_PATH", "/data/slack.db")

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL DEFAULT '#incidents',
            username TEXT NOT NULL DEFAULT 'bot',
            text TEXT NOT NULL,
            blocks TEXT,
            attachments TEXT,
            source TEXT NOT NULL DEFAULT 'api',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def render_blocks(blocks_raw) -> str:
    """Render Slack block kit JSON to HTML."""
    if not blocks_raw:
        return ""
    try:
        blocks = json.loads(blocks_raw) if isinstance(blocks_raw, str) else blocks_raw
    except Exception:
        return ""

    html = ""
    for block in blocks:
        btype = block.get("type", "")
        if btype == "header":
            text = block.get("text", {}).get("text", "")
            html += f'<div style="font-size:15px;font-weight:700;color:#e4e6f0;margin-bottom:6px">{text}</div>'
        elif btype == "section":
            text_obj = block.get("text", {})
            text = text_obj.get("text", "") if isinstance(text_obj, dict) else ""
            # Render markdown-ish: *bold*, `code`
            text = text.replace("*", "<b>", 1).replace("*", "</b>", 1) if text.count("*") >= 2 else text
            html += f'<div style="font-size:13px;color:#c9cce0;margin-bottom:4px;white-space:pre-wrap">{text}</div>'
            # Fields
            for field in block.get("fields", []):
                ft = field.get("text", "")
                html += f'<div style="font-size:12px;color:#8b90a8;margin-bottom:2px">{ft}</div>'
        elif btype == "divider":
            html += '<hr style="border:none;border-top:1px solid #252836;margin:8px 0">'
        elif btype == "context":
            for el in block.get("elements", []):
                t = el.get("text", "")
                html += f'<div style="font-size:11px;color:#555a72">{t}</div>'
        elif btype == "actions":
            for el in block.get("elements", []):
                label = el.get("text", {}).get("text", "Action") if isinstance(el.get("text"), dict) else el.get("text", "Action")
                html += f'<span style="display:inline-block;padding:4px 10px;background:rgba(91,106,240,.15);border:1px solid rgba(91,106,240,.3);border-radius:5px;font-size:12px;color:#a5b4fc;margin-right:6px">{label}</span>'
    return html


def msg_to_dict(row) -> dict:
    d = dict(row)
    d["blocks"] = json.loads(d["blocks"]) if d.get("blocks") else None
    d["attachments"] = json.loads(d["attachments"]) if d.get("attachments") else None
    return d


class WebhookPayload(BaseModel):
    text: Optional[str] = ""
    channel: Optional[str] = "#incidents"
    username: Optional[str] = "Incident Cortex"
    blocks: Optional[list] = None
    attachments: Optional[list] = None


class PostMessageRequest(BaseModel):
    channel: str
    text: Optional[str] = ""
    username: Optional[str] = "bot"
    blocks: Optional[list] = None
    attachments: Optional[list] = None


@app.post("/webhook")
async def receive_webhook(data: WebhookPayload):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (channel, username, text, blocks, attachments, source, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                data.channel or "#incidents",
                data.username or "Incident Cortex",
                data.text or "",
                json.dumps(data.blocks) if data.blocks else None,
                json.dumps(data.attachments) if data.attachments else None,
                "webhook",
                datetime.utcnow().isoformat()
            )
        )
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    return {"status": "ok", "message_count": count}


@app.post("/api/chat.postMessage")
async def post_message(data: PostMessageRequest):
    ts = datetime.utcnow().timestamp()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (channel, username, text, blocks, attachments, source, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                data.channel,
                data.username or "bot",
                data.text or "",
                json.dumps(data.blocks) if data.blocks else None,
                json.dumps(data.attachments) if data.attachments else None,
                "api",
                datetime.utcfromtimestamp(ts).isoformat()
            )
        )
    return {
        "ok": True,
        "channel": data.channel,
        "ts": str(ts),
        "message": {"text": data.text, "username": data.username}
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 200").fetchall()

    messages = [msg_to_dict(r) for r in rows]

    cards_html = ""
    if not messages:
        cards_html = '<div style="text-align:center;padding:56px 0;color:#555a72;font-size:14px">No messages yet</div>'
    else:
        for msg in messages:
            ts_raw = msg.get("created_at", "")
            try:
                dt = datetime.fromisoformat(ts_raw)
                ts_str = dt.strftime("%b %d, %H:%M:%S")
            except Exception:
                ts_str = ts_raw

            channel = msg.get("channel", "#incidents")
            username = msg.get("username", "bot")
            text = msg.get("text", "")
            blocks_html = render_blocks(msg.get("blocks"))
            source_badge = msg.get("source", "api")

            content_html = blocks_html if blocks_html else f'<div style="font-size:13px;color:#c9cce0;white-space:pre-wrap">{text}</div>'

            cards_html += f"""
            <div style="border-bottom:1px solid #1a1d27;padding:16px 20px">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
                <div style="width:28px;height:28px;border-radius:6px;background:rgba(91,106,240,.2);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#a5b4fc">{username[0].upper()}</div>
                <div>
                  <span style="font-size:13px;font-weight:600;color:#e4e6f0">{username}</span>
                  <span style="font-size:12px;color:#555a72;margin-left:6px">{channel}</span>
                </div>
                <div style="margin-left:auto;display:flex;align-items:center;gap:8px">
                  <span style="font-size:11px;padding:2px 7px;border-radius:4px;background:rgba(91,106,240,.1);color:#8b90a8">{source_badge}</span>
                  <span style="font-size:11px;color:#555a72;font-family:monospace">{ts_str}</span>
                </div>
              </div>
              <div style="padding-left:36px">{content_html}</div>
            </div>
            """

    total = len(messages)
    channels = list(set(m.get("channel", "#incidents") for m in messages))

    return HTMLResponse(f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Slack Mock</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:#0d0f14;color:#e4e6f0;font-family:'Inter',sans-serif;height:100vh;display:flex;flex-direction:column}}
    ::-webkit-scrollbar{{width:6px}} ::-webkit-scrollbar-track{{background:#13161e}} ::-webkit-scrollbar-thumb{{background:#252836;border-radius:3px}}
  </style>
</head>
<body>
  <!-- Header -->
  <div style="height:56px;border-bottom:1px solid #252836;background:#13161e;display:flex;align-items:center;padding:0 24px;flex-shrink:0;gap:12px">
    <div style="width:28px;height:28px;background:#5b6af0;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:15px">💬</div>
    <div>
      <div style="font-weight:700;font-size:15px;letter-spacing:-0.02em">Slack Mock</div>
      <div style="font-size:11px;color:#555a72">Incident Cortex notifications</div>
    </div>
    <div style="margin-left:auto;display:flex;gap:16px;align-items:center">
      <span style="font-size:12px;color:#8b90a8">{total} messages</span>
      <button onclick="location.reload()" style="padding:6px 12px;background:#1a1d27;border:1px solid #252836;border-radius:6px;color:#8b90a8;font-size:12px;font-weight:500;cursor:pointer">↻ Refresh</button>
    </div>
  </div>

  <!-- Body -->
  <div style="display:flex;flex:1;overflow:hidden">
    <!-- Sidebar -->
    <div style="width:220px;border-right:1px solid #252836;background:#13161e;padding:16px 0;flex-shrink:0;overflow-y:auto">
      <div style="padding:0 16px;margin-bottom:12px;font-size:11px;font-weight:600;color:#555a72;text-transform:uppercase;letter-spacing:0.07em">Channels</div>
      {"".join(f'<div style="padding:7px 16px;font-size:13px;color:#8b90a8;background:{"rgba(91,106,240,.12)" if i==0 else "none"};color:{"#e4e6f0" if i==0 else "#8b90a8"}"># {ch.lstrip("#")}</div>' for i,ch in enumerate(channels)) if channels else '<div style="padding:7px 16px;font-size:12px;color:#555a72">No channels</div>'}
    </div>

    <!-- Messages -->
    <div style="flex:1;overflow-y:auto;background:#0d0f14">
      {cards_html}
    </div>
  </div>

  <script>setTimeout(()=>location.reload(),10000)</script>
</body>
</html>""")


@app.get("/api/messages")
async def get_messages():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 200").fetchall()
    return {"messages": [msg_to_dict(r) for r in rows], "count": len(rows)}


@app.get("/health")
async def health():
    return {"status": "ok"}
