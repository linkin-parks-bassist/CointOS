"""Coin's terminal monitor: a retained conversation, live state and compact activity."""
from __future__ import annotations

import time
from collections import deque

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.segment import Segment
from rich.table import Table
from rich.text import Text

INK = '#e9e2d5'
MUTED = '#a3ada6'
ACCENT = '#a8c5a1'


def clean(value) -> str:
    return ''.join(c for c in str(value or '') if c in '\n\t' or ord(c) >= 32 and not 127 <= ord(c) < 160)


def elapsed(seconds) -> str:
    seconds = max(0, int(seconds))
    return f'{seconds}s' if seconds < 60 else f'{seconds // 60}m {seconds % 60:02}s'


class Tail:
    """Keep the newest rendered lines inside the conversation viewport."""
    def __init__(self, renderable, height):
        self.renderable, self.height = renderable, height

    def __rich_console__(self, console, options):
        lines = console.render_lines(self.renderable, options.update(height=None), pad=False)
        for line in lines[-self.height:]:
            yield from line
            yield Segment.line()


class Monitor:
    def __init__(self):
        self.turns = deque(maxlen=4)
        self.identity = None
        self.state = {}
        self.error = None

    def update(self, state):
        if '_error' in state:
            self.error = clean(state['_error'])
            return
        self.state, self.error = state, None
        coin = state.get('coin') or {}
        live = coin.get('live') or {}
        identity = (coin.get('worker_since'), coin.get('turns'))
        if identity != self.identity:
            self.identity = identity
            self.turns.append({'trigger': clean(coin.get('trigger') or coin.get('last_trigger') or 'Conversation'),
                               'reasoning': '', 'content': ''})
        for field in ('reasoning', 'content'):
            if value := live.get(field):
                self.turns[-1][field] = clean(value)[-16000:]

    def render(self, width=100, height=36):
        coin = self.state.get('coin') or {}
        thought = next((t for t in (self.state.get('thoughts') or {}).values() if t.get('agent') == 'coin'), None)
        phase = ('reconnecting' if self.error else 'offline' if coin.get('alive') is False else
                 'reading' if thought and thought.get('reading') else
                 clean((coin.get('live') or {}).get('phase') or 'thinking') if thought else
                 'tools' if coin.get('doing') and coin.get('busy') else 'working' if coin.get('busy') else 'idle')
        header = Table.grid(expand=True)
        header.add_column(ratio=1)
        header.add_column(justify='right')
        header.add_row(Text('◉  Coin', style=f'bold {INK}'), Text(phase.upper(), style=f'bold {ACCENT}'))
        trigger = clean(coin.get('trigger') or coin.get('last_trigger') or 'Ready for your next message')
        header.add_row(Text(trigger, style=INK), Text(clean(coin.get('model')).removesuffix('-GGUF'), style=MUTED))
        facts = [f"{coin.get('turns', 0)} turns"]
        if coin.get('busy') and coin.get('turn_started_at'):
            facts.append('this turn ' + elapsed(time.time() - coin['turn_started_at']))
        if thought:
            facts.append(f"{int(thought.get('generated') or 0):,} tokens")
            if thought.get('rate'):
                facts.append(f"{thought['rate']:.1f} tok/s")
            if thought.get('reading'):
                facts.append(f"context {int(thought.get('read') or 0):,} / {int(thought.get('prompt') or 0):,}")
        header.add_row(Text('  ·  '.join(facts), style=MUTED), Text('LIVE', style=MUTED))
        sections = [Panel(header, box=box.ROUNDED, border_style=ACCENT, padding=(1, 2))]
        body = []
        # The viewport follows the latest conversation while retaining earlier turns in memory.
        available = max(5, height - 17)
        for turn in list(self.turns)[-2:]:
            if turn['content']:
                text = '\n'.join(turn['content'].splitlines()[-available:])
                body.append(Panel(Markdown(text), title=Text('Coin · ' + turn['trigger'], style=ACCENT),
                                  title_align='left', border_style='#67786a', box=box.ROUNDED, padding=(1, 2)))
        current = self.turns[-1] if self.turns else {}
        if current.get('reasoning') and (thought or not current.get('content')):
            lines = current['reasoning'].splitlines()
            reasoning = '\n'.join(lines[-max(2, min(5, available // 3)):])
            body.append(Panel(Text(reasoning, style=MUTED), title=Text('Thinking', style=MUTED),
                              title_align='left', border_style='#56625a', box=box.ROUNDED, padding=(0, 2)))
        if not body:
            body.append(Panel(Text('Reading context…' if phase == 'reading' else 'Ready. Replies and work appear here.',
                                   style=MUTED), border_style='#56625a', padding=(1, 2), box=box.ROUNDED))
        has_tool = coin.get('busy') and coin.get('doing') and not thought
        reserve = 8 + (5 if coin.get('recent') else 0) + (3 if has_tool else 0) + (2 if self.error else 0)
        sections.append(Tail(Group(*body), max(3, height - reserve)))
        if coin.get('busy') and coin.get('doing') and not thought:
            sections.append(Panel(Text(clean(coin.get('doing') or 'Working'), style=INK),
                                  title=Text('Tool', style=ACCENT), title_align='left',
                                  border_style='#657761', padding=(0, 2), box=box.ROUNDED))
        activity = Table.grid(padding=(0, 2))
        activity.add_column(style='#68746c', no_wrap=True)
        activity.add_column(style=MUTED)
        for event in (coin.get('recent') or [])[-3:]:
            when = time.strftime('%H:%M:%S', time.localtime(event.get('at') or time.time()))
            label = clean(event.get('detail') or event.get('trigger') or event.get('event'))
            activity.add_row(when, label)
        if activity.row_count:
            sections.append(Panel(activity, title=Text('Activity', style=MUTED), title_align='left',
                                  border_style='#56625a', box=box.ROUNDED, padding=(0, 1)))
        if self.error:
            sections.append(Text('Reconnecting · ' + self.error, style='#d3ac81'))
        sections.append(Text('  CointOS / Coin  ·  Ctrl+C to close', style='#68746c'))
        return Group(*sections)


def watch(states, stop=None):
    console = Console()
    monitor = Monitor()
    try:
        with Live(console=console, screen=console.is_terminal, auto_refresh=False, vertical_overflow='crop') as live:
            for state in states:
                if stop and stop():
                    return
                monitor.update(state)
                live.update(monitor.render(console.width, console.height), refresh=True)
    except KeyboardInterrupt:
        pass
