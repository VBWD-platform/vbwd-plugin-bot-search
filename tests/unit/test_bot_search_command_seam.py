"""bot-search command seam — it IS a ``BotCommandProvider``.

Being an enabled plugin that structurally implements ``BotCommandProvider`` is
the whole registration: ``CommandRegistry`` discovers it via ``isinstance`` and
its ``/search`` command lands in ``command_index()`` so the dispatcher routes a
``/search`` turn to it (mirrors bot-meinchat-llm).
"""
from plugins.bot_base.bot_base.ports import BotCommandProvider
from plugins.bot_search import BOT_NAMESPACE, SEARCH_COMMAND, BotSearchPlugin


def test_plugin_structurally_implements_bot_command_provider():
    plugin = BotSearchPlugin()
    plugin.initialize()

    assert isinstance(plugin, BotCommandProvider)
    assert plugin.bot_namespace == BOT_NAMESPACE == "search"


def test_get_bot_commands_exposes_the_search_command():
    plugin = BotSearchPlugin()
    plugin.initialize()

    commands = plugin.get_bot_commands()

    assert len(commands) == 1
    command = commands[0]
    assert command.name == SEARCH_COMMAND == "search"
    assert command.description == "Search the catalog"
    assert command.namespace == "search"


def test_command_reaches_the_dispatcher_command_index():
    """The plugin's /search command lands in CommandRegistry.command_index()."""
    from plugins.bot_base.bot_base.services.command_registry import CommandRegistry

    plugin = BotSearchPlugin()
    plugin.initialize()

    class _FakeManager:
        def get_enabled_plugins(self):
            return [plugin]

    registry = CommandRegistry(_FakeManager())

    index = registry.command_index()
    assert index.get("search") is plugin
    assert registry.get_provider_for_namespace("search") is plugin
