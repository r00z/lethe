"""NiceGUI-based console UI — Mission Control style."""

import json
import logging
from datetime import datetime
from typing import Optional

from nicegui import ui, app

from . import get_state

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 2.0

# Role styling
ROLES = {
    "user":      {"color": "#3b82f6", "bg": "rgba(59,130,246,0.08)", "icon": "person",    "label": "USER"},
    "assistant": {"color": "#00d4aa", "bg": "rgba(0,212,170,0.08)",  "icon": "smart_toy", "label": "ASSISTANT"},
    "tool":      {"color": "#f59e0b", "bg": "rgba(245,158,11,0.08)", "icon": "build",     "label": "TOOL"},
    "system":    {"color": "#64748b", "bg": "rgba(100,116,139,0.1)", "icon": "settings",  "label": "SYSTEM"},
}

CSS = """
<style>
    * { box-sizing: border-box; }
    body { margin: 0; padding: 0; overflow: hidden; background: #0f1419; font-family: 'Inter', -apple-system, sans-serif; }
    
    .mc-root { display: flex; flex-direction: column; width: 100vw; height: 100vh; background: #0f1419; color: #e2e8f0; }
    
    /* Header */
    .mc-header {
        display: flex; align-items: center; gap: 16px;
        padding: 6px 16px; background: #111820;
        border-bottom: 1px solid #1e2d3d; flex-shrink: 0; min-height: 36px;
    }
    .mc-title { font-size: 13px; font-weight: 600; color: #00d4aa; letter-spacing: 2px; text-transform: uppercase; }
    .mc-stat { font-size: 11px; color: #64748b; font-family: 'JetBrains Mono', 'Fira Code', monospace; }
    .mc-stat b { color: #94a3b8; font-weight: 500; }
    
    /* Status dot */
    .mc-status { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #94a3b8; font-family: monospace; }
    .mc-dot { width: 8px; height: 8px; border-radius: 50%; }
    .mc-dot-idle { background: #22c55e; }
    .mc-dot-thinking { background: #3b82f6; animation: pulse 1.2s infinite; }
    .mc-dot-tool_call { background: #f59e0b; animation: pulse 0.8s infinite; }
    @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
    
    /* Columns */
    .mc-columns { display: flex; flex: 1; min-height: 0; }
    .mc-panel { display: flex; flex-direction: column; min-width: 0; border-right: 1px solid #1e2d3d; }
    .mc-panel:last-child { border-right: none; }
    .mc-panel-header {
        padding: 8px 12px; font-size: 10px; font-weight: 600; letter-spacing: 1.5px;
        text-transform: uppercase; color: #64748b; background: #111820;
        border-bottom: 1px solid #1e2d3d; flex-shrink: 0;
        display: flex; align-items: center; gap: 8px;
    }
    .mc-panel-header .accent { color: #00d4aa; }
    .mc-panel-content { flex: 1; overflow-y: auto; padding: 8px; }
    .mc-panel-content::-webkit-scrollbar { width: 4px; }
    .mc-panel-content::-webkit-scrollbar-track { background: transparent; }
    .mc-panel-content::-webkit-scrollbar-thumb { background: #2d3f52; border-radius: 2px; }
    
    /* Message cards */
    .mc-msg {
        border-left: 2px solid; padding: 6px 10px; margin-bottom: 4px;
        border-radius: 2px; font-size: 12px;
    }
    .mc-msg-header { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }
    .mc-msg-role { font-size: 9px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; }
    .mc-msg-time { font-size: 9px; color: #475569; margin-left: auto; font-family: monospace; }
    .mc-msg-chip { font-size: 9px; padding: 1px 6px; border-radius: 3px; font-weight: 500; }
    .mc-msg pre {
        white-space: pre-wrap; word-wrap: break-word;
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
        font-size: 11px; margin: 4px 0 0 0; padding: 0; color: #cbd5e1; line-height: 1.5;
    }
    
    /* Memory blocks */
    .mc-block { margin-bottom: 4px; }
    .mc-block-header {
        display: flex; align-items: center; gap: 6px; padding: 6px 8px;
        cursor: pointer; border-radius: 3px; font-size: 11px; color: #94a3b8;
        transition: background 0.15s;
    }
    .mc-block-header:hover { background: rgba(0,212,170,0.05); }
    .mc-block-arrow { font-size: 10px; color: #475569; transition: transform 0.2s; width: 12px; }
    .mc-block-label { font-weight: 600; color: #e2e8f0; }
    .mc-block-meta { font-size: 9px; color: #475569; margin-left: auto; font-family: monospace; }
    .mc-block-body {
        padding: 4px 8px 8px 26px; display: none;
    }
    .mc-block-body.open { display: block; }
    .mc-block-body pre {
        white-space: pre-wrap; word-wrap: break-word;
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
        font-size: 10px; color: #94a3b8; margin: 0; line-height: 1.5;
    }
    .mc-block-desc { font-size: 10px; color: #475569; margin-bottom: 4px; font-style: italic; }
    
    /* No data */
    .mc-empty { color: #475569; font-size: 11px; padding: 16px; text-align: center; }
</style>
<script>
function toggleBlock(id) {
    const el = document.getElementById(id);
    const arrow = document.getElementById('arrow-' + id);
    if (el) {
        el.classList.toggle('open');
        if (arrow) arrow.textContent = el.classList.contains('open') ? '▾' : '▸';
    }
}
</script>
"""

def _esc(text):
    """Escape HTML."""
    if not isinstance(text, str):
        text = str(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class ConsoleUI:
    
    def __init__(self, port: int = 8080):
        self.port = port
        self._last_version = 0
        self._block_counter = 0
        self._setup_ui()
    
    def _setup_ui(self):
        @ui.page("/")
        async def main_page():
            ui.dark_mode().enable()
            ui.add_head_html('<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">')
            ui.add_head_html(CSS)
            
            # Root container
            with ui.element("div").classes("mc-root"):
                # Header
                with ui.element("div").classes("mc-header"):
                    ui.html('<span class="mc-title">◉ Lethe Console</span>')
                    ui.html('<span style="flex:1"></span>')
                    self.status_html = ui.html(self._render_status("idle", None))
                    self.stats_html = ui.html(self._render_stats(0, 0, 0, 0))
                
                # Columns
                with ui.element("div").classes("mc-columns"):
                    # Messages — 30%
                    with ui.element("div").classes("mc-panel").style("width: 30%"):
                        ui.html('<div class="mc-panel-header"><span class="accent">◆</span> Messages</div>')
                        self.msg_scroll = ui.element("div").classes("mc-panel-content")
                        with self.msg_scroll:
                            self.msg_container = ui.element("div")
                    
                    # Memory — 20%
                    with ui.element("div").classes("mc-panel").style("width: 20%"):
                        ui.html('<div class="mc-panel-header"><span class="accent">◆</span> Memory</div>')
                        with ui.element("div").classes("mc-panel-content"):
                            self.mem_container = ui.element("div")
                    
                    # Context — 50%
                    with ui.element("div").classes("mc-panel").style("width: 50%"):
                        with ui.element("div").classes("mc-panel-header"):
                            ui.html('<span class="accent">◆</span> Context')
                            ui.html('<span style="flex:1"></span>')
                            self.ctx_info = ui.html('<span class="mc-stat"></span>')
                        self.ctx_scroll = ui.element("div").classes("mc-panel-content")
                        with self.ctx_scroll:
                            self.ctx_container = ui.element("div")
            
            # Load data
            self._full_rebuild()
            self._last_version = get_state().version
            
            # Scroll to bottom
            ui.timer(0.5, lambda: (
                self._scroll_bottom(self.msg_scroll),
                self._scroll_bottom(self.ctx_scroll),
            ), once=True)
            
            ui.timer(REFRESH_INTERVAL, self._refresh)
    
    # ── Rendering ─────────────────────────────────────────────
    
    def _render_status(self, status, tool):
        dot_cls = f"mc-dot mc-dot-{status}"
        label = status
        if tool:
            label = f"{status}: {tool}"
        return f'<span class="mc-status"><span class="{dot_cls}"></span>{_esc(label)}</span>'
    
    def _render_stats(self, msgs, total, archival, tokens):
        parts = [
            f'<b>{msgs}</b> msgs',
            f'<b>{total}</b> history',
            f'<b>{archival}</b> archival',
        ]
        if tokens:
            parts.append(f'<b>{tokens:,}</b> tok')
        return '<span class="mc-stat">' + ' │ '.join(parts) + '</span>'
    
    def _render_message_html(self, role, content, timestamp=None):
        r = ROLES.get(role, ROLES["system"])
        time_html = f'<span class="mc-msg-time">{_esc(timestamp)}</span>' if timestamp else ''
        return f'''<div class="mc-msg" style="border-color:{r['color']};background:{r['bg']}">
            <div class="mc-msg-header">
                <span class="mc-msg-role" style="color:{r['color']}">{r['label']}</span>
                {time_html}
            </div>
            <pre>{_esc(content)}</pre>
        </div>'''
    
    def _render_context_msg_html(self, msg):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        r = ROLES.get(role, ROLES["system"])
        
        # Extract text from content blocks
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            content = "\n---\n".join(parts) if parts else f"[{len(content)} content blocks]"
        
        # Chips for tool info
        chips = ""
        if msg.get("tool_calls"):
            chips += f'<span class="mc-msg-chip" style="background:rgba(245,158,11,0.15);color:#f59e0b">{len(msg["tool_calls"])} tools</span>'
        if msg.get("tool_call_id"):
            chips += '<span class="mc-msg-chip" style="background:rgba(245,158,11,0.15);color:#f59e0b">result</span>'
        
        return f'''<div class="mc-msg" style="border-color:{r['color']};background:{r['bg']}">
            <div class="mc-msg-header">
                <span class="mc-msg-role" style="color:{r['color']}">{r['label']}</span>
                {chips}
            </div>
            <pre>{_esc(str(content))}</pre>
        </div>'''
    
    def _render_block_html(self, label, value, description="", chars=0, limit=20000):
        self._block_counter += 1
        bid = f"block-{self._block_counter}"
        
        desc_html = f'<div class="mc-block-desc">{_esc(description)}</div>' if description else ''
        
        return f'''<div class="mc-block">
            <div class="mc-block-header" onclick="toggleBlock('{bid}')">
                <span class="mc-block-arrow" id="arrow-{bid}">▸</span>
                <span class="mc-block-label">{_esc(label)}</span>
                <span class="mc-block-meta">{chars:,}/{limit:,}</span>
            </div>
            <div class="mc-block-body" id="{bid}">
                {desc_html}
                <pre>{_esc(value[:5000])}</pre>
            </div>
        </div>'''
    
    # ── Data loading ──────────────────────────────────────────
    
    def _full_rebuild(self):
        state = get_state()
        
        # Messages
        msg_html = []
        for m in state.messages[-30:]:
            msg_html.append(self._render_message_html(
                m.get("role", "?"),
                m.get("content", ""),
                m.get("timestamp"),
            ))
        self.msg_container._props["innerHTML"] = "\n".join(msg_html) if msg_html else '<div class="mc-empty">No messages</div>'
        self.msg_container.update()
        
        # Memory
        mem_html = []
        self._block_counter = 0
        if state.identity:
            mem_html.append(self._render_block_html("identity", state.identity, "System prompt", len(state.identity), 20000))
        if state.summary:
            mem_html.append(self._render_block_html("summary", state.summary, "Conversation summary", len(state.summary), 10000))
        for label, block in state.memory_blocks.items():
            if label == "identity":
                continue
            mem_html.append(self._render_block_html(
                label, block.get("value", ""),
                block.get("description", ""),
                len(block.get("value", "")),
                block.get("limit", 20000),
            ))
        self.mem_container._props["innerHTML"] = "\n".join(mem_html) if mem_html else '<div class="mc-empty">No memory blocks</div>'
        self.mem_container.update()
        
        # Context
        ctx_html = []
        if state.last_context:
            for msg in state.last_context:
                ctx_html.append(self._render_context_msg_html(msg))
        self.ctx_container._props["innerHTML"] = "\n".join(ctx_html) if ctx_html else '<div class="mc-empty">No context captured yet</div>'
        self.ctx_container.update()
        
        # Context info
        if state.last_context_time:
            time_str = state.last_context_time.strftime("%H:%M:%S")
            self.ctx_info._props["innerHTML"] = f'<span class="mc-stat"><b>{state.last_context_tokens:,}</b> tokens @ {time_str}</span>'
            self.ctx_info.update()
        
        # Stats
        self.stats_html._props["innerHTML"] = self._render_stats(
            len(state.messages), state.total_messages, state.archival_count,
            state.last_context_tokens,
        )
        self.stats_html.update()
    
    def _scroll_bottom(self, el):
        ui.run_javascript(f'document.querySelector("[id=\\"c{el.id}\\"]").scrollTop = 999999;')
    
    # ── Refresh loop ──────────────────────────────────────────
    
    def _refresh(self):
        state = get_state()
        
        # Always update status (lightweight)
        self.status_html._props["innerHTML"] = self._render_status(state.status, state.current_tool)
        self.status_html.update()
        
        # Rebuild only on data change
        if state.version != self._last_version:
            self._last_version = state.version
            self._full_rebuild()
            self._scroll_bottom(self.msg_scroll)
            self._scroll_bottom(self.ctx_scroll)
    
    def run(self):
        logger.info(f"Starting Lethe Console on port {self.port}")
        ui.run(
            port=self.port,
            title="Lethe Console",
            favicon="🧠",
            show=False,
            reload=False,
        )


async def run_console(port: int = 8080):
    console = ConsoleUI(port=port)
    import threading
    threading.Thread(target=console.run, daemon=True).start()
    logger.info(f"Lethe Console started on http://localhost:{port}")
