"""`/start` перечисляет все зарегистрированные команды.

Регрессия: задача 15.6.6 дополнила `/help` и `_BOT_COMMANDS`, но `/start`
остался со старым списком — пользователь не видел `/mode`, `/schedule`,
`/schedules`. См. `_docs/commands.md` § `/start`.
"""

from __future__ import annotations

from app.commands.registry import _START_TEXT, CommandRegistry


def test_start_lists_every_registered_command() -> None:
    commands = set(CommandRegistry().list_commands()) - {"start"}

    missing = [name for name in sorted(commands) if f"/{name}" not in _START_TEXT]
    assert missing == []
