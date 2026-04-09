import sqlite3
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

app = FastAPI(title="Jira Mock")

DB_PATH = os.environ.get("JIRA_DB_PATH", "/data/jira.db")

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            summary TEXT NOT NULL,
            description TEXT DEFAULT '',
            priority TEXT DEFAULT 'Medium',
            labels TEXT DEFAULT '',
            status TEXT DEFAULT 'Open',
            created_at TEXT NOT NULL,
            url TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS counter (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            value INTEGER NOT NULL DEFAULT 100
        )
    """)
    conn.execute("INSERT OR IGNORE INTO counter (id, value) VALUES (1, 100)")
    conn.commit()
    return conn

def next_counter(conn):
    conn.execute("UPDATE counter SET value = value + 1 WHERE id = 1")
    return conn.execute("SELECT value FROM counter WHERE id = 1").fetchone()["value"]

def row_to_dict(row):
    d = dict(row)
    d["labels"] = [l for l in d["labels"].split(",") if l] if d["labels"] else []
    return d


class CreateIssueRequest(BaseModel):
    summary: str
    description: Optional[str] = None
    priority: Optional[str] = "Medium"
    labels: Optional[List[str]] = None

class IssueResponse(BaseModel):
    id: str
    key: str
    summary: str
    description: Optional[str]
    priority: str
    labels: List[str]
    status: str
    created_at: str
    url: str


@app.post("/api/issues", response_model=IssueResponse)
async def create_issue(data: CreateIssueRequest):
    conn = get_db()
    n = next_counter(conn)
    key = f"JIRA-{n}"
    labels_str = ",".join(data.labels or [])
    created_at = datetime.utcnow().isoformat()
    url = f"http://localhost:8080/browse/{key}"
    conn.execute(
        "INSERT INTO issues (key, summary, description, priority, labels, status, created_at, url) "
        "VALUES (?, ?, ?, ?, ?, 'Open', ?, ?)",
        (key, data.summary, data.description or "", data.priority or "Medium", labels_str, created_at, url)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM issues WHERE key = ?", (key,)).fetchone()
    d = row_to_dict(row)
    d["id"] = str(d["id"])
    conn.close()
    return IssueResponse(**d)


@app.get("/api/issues", response_model=List[IssueResponse])
async def list_issues():
    conn = get_db()
    rows = conn.execute("SELECT * FROM issues ORDER BY id DESC").fetchall()
    conn.close()
    result = []
    for row in rows:
        d = row_to_dict(row)
        d["id"] = str(d["id"])
        result.append(IssueResponse(**d))
    return result


@app.get("/api/issues/{key}", response_model=IssueResponse)
async def get_issue(key: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM issues WHERE key = ?", (key,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Issue not found")
    d = row_to_dict(row)
    d["id"] = str(d["id"])
    return IssueResponse(**d)


@app.get("/browse/{key}", response_class=HTMLResponse)
async def browse_issue(key: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM issues WHERE key = ?", (key,)).fetchone()
    conn.close()
    if not row:
        return HTMLResponse("<html><body><h1>404 - Issue Not Found</h1></body></html>", status_code=404)

    issue = row_to_dict(row)
    priority_colors = {"Critical": "#dc2626", "High": "#ea580c", "Medium": "#ca8a04", "Low": "#16a34a"}
    pcolor = priority_colors.get(issue["priority"], "#6b7280")
    labels_html = "".join(
        f'<span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:12px;margin-right:4px">{l}</span>'
        for l in issue["labels"]
    )
    desc_html = (issue["description"] or "").replace("\n", "<br>")

    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>{issue['key']} - Jira Mock</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f3f4f6;margin:0;padding:0}}
    .header{{background:#0052CC;color:white;padding:16px 32px;font-size:18px;font-weight:700}}
    .container{{max-width:900px;margin:32px auto;padding:0 16px}}
    .card{{background:white;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);padding:32px}}
    .key{{font-size:13px;color:#6b7280;font-weight:600;margin-bottom:8px}}
    .summary{{font-size:24px;font-weight:700;color:#111827;margin-bottom:24px}}
    .meta{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:24px;padding:16px;background:#f9fafb;border-radius:6px}}
    .meta-item label{{font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em}}
    .meta-item p{{font-size:15px;font-weight:600;color:#111827;margin:4px 0 0}}
    .badge{{display:inline-block;padding:3px 10px;border-radius:4px;font-size:13px;font-weight:600;color:white}}
    .section-title{{font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;font-weight:600}}
    .description{{color:#374151;line-height:1.7;font-size:14px}}
    .back{{display:inline-block;margin-bottom:16px;color:#0052CC;text-decoration:none;font-size:14px}}
    .back:hover{{text-decoration:underline}}
  </style>
</head>
<body>
  <div class="header">Jira Mock</div>
  <div class="container">
    <a href="/" class="back">← All Issues</a>
    <div class="card">
      <div class="key">{issue['key']}</div>
      <div class="summary">{issue['summary']}</div>
      <div class="meta">
        <div class="meta-item">
          <label>Status</label>
          <p>{issue['status']}</p>
        </div>
        <div class="meta-item">
          <label>Priority</label>
          <p><span class="badge" style="background:{pcolor}">{issue['priority']}</span></p>
        </div>
        <div class="meta-item">
          <label>Created</label>
          <p style="font-size:13px">{issue['created_at'][:19].replace('T',' ')}</p>
        </div>
      </div>
      {f'<div style="margin-bottom:24px"><div class="section-title">Labels</div>{labels_html}</div>' if issue['labels'] else ''}
      <div>
        <div class="section-title">Description</div>
        <div class="description">{desc_html or '<em style="color:#9ca3af">No description</em>'}</div>
      </div>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    conn = get_db()
    rows = conn.execute("SELECT * FROM issues ORDER BY id DESC").fetchall()
    conn.close()

    rows_html = ""
    priority_colors = {"Critical": "#dc2626", "High": "#ea580c", "Medium": "#ca8a04", "Low": "#16a34a"}
    for row in rows:
        issue = row_to_dict(row)
        pcolor = priority_colors.get(issue["priority"], "#6b7280")
        labels_html = "".join(
            f'<span style="background:#dbeafe;color:#1e40af;padding:1px 6px;border-radius:3px;font-size:11px;margin-right:3px">{l}</span>'
            for l in issue["labels"]
        )
        rows_html += f"""
        <tr>
          <td><a href="/browse/{issue['key']}" style="color:#0052CC;font-weight:600;text-decoration:none">{issue['key']}</a></td>
          <td style="max-width:360px">{issue['summary']}</td>
          <td><span style="background:{pcolor};color:white;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600">{issue['priority']}</span></td>
          <td>{issue['status']}</td>
          <td style="font-size:12px;color:#6b7280">{issue['created_at'][:10]}</td>
          <td>{labels_html}</td>
        </tr>"""

    empty = '<tr><td colspan="6" style="text-align:center;padding:32px;color:#9ca3af">No issues yet</td></tr>'

    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Jira Mock</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f3f4f6;margin:0}}
    .header{{background:#0052CC;color:white;padding:16px 32px}}
    .header h1{{margin:0;font-size:20px;font-weight:700}}
    .header p{{margin:4px 0 0;font-size:13px;opacity:.8}}
    .container{{max-width:1100px;margin:32px auto;padding:0 16px}}
    .card{{background:white;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);overflow:hidden}}
    table{{width:100%;border-collapse:collapse}}
    thead{{background:#f9fafb}}
    th{{padding:12px 16px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#6b7280;font-weight:600;border-bottom:1px solid #e5e7eb}}
    td{{padding:12px 16px;border-bottom:1px solid #f3f4f6;font-size:14px;color:#374151;vertical-align:middle}}
    tr:hover td{{background:#f9fafb}}
    tr:last-child td{{border-bottom:none}}
    .count{{font-size:13px;color:#6b7280;margin-bottom:12px}}
  </style>
</head>
<body>
  <div class="header">
    <h1>Jira Mock</h1>
    <p>Incident Cortex — Issue Tracker</p>
  </div>
  <div class="container">
    <div class="count">{len(rows)} issue(s)</div>
    <div class="card">
      <table>
        <thead>
          <tr>
            <th>Key</th><th>Summary</th><th>Priority</th><th>Status</th><th>Created</th><th>Labels</th>
          </tr>
        </thead>
        <tbody>{rows_html or empty}</tbody>
      </table>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/health")
async def health():
    return {"status": "ok"}
