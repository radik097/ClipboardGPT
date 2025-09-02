#!/usr/bin/env python3
"""Flet frontend for BeepConf Chat — single-file entrypoint.

This module contains the Flet UI and a small local backend stub.
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
import sys
import os
import traceback
from openai import OpenAI

try:
    import flet as ft
except Exception:
    print("Flet is not installed. Install with: pip install flet")
    raise SystemExit(1)

# -------------------------------
# Backend integration hook
# -------------------------------
async def send_to_backend(prompt: str, attached_preset: str | None) -> str:
    """
    Call OpenAI Chat Completions via the official SDK in a threadpool to
    avoid blocking the Flet asyncio loop.

    Uses environment variables:
      - OPENAI_API_KEY
      - OPENAI_API_BASE or OPENAI_BASE_URL
      - OPENAI_MODEL (optional, default gpt-3.5-turbo)
      - OPENAI_TIMEOUT (optional seconds, default 60)
    Returns the combined text response (first candidate by default) or an
    error string starting with "ERROR:" on failure.
    """
    loop = asyncio.get_running_loop()

    def blocking_call():
        try:
            api_key = os.environ.get("OPENAI_API_KEY")
            base = os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL")
            model = os.environ.get("OPENAI_MODEL") or "gpt-3.5-turbo"
            timeout = int(os.environ.get("OPENAI_TIMEOUT") or 60)

            client_kwargs = {}
            if api_key:
                client_kwargs["api_key"] = api_key
            if base:
                client_kwargs["api_base"] = base

            client = OpenAI(**client_kwargs) if client_kwargs else OpenAI()

            messages = []
            if attached_preset:
                messages.append({"role": "system", "content": attached_preset})
            # keep a short system instruction
            messages.append({"role": "system", "content": "You are a helpful assistant."})
            messages.append({"role": "user", "content": prompt})

            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.2,
                    n=1,
                    max_tokens=1024,
                    request_timeout=timeout,
                )
            except TypeError as te:
                if "request_timeout" in str(te):
                    resp = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0.2,
                        n=1,
                        max_tokens=1024,
                    )
                else:
                    raise

            # Parse response
            choices = getattr(resp, "choices", None) or (resp.get("choices") if isinstance(resp, dict) else [])
            parts = []
            for c in choices:
                if isinstance(c, dict):
                    m = c.get("message") or {}
                    txt = m.get("content") or c.get("text") or ""
                else:
                    msg = getattr(c, "message", None)
                    txt = getattr(msg, "content", "") if msg else getattr(c, "text", "") or ""
                txt = (txt or "").strip()
                if txt:
                    parts.append(txt)

            return "\n\n".join(parts) if parts else ""
        except Exception as e:
            tb = traceback.format_exc()
            # return an informative error to the caller
            return f"ERROR: {e}\n{tb}"

    # run blocking call in default executor
    result = await loop.run_in_executor(None, blocking_call)
    return result


# -------------------------------
# Data layer: simple persistent history via client_storage
# -------------------------------
HIST_KEY = "beep_hist"
THEME_KEY = "beep_theme"
PRESETS_FILE = str(Path(__file__).parent / "presets.json")


def load_presets() -> list[dict]:
    """
    Формат: [{"name":"...", "text":"..."}, ...]
    Если файла нет — вернём пару демо-пресетов.
    """
    try:
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [p for p in data if isinstance(p, dict) and "text" in p]
    except Exception:
        pass
    return [
        {"name": "Helpful", "text": "You are a helpful assistant."},
        {"name": "Strict", "text": "Be direct and concise."},
    ]


def load_history(page: ft.Page) -> list[dict]:
    try:
        raw = page.client_storage.get(HIST_KEY)
        hist = json.loads(raw) if raw else []
        if isinstance(hist, list):
            return hist[-200:]
    except Exception:
        pass
    return []


def save_history(page: ft.Page, hist: list[dict]) -> None:
    try:
        page.client_storage.set(HIST_KEY, json.dumps(hist[-200:], ensure_ascii=False))
    except Exception:
        pass


def save_theme(page: ft.Page, theme_mode: str) -> None:
    try:
        page.client_storage.set(THEME_KEY, theme_mode)
    except Exception:
        pass


def load_theme(page: ft.Page) -> str:
    try:
        t = page.client_storage.get(THEME_KEY)
        if t in ("light", "dark"):
            return t
    except Exception:
        pass
    return "dark" if page.platform_brightness == ft.Brightness.DARK else "light"


# -------------------------------
# UI constants
# -------------------------------
class Palette:
    def __init__(self, dark: bool):
        if not dark:
            self.bg = ft.Colors.with_opacity(1, "#f6f7f9")
            self.card = "#ffffff"
            self.text = "#0f172a"
            self.muted = "#667085"
            self.border = "#e6e8ec"
            self.primary = "#2663eb"
            self.primary2 = "#1742a0"
            self.accent = "#eff4ff"
            self.bubble_user = "#e8f1ff"
            self.bubble_ai = "#ffffff"
            self.scroll = "#2b334277"
        else:
            self.bg = "#0b0f15"
            self.card = "#0f141b"
            self.text = "#e5e7eb"
            self.muted = "#94a3b8"
            self.border = "#1c2430"
            self.primary = "#5a8bff"
            self.primary2 = "#3a64d8"
            self.accent = "#0f1a2e"
            self.bubble_user = "#0f2449"
            self.bubble_ai = "#121a24"
            self.scroll = "#9aa7be77"


def message_row(
    text: str,
    role: str,  # "req" | "resp"
    pal: Palette,
    on_copy=None,
) -> ft.Row:
    is_user = role == "req"

    # CircleAvatar doesn't support gradient background; use solid bgcolor and color for text
    avatar = ft.CircleAvatar(
        content=ft.Text("YOU" if is_user else "AI", size=10, weight=ft.FontWeight.W_700),
        radius=14,
        bgcolor=pal.primary if is_user else "#22c55e",
    color=ft.Colors.WHITE,
    )

    bubble_bg = pal.bubble_user if is_user else pal.bubble_ai

    bubble = ft.Container(
        content=ft.Text(text, selectable=True),
        padding=ft.padding.symmetric(10, 12),
        width=None,
        bgcolor=bubble_bg,
    border=ft.border.all(1, pal.border if not is_user else ft.Colors.with_opacity(0, pal.border)),
        border_radius=ft.border_radius.only(
            top_left=14 if not is_user else 14,
            top_right=6 if is_user else 14,
            bottom_left=14,
            bottom_right=14,
        ),
    shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.05, "#000000")),
    )

    row_children = []
    if is_user:
        row_children = [ft.Container(expand=1), bubble, avatar]
        alignment = ft.MainAxisAlignment.END
    else:
        copy_btn = ft.TextButton(
            content=ft.Row([ft.Icon(ft.Icons.CONTENT_COPY, size=14), ft.Text("Copy", size=12)], spacing=4),
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(4, 8),
                shape=ft.RoundedRectangleBorder(radius=8),
                side=ft.BorderSide(1, pal.border),
                bgcolor={
                    ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
                    ft.ControlState.HOVERED: ft.Colors.with_opacity(0.08, "#64748B"),
                },
            ),
            on_click=lambda _: on_copy(text) if on_copy else None,
        )
        row_children = [avatar, bubble, copy_btn, ft.Container(expand=1)]
        alignment = ft.MainAxisAlignment.START

    return ft.Row(row_children, vertical_alignment=ft.CrossAxisAlignment.END, alignment=alignment, spacing=10)


def flet_main(page: ft.Page):
    page.title = "BeepConf Chat"
    # Window size properties are set via page.window
    page.window.min_width = 900
    page.window.min_height = 600
    page.scroll = ft.ScrollMode.AUTO

    # Theme mode expects ft.ThemeMode enum, but we persist a string ("light"|"dark")
    theme_mode_str = load_theme(page)
    page.theme_mode = ft.ThemeMode.DARK if theme_mode_str == "dark" else ft.ThemeMode.LIGHT
    pal = Palette(dark=page.theme_mode == ft.ThemeMode.DARK)
    page.bgcolor = pal.bg

    brand_dot = ft.Container(
        width=10,
        height=10,
        border_radius=50,
        gradient=ft.RadialGradient(center=ft.Alignment(0.3, 0.3), radius=1.0, colors=["#7aa2ff", pal.primary]),
    )

    presets = load_presets()
    presets_dd = ft.Dropdown(width=280, options=[ft.dropdown.Option(p.get("text", "")) for p in presets], value=None, hint_text="Choose preset…", dense=True)
    pinned = ft.Container(content=ft.Text("", size=12, selectable=True, color=pal.muted), bgcolor=pal.accent, border=ft.border.all(1, pal.border), border_radius=10, padding=8, height=140, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)

    attached_preset: dict | None = {"text": None}

    def attach_preset(_):
        txt = presets_dd.value or ""
        if not txt:
            return
        attached_preset["text"] = txt
        pinned.content = ft.Text(txt[:2000], size=12, selectable=True, color=pal.muted)
        pinned.update()

    def detach_preset(_):
        attached_preset["text"] = None
        pinned.content = ft.Text("", size=12, selectable=True, color=pal.muted)
        pinned.update()

    load_btn = ft.ElevatedButton("Attach", icon="link", on_click=attach_preset)
    detach_btn = ft.TextButton("Detach", icon="link_off", on_click=detach_preset)

    history_col = ft.Column(spacing=8, scroll=ft.ScrollMode.ADAPTIVE)

    def render_history_list():
        history_col.controls.clear()
        hist = load_history(page)
        for h in reversed(hist):
            when = datetime.fromtimestamp(h.get("t", 0) / 1000).strftime("%Y-%m-%d %H:%M")
            preview = (h.get("req") or "")[:60].replace("\n", " ")
            btn = ft.OutlinedButton(f"{when} — {preview}", style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)), on_click=lambda e, item=h: show_item(item))
            history_col.controls.append(btn)
        history_col.update()

    # ListView does not accept visual kwargs like bgcolor/border/radius on some Flet versions.
    # Visuals are provided by the surrounding Container in the layout below.
    output_lv = ft.ListView(expand=True, spacing=8, auto_scroll=True, padding=ft.padding.only(14, 14, 14, 8))

    typing_text = ft.Text("typing…", size=12, color=pal.muted, visible=False)

    input_tf = ft.TextField(hint_text="Type your message... (Ctrl+Enter to send)", multiline=True, min_lines=3, max_lines=6, expand=True, border_radius=10, border_color=pal.border, on_change=lambda e: toggle_send_button())
    send_btn = ft.ElevatedButton("Send", icon="send", disabled=True)
    copy_last_btn = ft.TextButton("Copy", icon=ft.Icons.CONTENT_COPY)

    theme_btn = ft.IconButton(icon=("dark_mode" if page.theme_mode == ft.ThemeMode.LIGHT else "light_mode"), tooltip="Toggle theme")
    clear_btn = ft.TextButton("Clear history", icon="clear_all")

    def toggle_theme(_):
        # Toggle between LIGHT and DARK and persist as string
        new_mode = ft.ThemeMode.DARK if page.theme_mode == ft.ThemeMode.LIGHT else ft.ThemeMode.LIGHT
        page.theme_mode = new_mode
        save_theme(page, "dark" if new_mode == ft.ThemeMode.DARK else "light")
        page.clean()
        flet_main(page)

    theme_btn.on_click = toggle_theme

    def toggle_send_button():
        send_btn.disabled = not bool(input_tf.value.strip())
        send_btn.update()

    def kb_handler(e: ft.KeyboardEvent):
        if e.key == "Enter" and e.ctrl and input_tf.focused:
            do_send()

    page.on_keyboard_event = kb_handler

    state = {"last_req_text": "", "last_resp_text": ""}

    def append_message(text: str, role: str):
        nonlocal pal
        row = message_row(text=text, role=role, pal=pal, on_copy=lambda t: page.set_clipboard(t))
        output_lv.controls.append(row)
        output_lv.update()

    def save_hist_pair(req: str, resp: str):
        hist = load_history(page)
        hist.append({"t": int(datetime.now().timestamp() * 1000), "req": req, "resp": resp})
        save_history(page, hist)
        render_history_list()

    def show_item(item: dict):
        output_lv.controls.clear()
        append_message(item.get("req", ""), "req")
        append_message(item.get("resp", ""), "resp")
        output_lv.update()

    async def process_send(prompt: str, preset: str | None):
        return await send_to_backend(prompt, preset)

    def on_task_done(t: asyncio.Task):
        typing_text.visible = False
        send_btn.disabled = False
        try:
            resp = t.result()
        except Exception as ex:
            resp = f"ERROR: {ex}"
        append_message(resp, "resp")
        state["last_resp_text"] = resp
        save_hist_pair(state["last_req_text"], resp)
        page.update()

    def do_send(_=None):
        txt = input_tf.value.strip()
        if not txt:
            return
        append_message(txt, "req")
        state["last_req_text"] = txt
        state["last_resp_text"] = ""
        input_tf.value = ""
        input_tf.update()
        send_btn.disabled = True
        typing_text.visible = True
        page.update()

        preset = attached_preset["text"]
        # Pass coroutine function and its args to run_task (do not call it here)
        page.run_task(process_send, txt, preset, on_complete=on_task_done)

    # Bind send button click handler once
    send_btn.on_click = do_send

    # Copy last response button
    def copy_last(_=None):
        if state["last_resp_text"]:
            page.set_clipboard(state["last_resp_text"])
    copy_last_btn.on_click = copy_last

    def clear_history(_):
        page.client_storage.remove(HIST_KEY)
        output_lv.controls.clear()
        render_history_list()
        page.update()

    clear_btn.on_click = clear_history

    sidebar = ft.Container(content=ft.Column([ft.Text("Presets", size=12, color=pal.muted), presets_dd, ft.Row([load_btn, detach_btn], spacing=8), ft.Divider(color=pal.border), ft.Text("Pinned preset", size=12, color=pal.muted), pinned, ft.Divider(color=pal.border), ft.Text("History", size=12, color=pal.muted), ft.Container(content=history_col, expand=True)], spacing=8, expand=True), width=300, bgcolor=pal.card, border=ft.border.all(1, pal.border), border_radius=12, padding=12)

    top_bar = ft.Container(content=ft.Row([ft.Row([brand_dot, ft.Text("BeepConf Chat", weight=ft.FontWeight.BOLD)], spacing=10, alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER, expand=True), typing_text, theme_btn, clear_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER), bgcolor=pal.card, border=ft.border.all(1, pal.border), border_radius=12, padding=ft.padding.symmetric(10, 12))

    input_row = ft.Row([ft.Container(input_tf, expand=True), ft.Column([send_btn, copy_last_btn], spacing=10, alignment=ft.MainAxisAlignment.END)], spacing=10, vertical_alignment=ft.CrossAxisAlignment.END)

    main_col = ft.Column([top_bar, ft.Container(output_lv, expand=True, bgcolor=pal.card, border_radius=12), input_row], spacing=10, expand=True)

    root = ft.Row([sidebar, main_col], spacing=10, expand=True)

    page.add(root)

    # Initial render of history
    render_history_list()
    page.update()


if __name__ == "__main__":
    ft.app(target=flet_main)
