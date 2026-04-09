#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Gramps Development Team
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.
#

"""
GrampsAssist — a persistent AI chatbot ASSISTPANEL plugin for Gramps.
"""

import logging
import re
import uuid

from gi.repository import GLib, Gdk, Gtk, Pango

from gramps.gen.config import config as global_config
from gramps.gui.assistpanel import BaseAssistPanel

from backend import AnthropicBackend, OpenAICompatibleBackend
from tools import call_tool, get_tools_schema, register_gramps_tools, tool_registry
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.gettext
_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plugin-local configuration
# ---------------------------------------------------------------------------

_cfg = global_config.register_manager("GrampsAssist", use_config_path=True)
_cfg.register("backend.type", "openai")
_cfg.register("backend.url", "http://localhost:11434")
_cfg.register("backend.model", "")
_cfg.register("backend.api_key", "")
_cfg.register(
    "chat.system_prompt",
    _("You are a helpful genealogy assistant with access to the user's Gramps database. "
      "Answer questions about people, families, events, and relationships. "
      "Use the available tools to look up information when needed."),
)
_cfg.register("chat.include_context", True)
_cfg.register("chat.simplify_tools", False)
try:
    _cfg.load()
except Exception:
    pass  # file may not exist yet on first run


# ---------------------------------------------------------------------------
# GrampsAssist
# ---------------------------------------------------------------------------


class GrampsAssist(BaseAssistPanel):
    """
    Persistent assist-panel chatbot that supports OpenAI-compatible and
    Anthropic backends, streaming output, and Python function tools.
    """

    def __init__(self, dbstate, uistate):
        self.dbstate = dbstate
        self.uistate = uistate

        self._messages = []             # conversation history (OpenAI format)
        self._thread_id = str(uuid.uuid4())  # Opik thread; rotated on Clear
        self._streaming = False         # True while a request is in flight
        self._cancelled = False         # set True when panel is hidden/destroyed
        self._current_context = ""
        self._full_response = ""        # full text of current turn (for history)
        # Line-by-line streaming markdown state
        self._line_buffer = ""          # partial (uncommitted) current line
        self._line_start_mark = None    # TextMark at start of _line_buffer in buffer
        self._in_code_block = False     # inside a ``` fence?
        self._table_buffer = []         # raw table lines buffered until table ends
        # Maps unique tag name → URL for clickable links
        self._link_tags = {}

        # Register the built-in Gramps tools
        register_gramps_tools(dbstate, uistate)

        # Build backend from current config
        self._backend = self._make_backend()

        # Build the GTK widget tree
        self._build_ui()

        # Connect to navigation history for context updates
        self._connect_history_signals()
        self._update_context_label()

    # ------------------------------------------------------------------
    # BaseAssistPanel interface
    # ------------------------------------------------------------------

    def get_top(self):
        return self.top

    def view_changed(self, cat_num, view_num):
        self._update_context()

    def db_changed(self, db):
        self._messages.clear()
        self._thread_id = str(uuid.uuid4())
        self._current_context = ""

    def active(self, cat_num, view_num):
        self._cancelled = False

    def inactive(self):
        self._cancelled = True

    # ------------------------------------------------------------------
    # GTK widget construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.top.set_border_width(4)

        # --- Chat display ---
        chat_scroll = Gtk.ScrolledWindow()
        chat_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        chat_scroll.set_vexpand(True)
        chat_scroll.set_size_request(-1, 200)

        self._chat_view = Gtk.TextView()
        self._chat_view.set_editable(False)
        self._chat_view.set_cursor_visible(False)
        self._chat_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._chat_view.set_left_margin(6)
        self._chat_view.set_right_margin(6)
        self._chat_view.set_top_margin(4)
        self._chat_view.set_bottom_margin(4)

        self._chat_buffer = self._chat_view.get_buffer()
        self._create_text_tags()
        self._chat_view.connect("button-press-event", self._on_chat_button_press)

        # Welcome message
        self._show_welcome()

        chat_scroll.add(self._chat_view)

        # --- Separator ---
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)

        # --- Input area (vertical): [text input full-width] / [⚙  Clear  →  Send] ---
        input_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        input_area.set_border_width(4)

        # Multi-line input spanning full width
        input_scroll = Gtk.ScrolledWindow()
        input_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        input_scroll.set_shadow_type(Gtk.ShadowType.IN)
        input_scroll.set_size_request(-1, 80)
        input_scroll.set_hexpand(True)

        self._input_view = Gtk.TextView()
        self._input_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._input_view.set_left_margin(4)
        self._input_view.set_right_margin(4)
        self._input_view.set_top_margin(4)
        self._input_view.set_bottom_margin(4)
        self._input_buffer = self._input_view.get_buffer()
        self._input_view.connect("key-press-event", self._on_key_press)

        input_scroll.add(self._input_view)

        # Button row below the text input
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        settings_btn = Gtk.Button(label="⚙")
        settings_btn.set_tooltip_text(_("Gramps Assistant settings"))
        settings_btn.connect("clicked", self._on_settings_clicked)

        clear_btn = Gtk.Button(label=_("Clear"))
        clear_btn.set_tooltip_text(_("Clear conversation and context"))
        clear_btn.connect("clicked", self._on_clear_clicked)

        self._send_btn = Gtk.Button(label=_("Send"))
        self._send_btn.connect("clicked", self._on_send_clicked)

        self._context_label = Gtk.Label(label="")
        self._context_label.set_xalign(0.5)

        btn_row.pack_start(settings_btn, False, False, 0)
        btn_row.pack_start(clear_btn, False, False, 0)
        btn_row.pack_start(self._context_label, True, True, 4)
        btn_row.pack_end(self._send_btn, False, False, 0)

        input_area.pack_start(input_scroll, False, False, 0)
        input_area.pack_start(btn_row, False, False, 0)

        # --- Assemble ---
        self.top.pack_start(chat_scroll, True, True, 0)
        self.top.pack_start(sep, False, False, 2)
        self.top.pack_start(input_area, False, False, 0)

        self.top.show_all()

    def _create_text_tags(self):
        buf = self._chat_buffer

        buf.create_tag(
            "user_label",
            weight=Pango.Weight.BOLD,
            foreground="#1a6496",
        )
        buf.create_tag(
            "user_body",
            foreground="#1a6496",
            left_margin=12,
        )
        buf.create_tag(
            "assistant_label",
            weight=Pango.Weight.BOLD,
            foreground="#2d6a2d",
        )
        buf.create_tag(
            "assistant_body",
            foreground="#1a1a1a",
            left_margin=12,
        )
        buf.create_tag(
            "tool_call",
            family="Monospace",
            foreground="#888888",
            style=Pango.Style.ITALIC,
            left_margin=12,
            size_points=9.0,
        )
        buf.create_tag(
            "tool_result",
            family="Monospace",
            foreground="#555555",
            left_margin=12,
            size_points=9.0,
        )
        buf.create_tag(
            "error",
            foreground="#cc0000",
            weight=Pango.Weight.BOLD,
        )

        # Markdown rendering tags
        buf.create_tag(
            "md_h1",
            weight=Pango.Weight.BOLD,
            scale=1.4,
            left_margin=12,
        )
        buf.create_tag(
            "md_h2",
            weight=Pango.Weight.BOLD,
            scale=1.2,
            left_margin=12,
        )
        buf.create_tag(
            "md_h3",
            weight=Pango.Weight.BOLD,
            scale=1.05,
            left_margin=12,
        )
        buf.create_tag(
            "md_bold",
            weight=Pango.Weight.BOLD,
            left_margin=12,
        )
        buf.create_tag(
            "md_italic",
            style=Pango.Style.ITALIC,
            left_margin=12,
        )
        buf.create_tag(
            "md_bold_italic",
            weight=Pango.Weight.BOLD,
            style=Pango.Style.ITALIC,
            left_margin=12,
        )
        buf.create_tag(
            "md_code_inline",
            family="Monospace",
            foreground="#c7254e",
            background="#f9f2f4",
            size_points=9.0,
        )
        buf.create_tag(
            "md_code_block",
            family="Monospace",
            foreground="#333333",
            background="#f5f5f5",
            left_margin=16,
            size_points=9.0,
        )
        buf.create_tag(
            "md_bullet",
            left_margin=20,
        )
        buf.create_tag(
            "md_table_row",
            family="Monospace",
            foreground="#222222",
            background="#f7f7f7",
            left_margin=12,
            size_points=9.0,
        )

    # ------------------------------------------------------------------
    # Buffer helpers (always called on GTK main thread)
    # ------------------------------------------------------------------

    def _append_text(self, text: str, tag_name: str = None):
        """Insert *text* at end of chat buffer with optional tag."""
        end_iter = self._chat_buffer.get_end_iter()
        if tag_name:
            self._chat_buffer.insert_with_tags_by_name(end_iter, text, tag_name)
        else:
            self._chat_buffer.insert(end_iter, text)
        self._scroll_to_end()

    def _scroll_to_end(self):
        self._chat_buffer.place_cursor(self._chat_buffer.get_end_iter())
        self._chat_view.scroll_mark_onscreen(self._chat_buffer.get_insert())

    def _update_context_label(self):
        """Recompute and display the approximate token count of the current context."""
        if not self._messages:
            self._context_label.set_text("")
            return
        total_chars = sum(
            len(m.get("content") or "")
            for m in self._messages
        )
        # Include system prompt + active-person context in the estimate
        total_chars += len(_cfg.get("chat.system_prompt"))
        if self._current_context:
            total_chars += len(self._current_context)
        approx_tokens = total_chars // 4
        if approx_tokens == 0:
            self._context_label.set_text("")
        elif approx_tokens < 1000:
            self._context_label.set_text(f"~{approx_tokens} tokens")
        else:
            self._context_label.set_text(f"~{approx_tokens / 1000:.1f}k tokens")

    def _show_welcome(self):
        self._append_text(_("Gramps Assistant:") + "\n", "assistant_label")
        self._append_text(
            _("Ask me anything about the Gramps program or your specific Gramps family tree. "
              "Use the ⚙ button to configure the AI.\n"),
            "assistant_body",
        )

    # ------------------------------------------------------------------
    # Markdown rendering
    # ------------------------------------------------------------------

    # Matches [text](url), `code`, ***bold-italic***, **bold**, *italic*, _variants_
    _INLINE_RE = re.compile(
        r"\[([^\]]+)\]\(([^)]+)\)"    # [link text](url)   → groups 1, 2
        r"|(`+)(.+?)\3"               # `code`             → groups 3, 4
        r"|\*\*\*(.+?)\*\*\*"         # ***bold italic***  → group 5
        r"|___(.+?)___"               # ___bold italic___  → group 6
        r"|\*\*(.+?)\*\*"             # **bold**           → group 7
        r"|__(.+?)__"                 # __bold__           → group 8
        r"|\*(.+?)\*"                 # *italic*           → group 9
        r"|_(.+?)_",                  # _italic_           → group 10
        re.DOTALL,
    )

    # Separator rows: | --- | :---: | ---: |
    _TABLE_SEP_RE = re.compile(r"^\|[\s\-:|]+\|[\s\-:|]*$")

    def _insert_inline(self, text: str, base_tag: str):
        """Insert *text* into the buffer, applying inline markdown tags."""
        buf = self._chat_buffer
        pos = 0
        for m in self._INLINE_RE.finditer(text):
            if m.start() > pos:
                end = buf.get_end_iter()
                buf.insert_with_tags_by_name(end, text[pos:m.start()], base_tag)
            end = buf.get_end_iter()
            if m.group(1):      # [text](url)
                self._insert_link(m.group(1), m.group(2))
            elif m.group(3):    # `code`
                buf.insert_with_tags_by_name(end, m.group(4), "md_code_inline")
            elif m.group(5):    # ***bold italic***
                buf.insert_with_tags_by_name(end, m.group(5), "md_bold_italic")
            elif m.group(6):    # ___bold italic___
                buf.insert_with_tags_by_name(end, m.group(6), "md_bold_italic")
            elif m.group(7):    # **bold**
                buf.insert_with_tags_by_name(end, m.group(7), "md_bold")
            elif m.group(8):    # __bold__
                buf.insert_with_tags_by_name(end, m.group(8), "md_bold")
            elif m.group(9):    # *italic*
                buf.insert_with_tags_by_name(end, m.group(9), "md_italic")
            elif m.group(10):   # _italic_
                buf.insert_with_tags_by_name(end, m.group(10), "md_italic")
            pos = m.end()
        if pos < len(text):
            end = buf.get_end_iter()
            buf.insert_with_tags_by_name(end, text[pos:], base_tag)

    def _insert_link(self, text: str, url: str):
        """Insert a styled, clickable hyperlink into the buffer."""
        buf = self._chat_buffer
        tag_name = f"_link_{len(self._link_tags)}"
        buf.create_tag(
            tag_name,
            foreground="#0645ad",
            underline=Pango.Underline.SINGLE,
        )
        self._link_tags[tag_name] = url.strip()
        end = buf.get_end_iter()
        buf.insert_with_tags_by_name(end, text, tag_name)

    # CSS applied once per instance for embedded tables
    _TABLE_CSS = b"""
        .ga-table {
            border: 1px solid #bbbbbb;
            background-color: #bbbbbb;
        }
        .ga-table-header {
            background-color: #dde8f0;
            padding: 3px 10px;
        }
        .ga-table-cell {
            background-color: #ffffff;
            padding: 3px 10px;
        }
    """

    @staticmethod
    def _md_to_pango(text: str) -> str:
        """Convert simple inline markdown to Pango markup."""
        import html as _html
        out = _html.escape(text)
        out = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", out)
        out = re.sub(r"\*\*(.+?)\*\*",     r"<b>\1</b>",         out)
        out = re.sub(r"\*(.+?)\*",          r"<i>\1</i>",         out)
        out = re.sub(r"`(.+?)`",            r"<tt>\1</tt>",       out)
        return out

    def _flush_table(self):
        """Embed a Gtk.Grid widget for all buffered table rows, then clear the buffer."""
        if not self._table_buffer:
            return
        buf = self._chat_buffer

        # Parse rows: None = separator row, list[str] = data/header cells
        parsed = []
        for line in self._table_buffer:
            stripped = line.strip()
            if self._TABLE_SEP_RE.match(stripped):
                parsed.append(None)
            else:
                parsed.append([c.strip() for c in stripped.strip("|").split("|")])
        self._table_buffer = []

        # Split header (rows before first separator) from body rows
        header_rows, body_rows, sep_seen = [], [], False
        for row in parsed:
            if row is None:
                sep_seen = True
            elif sep_seen:
                body_rows.append(row)
            else:
                header_rows.append(row)
        if not sep_seen:
            body_rows = header_rows
            header_rows = []

        # Apply CSS (idempotent — GTK deduplicates by provider object)
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(self._TABLE_CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        grid = Gtk.Grid()
        grid.set_row_spacing(1)
        grid.set_column_spacing(1)
        grid.get_style_context().add_class("ga-table")

        gtk_row = 0
        for row in header_rows:
            for col, cell in enumerate(row):
                lbl = Gtk.Label()
                lbl.set_markup(self._md_to_pango(cell))
                lbl.set_halign(Gtk.Align.START)
                lbl.set_hexpand(True)
                lbl.get_style_context().add_class("ga-table-header")
                grid.attach(lbl, col, gtk_row, 1, 1)
            gtk_row += 1

        for row in body_rows:
            for col, cell in enumerate(row):
                lbl = Gtk.Label()
                lbl.set_markup(self._md_to_pango(cell))
                lbl.set_halign(Gtk.Align.START)
                lbl.set_hexpand(True)
                lbl.get_style_context().add_class("ga-table-cell")
                grid.attach(lbl, col, gtk_row, 1, 1)
            gtk_row += 1

        grid.show_all()

        end = buf.get_end_iter()
        buf.insert(end, "\n")
        end = buf.get_end_iter()
        anchor = buf.create_child_anchor(end)
        self._chat_view.add_child_at_anchor(grid, anchor)
        end = buf.get_end_iter()
        buf.insert(end, "\n")

    def _insert_markdown_line(self, line: str):
        """
        Insert one completed line (no trailing newline) into the buffer
        with appropriate markdown formatting.  Updates self._in_code_block.
        Always appends a trailing newline.
        """
        buf = self._chat_buffer

        # Code fence toggle
        if line.startswith("```"):
            self._in_code_block = not self._in_code_block
            if not self._in_code_block:
                # closing fence — insert a blank line for spacing
                end = buf.get_end_iter()
                buf.insert(end, "\n")
            return

        if self._in_code_block:
            end = buf.get_end_iter()
            buf.insert_with_tags_by_name(end, line + "\n", "md_code_block")
            return

        # Table row — buffer until table ends so we can compute column widths
        if line.startswith("|"):
            self._table_buffer.append(line)
            return

        # Non-table line: flush any buffered table first
        self._flush_table()

        # Headers
        if line.startswith("### "):
            self._insert_inline(line[4:] + "\n", "md_h3")
        elif line.startswith("## "):
            self._insert_inline(line[3:] + "\n", "md_h2")
        elif line.startswith("# "):
            self._insert_inline(line[2:] + "\n", "md_h1")
        # Horizontal rule (only outside bullets/headers)
        elif line.strip() in ("---", "***", "___"):
            end = buf.get_end_iter()
            buf.insert_with_tags_by_name(end, "─" * 28 + "\n", "assistant_body")
        # Bullet list
        elif re.match(r"^[-*] ", line):
            end = buf.get_end_iter()
            buf.insert_with_tags_by_name(end, "  • ", "md_bullet")
            self._insert_inline(line[2:] + "\n", "md_bullet")
        # Numbered list
        elif re.match(r"^\d+\. ", line):
            m = re.match(r"^(\d+\.) (.+)$", line)
            if m:
                end = buf.get_end_iter()
                buf.insert_with_tags_by_name(end, "  " + m.group(1) + " ", "md_bullet")
                self._insert_inline(m.group(2) + "\n", "md_bullet")
            else:
                self._insert_inline(line + "\n", "assistant_body")
        # Normal paragraph line
        else:
            self._insert_inline(line + "\n", "assistant_body")

    # ------------------------------------------------------------------
    # Line-by-line streaming helpers (GTK main thread)
    # ------------------------------------------------------------------

    def _process_chunk(self, text: str):
        """
        Called on the GTK main thread via GLib.idle_add.

        Splits incoming text at newlines.  Each complete line is committed
        (formatted and written permanently); the trailing partial line is
        shown as plain text and will be replaced when the next chunk arrives.
        """
        combined = self._line_buffer + text
        parts = combined.split("\n")

        # Every part except the last is a complete line
        for part in parts[:-1]:
            self._line_buffer = part
            self._commit_line()

        # The last part is the new (possibly empty) partial line
        self._line_buffer = parts[-1]
        self._refresh_partial()
        self._scroll_to_end()
        return False

    def _commit_line(self):
        """
        Delete the current partial-line placeholder from the buffer,
        insert the formatted line (with trailing newline), and advance
        _line_start_mark to the new end.
        """
        buf = self._chat_buffer
        start_iter = buf.get_iter_at_mark(self._line_start_mark)
        end_iter = buf.get_end_iter()
        if start_iter.compare(end_iter) < 0:
            buf.delete(start_iter, end_iter)
        self._insert_markdown_line(self._line_buffer)
        buf.move_mark(self._line_start_mark, buf.get_end_iter())
        self._line_buffer = ""

    def _refresh_partial(self):
        """
        Replace the partial-line region with the current _line_buffer
        as plain (unformatted) text, ready to be committed when the
        next newline arrives.
        """
        buf = self._chat_buffer
        start_iter = buf.get_iter_at_mark(self._line_start_mark)
        end_iter = buf.get_end_iter()
        if start_iter.compare(end_iter) < 0:
            buf.delete(start_iter, end_iter)
        if self._line_buffer:
            end_iter = buf.get_end_iter()
            buf.insert_with_tags_by_name(end_iter, self._line_buffer, "assistant_body")

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def _on_key_press(self, widget, event):
        from gi.repository import Gdk
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if event.state & Gdk.ModifierType.SHIFT_MASK:
                return False  # Shift+Enter → newline
            self._submit_message()
            return True
        return False

    def _on_send_clicked(self, button):
        self._submit_message()

    def _on_clear_clicked(self, button):
        self._messages.clear()
        self._thread_id = str(uuid.uuid4())
        self._current_context = ""
        self._link_tags.clear()
        self._chat_buffer.set_text("")
        self._show_welcome()
        self._update_context_label()

    # ------------------------------------------------------------------
    # Message submission
    # ------------------------------------------------------------------

    def _submit_message(self):
        if self._streaming:
            return

        if not _cfg.get("backend.model"):
            self._append_text(
                _("\nNo model configured. Please click the Settings button "
                  "to choose a backend and model before chatting.\n"),
                "assistant_body",
            )
            return

        text = self._input_buffer.get_text(
            self._input_buffer.get_start_iter(),
            self._input_buffer.get_end_iter(),
            False,
        ).strip()
        if not text:
            return

        # Clear input
        self._input_buffer.set_text("")

        # Display user turn
        self._append_text("\nYou: ", "user_label")
        self._append_text(text + "\n", "user_body")

        # Build message list for this turn
        user_msg = {"role": "user", "content": text}
        send_messages = self._build_context_messages() + self._messages + [user_msg]

        # Persist user message in history
        self._messages.append(user_msg)

        # Show assistant label; streaming tokens land on the next line
        self._append_text("\n" + _("Gramps Assistant:") + "\n", "assistant_label")

        # Initialise per-turn streaming state
        self._full_response = ""
        self._line_buffer = ""
        self._in_code_block = False
        end_iter = self._chat_buffer.get_end_iter()
        self._line_start_mark = self._chat_buffer.create_mark(
            None, end_iter, left_gravity=True
        )

        # Disable input while streaming
        self._streaming = True
        self._cancelled = False
        self._send_btn.set_sensitive(False)
        self._input_view.set_sensitive(False)

        # Start streaming in background
        tools_schema = self._select_tools(text)
        self._backend.stream_chat(
            messages=send_messages,
            tools=tools_schema,
            on_chunk=self._on_stream_chunk,
            on_tool_call=self._on_tool_call,
            on_done=self._on_stream_done,
            on_error=self._on_stream_error,
            thread_id=self._thread_id,
        )

    def _build_context_messages(self):
        """Return system message list with optional active-person context."""
        system_prompt = _cfg.get("chat.system_prompt")
        if _cfg.get("chat.include_context") and self._current_context:
            system_prompt += f"\n\nCurrent context: {self._current_context}"
        if system_prompt:
            return [{"role": "system", "content": system_prompt}]
        return []

    # ------------------------------------------------------------------
    # Streaming callbacks (called from background thread)
    # ------------------------------------------------------------------

    def _on_stream_chunk(self, text: str):
        if not self._cancelled:
            self._full_response += text
            GLib.idle_add(self._process_chunk, text)

    def _on_tool_call(self, name: str, args: dict, result_callback):
        """
        Marshal tool execution to the GTK main thread.

        The background thread is already blocking on a threading.Event;
        this method simply schedules the execution and returns immediately.
        """
        GLib.idle_add(self._execute_tool_on_main, name, args, result_callback)

    def _on_stream_done(self):
        GLib.idle_add(self._finish_stream)

    def _on_stream_error(self, exc: Exception):
        GLib.idle_add(self._show_error, str(exc))

    # ------------------------------------------------------------------
    # GTK-thread streaming helpers
    # ------------------------------------------------------------------

    def _on_chat_button_press(self, widget, event):
        """Open URLs when the user clicks on a link in the chat view."""
        if event.button != 1:
            return False
        x, y = self._chat_view.window_to_buffer_coords(
            Gtk.TextWindowType.WIDGET, int(event.x), int(event.y)
        )
        result = self._chat_view.get_iter_at_location(x, y)
        it = result[1] if isinstance(result, tuple) else result
        if it is None:
            return False
        for tag in it.get_tags():
            url = self._link_tags.get(tag.get_property("name"))
            if url:
                from gi.repository import Gio
                try:
                    Gio.AppInfo.launch_default_for_uri(url, None)
                except Exception:
                    pass
                return True
        return False

    def _execute_tool_on_main(self, name: str, args: dict, result_callback):
        """Run on GTK main thread (scheduled via GLib.idle_add)."""
        args_display = ", ".join(f"{k}={v!r}" for k, v in args.items())
        self._append_text(f"\n[Tool: {name}({args_display})]\n", "tool_call")

        try:
            result = call_tool(name, args)
            result_str = str(result)
        except Exception as exc:
            result_str = f"Error calling {name}: {exc}"

        # Display truncated result in chat
        display = result_str if len(result_str) <= 500 else result_str[:497] + "..."
        self._append_text(f"[Result: {display}]\n", "tool_result")

        # Resume background thread with the full result.
        # Use PRIORITY_LOW so any UI updates queued by the tool (e.g. set_active
        # scheduling its own idle callbacks) have a chance to run first.
        GLib.idle_add(result_callback, result_str, priority=GLib.PRIORITY_LOW)
        return False  # remove idle source

    def _finish_stream(self):
        # Commit any remaining partial line
        if self._line_buffer:
            self._commit_line()
        # Flush any table that ended at the very end of the response
        self._flush_table()
        # Clean up the line-start mark
        if self._line_start_mark:
            self._chat_buffer.delete_mark(self._line_start_mark)
            self._line_start_mark = None
        self._append_text("\n", None)
        # Persist the assistant turn in history
        if self._full_response:
            self._messages.append(
                {"role": "assistant", "content": self._full_response}
            )
        self._full_response = ""
        self._streaming = False
        self._send_btn.set_sensitive(True)
        self._input_view.set_sensitive(True)
        self._input_view.grab_focus()
        self._update_context_label()
        return False

    def _show_error(self, msg: str):
        if self._line_start_mark:
            self._chat_buffer.delete_mark(self._line_start_mark)
            self._line_start_mark = None
        self._line_buffer = ""
        self._append_text(f"\n[Error: {msg}]\n", "error")
        self._full_response = ""
        self._streaming = False
        self._send_btn.set_sensitive(True)
        self._input_view.set_sensitive(True)
        self._input_view.grab_focus()
        return False

    # ------------------------------------------------------------------
    # Context tracking
    # ------------------------------------------------------------------

    def _connect_history_signals(self):
        """Connect to the Person history so context updates on navigation."""
        try:
            history = self.uistate.get_history("Person")
            if history:
                history.connect("active-changed", self._on_active_person_changed)
        except Exception:
            pass

    def _on_active_person_changed(self, handle):
        self._update_context()
        self._update_context_label()

    def _update_context(self):
        if not _cfg.get("chat.include_context"):
            self._current_context = ""
            return
        if not self.dbstate.is_open():
            self._current_context = ""
            return
        try:
            handle = self.uistate.get_active("Person")
            if handle:
                person = self.dbstate.db.get_person_from_handle(handle)
                from gramps.gen.display.name import displayer as name_displayer

                name = name_displayer.display(person)
                gid = person.get_gramps_id()
                self._current_context = f"Active person: {name} (ID: {gid})"
            else:
                self._current_context = ""
        except Exception:
            self._current_context = ""

    # ------------------------------------------------------------------
    # Tool selection
    # ------------------------------------------------------------------

    _TOOL_KEYWORDS = {
        "people":       ["person", "people", "who", "name", "birth", "death",
                         "individual", "ancestor", "descendant", "relative"],
        "families":     ["family", "families", "father", "mother", "child",
                         "children", "spouse", "married", "marriage", "husband",
                         "wife", "parent", "sibling", "brother", "sister"],
        "events":       ["event", "events", "when", "date", "census", "baptism",
                         "burial", "immigration", "graduation", "occupation"],
        "places":       ["place", "places", "where", "location", "city", "town",
                         "county", "country", "state", "village", "address"],
        "sources":      ["source", "sources", "citation", "citations", "record",
                         "document", "reference", "archive", "book", "page"],
        "media":        ["photo", "photograph", "image", "picture", "media",
                         "file", "scan", "document", "attachment"],
        "repositories": ["repository", "repositories", "archive", "library",
                         "collection", "institution", "museum"],
        "notes":        ["note", "notes", "text", "comment", "annotation",
                         "memo", "description"],
    }

    _CATEGORY_TO_TAG = {
        "People":       "people",
        "Families":     "families",
        "Events":       "events",
        "Places":       "places",
        "Sources":      "sources",
        "Citations":    "sources",
        "Media":        "media",
        "Repositories": "repositories",
        "Notes":        "notes",
    }

    def _current_view_tag(self) -> str | None:
        """Return the tool tag for the currently active Gramps view, or None."""
        try:
            active = self.uistate.viewmanager.active_page
            if active and hasattr(active, "category"):
                return self._CATEGORY_TO_TAG.get(active.category[1])
        except Exception:
            pass
        return None

    def _select_tools(self, current_message: str) -> list:
        """
        Return a filtered tools schema based on keywords in the current
        message and recent conversation history.

        When 'Simplify tools' is off, all tools are returned unchanged.
        When on, scans the last 4 messages plus the current message for
        keywords and returns only matching tools (plus always-on tools).
        Falls back to the current Gramps view's tool set if no keywords match.
        """
        if not _cfg.get("chat.simplify_tools"):
            return get_tools_schema(_cfg.get("backend.type")) if tool_registry else []

        # Build search text from current message + recent history
        search_text = current_message.lower()
        for msg in self._messages[-4:]:
            content = msg.get("content")
            if isinstance(content, str):
                search_text += " " + content.lower()

        active_tags = set()
        for tag, keywords in self._TOOL_KEYWORDS.items():
            if any(kw in search_text for kw in keywords):
                active_tags.add(tag)

        # If nothing matched, fall back to the current view's tag
        if not active_tags:
            view_tag = self._current_view_tag()
            if view_tag:
                active_tags.add(view_tag)

        return get_tools_schema(_cfg.get("backend.type"), tags=active_tags) if tool_registry else []

    # ------------------------------------------------------------------
    # Backend factory
    # ------------------------------------------------------------------

    def _make_backend(self):
        btype = _cfg.get("backend.type")
        url = _cfg.get("backend.url")
        model = _cfg.get("backend.model")
        api_key = _cfg.get("backend.api_key")
        if btype == "anthropic":
            return AnthropicBackend(base_url=url, model=model, api_key=api_key)
        return OpenAICompatibleBackend(base_url=url, model=model, api_key=api_key)

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    # Preset list: (label, backend_type, base_url, model)
    # backend_type=None flags the Custom entry.
    _PRESETS = [
        # ── Ollama (local) ─────────────────────────────────────────────
        ("Ollama – llama3.3",        "openai", "http://localhost:11434", "llama3.3"),
        ("Ollama – llama3.2",        "openai", "http://localhost:11434", "llama3.2"),
        ("Ollama – llama3.1",        "openai", "http://localhost:11434", "llama3.1"),
        ("Ollama – mistral",         "openai", "http://localhost:11434", "mistral"),
        ("Ollama – mixtral",         "openai", "http://localhost:11434", "mixtral"),
        ("Ollama – phi4",            "openai", "http://localhost:11434", "phi4"),
        ("Ollama – gemma3",          "openai", "http://localhost:11434", "gemma3"),
        ("Ollama – qwen2.5",         "openai", "http://localhost:11434", "qwen2.5"),
        ("Ollama – deepseek-r1",     "openai", "http://localhost:11434", "deepseek-r1"),
        ("Ollama – deepseek-v3",     "openai", "http://localhost:11434", "deepseek-v3"),
        ("Ollama – command-r",       "openai", "http://localhost:11434", "command-r"),
        ("Ollama – codellama",       "openai", "http://localhost:11434", "codellama"),
        # ── Other local servers ────────────────────────────────────────
        ("LM Studio",                "openai", "http://localhost:1234",  "local-model"),
        ("llama.cpp server",         "openai", "http://localhost:8080",  ""),
        # ── OpenAI ────────────────────────────────────────────────────
        ("OpenAI – gpt-5",           "openai", "https://api.openai.com", "gpt-5"),
        ("OpenAI – gpt-4.1",         "openai", "https://api.openai.com", "gpt-4.1"),
        ("OpenAI – gpt-4.1-mini",    "openai", "https://api.openai.com", "gpt-4.1-mini"),
        ("OpenAI – gpt-4.1-nano",    "openai", "https://api.openai.com", "gpt-4.1-nano"),
        ("OpenAI – gpt-4o",          "openai", "https://api.openai.com", "gpt-4o"),
        ("OpenAI – gpt-4o-mini",     "openai", "https://api.openai.com", "gpt-4o-mini"),
        ("OpenAI – o3",              "openai", "https://api.openai.com", "o3"),
        ("OpenAI – o3-mini",         "openai", "https://api.openai.com", "o3-mini"),
        ("OpenAI – o1",              "openai", "https://api.openai.com", "o1"),
        ("OpenAI – o1-mini",         "openai", "https://api.openai.com", "o1-mini"),
        # ── Anthropic ─────────────────────────────────────────────────
        ("Anthropic – claude-opus-4-5",          "anthropic", "https://api.anthropic.com", "claude-opus-4-5"),
        ("Anthropic – claude-sonnet-4-5",        "anthropic", "https://api.anthropic.com", "claude-sonnet-4-5"),
        ("Anthropic – claude-haiku-4-5",         "anthropic", "https://api.anthropic.com", "claude-haiku-4-5"),
        ("Anthropic – claude-3-5-sonnet",        "anthropic", "https://api.anthropic.com", "claude-3-5-sonnet-20241022"),
        ("Anthropic – claude-3-5-haiku",         "anthropic", "https://api.anthropic.com", "claude-3-5-haiku-20241022"),
        ("Anthropic – claude-3-opus",            "anthropic", "https://api.anthropic.com", "claude-3-opus-20240229"),
        # ── Google Gemini (OpenAI-compatible endpoint) ─────────────────
        ("Gemini – gemini-2.0-flash",  "openai", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash"),
        ("Gemini – gemini-1.5-pro",    "openai", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-1.5-pro"),
        ("Gemini – gemini-1.5-flash",  "openai", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-1.5-flash"),
        # ── Custom ────────────────────────────────────────────────────
        ("Custom",                     None,     None,                    None),
    ]

    def _find_preset_index(self, btype, url, model):
        """Return the index of the matching preset, or the Custom index."""
        for i, (_, t, u, m) in enumerate(self._PRESETS):
            if t is not None and t == btype and u == url and m == model:
                return i
        return len(self._PRESETS) - 1  # Custom

    def _on_settings_clicked(self, button):
        parent = self.top.get_toplevel()
        if not isinstance(parent, Gtk.Window):
            parent = None

        dialog = Gtk.Dialog(
            title="Gramps Assist Settings",
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("_Save", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.set_default_size(460, -1)

        content = dialog.get_content_area()
        content.set_spacing(6)
        content.set_border_width(12)

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(8)
        content.add(grid)

        row = [0]

        def add_row(label_text, widget, grid_ref=grid):
            lbl = Gtk.Label(label=label_text, xalign=1.0)
            grid_ref.attach(lbl, 0, row[0], 1, 1)
            grid_ref.attach(widget, 1, row[0], 1, 1)
            widget.set_hexpand(True)
            row[0] += 1
            return lbl

        # ── Model preset dropdown ───────────────────────────────────────
        preset_combo = Gtk.ComboBoxText()
        for label, *_ in self._PRESETS:
            preset_combo.append_text(label)
        cur_idx = self._find_preset_index(
            _cfg.get("backend.type"),
            _cfg.get("backend.url"),
            _cfg.get("backend.model"),
        )
        preset_combo.set_active(cur_idx)
        add_row("Model:", preset_combo)

        # ── API key (always visible) ────────────────────────────────────
        apikey_entry = Gtk.Entry()
        apikey_entry.set_text(_cfg.get("backend.api_key"))
        apikey_entry.set_visibility(False)
        apikey_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        add_row("API Key:", apikey_entry)

        # ── Custom fields (shown only when Custom is selected) ──────────
        custom_lbl_type = Gtk.Label(label="Backend:", xalign=1.0)
        type_combo = Gtk.ComboBoxText()
        type_combo.append("openai", "OpenAI-compatible (Ollama, llama.cpp, LM Studio, OpenAI)")
        type_combo.append("anthropic", "Anthropic")
        type_combo.set_active_id(_cfg.get("backend.type"))
        type_combo.set_hexpand(True)
        grid.attach(custom_lbl_type, 0, row[0], 1, 1)
        grid.attach(type_combo, 1, row[0], 1, 1)
        row[0] += 1

        url_entry = Gtk.Entry()
        url_entry.set_text(_cfg.get("backend.url"))
        custom_lbl_url = add_row("Base URL:", url_entry)

        model_entry = Gtk.Entry()
        model_entry.set_text(_cfg.get("backend.model"))
        custom_lbl_model = add_row("Model name:", model_entry)

        custom_widgets = [
            custom_lbl_type, type_combo,
            custom_lbl_url, url_entry,
            custom_lbl_model, model_entry,
        ]

        def _update_custom_visibility():
            is_custom = self._PRESETS[preset_combo.get_active()][1] is None
            for w in custom_widgets:
                w.set_visible(is_custom)

        def _on_preset_changed(combo):
            idx = combo.get_active()
            if idx < 0:
                return
            _, btype, url, model = self._PRESETS[idx]
            if btype is not None:
                type_combo.set_active_id(btype)
                url_entry.set_text(url)
                model_entry.set_text(model)
            _update_custom_visibility()

        preset_combo.connect("changed", _on_preset_changed)

        # ── System prompt ───────────────────────────────────────────────
        sys_label = Gtk.Label(label="System Prompt:", xalign=1.0, yalign=0.0)
        grid.attach(sys_label, 0, row[0], 1, 1)
        sys_scroll = Gtk.ScrolledWindow()
        sys_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sys_scroll.set_min_content_height(240)
        sys_scroll.set_hexpand(True)
        sys_text = Gtk.TextView()
        sys_text.set_wrap_mode(Gtk.WrapMode.WORD)
        sys_text.get_buffer().set_text(_cfg.get("chat.system_prompt"))
        sys_scroll.add(sys_text)
        grid.attach(sys_scroll, 1, row[0], 1, 1)
        row[0] += 1

        # ── Simplify tools checkbox ─────────────────────────────────────
        simplify_check = Gtk.CheckButton(
            label=_("Simplify tools (recommended for smaller/local models)")
        )
        simplify_check.set_active(_cfg.get("chat.simplify_tools"))
        simplify_check.set_tooltip_text(
            _("When enabled, only the tools relevant to your question are sent "
              "to the model. This improves performance with smaller local models.")
        )
        grid.attach(simplify_check, 1, row[0], 1, 1)
        row[0] += 1

        dialog.show_all()
        _update_custom_visibility()  # hide custom rows if not needed

        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            _cfg.set("backend.type", type_combo.get_active_id() or "openai")
            _cfg.set("backend.url", url_entry.get_text().strip())
            _cfg.set("backend.model", model_entry.get_text().strip())
            _cfg.set("backend.api_key", apikey_entry.get_text())
            sys_buf = sys_text.get_buffer()
            sys_prompt = sys_buf.get_text(
                sys_buf.get_start_iter(), sys_buf.get_end_iter(), False
            )
            _cfg.set("chat.system_prompt", sys_prompt)
            _cfg.set("chat.simplify_tools", simplify_check.get_active())
            _cfg.save()
            self._update_context_label()

            self._backend = self._make_backend()

        dialog.destroy()
