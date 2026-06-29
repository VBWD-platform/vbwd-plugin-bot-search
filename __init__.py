"""bot-search — a ``/search <query>`` catalog-search bot command.

The plugin is a provider-neutral **bot-base consumer**: it structurally
implements ``BotCommandProvider`` (``bot_namespace="search"``) so its
``/search`` command lights up over every bot adapter (meinchat, Telegram) with
no consumer change. ``CommandRegistry`` discovers it among the *enabled* plugins
via ``isinstance(plugin, BotCommandProvider)`` — there is no explicit
"register as a command provider" call; being an enabled plugin that implements
the seam IS the registration (mirrors bot-meinchat-llm).

It reads from the CORE cross-entity ``search_provider_registry`` only — it never
imports a catalog plugin's model. Each catalog plugin (shop / booking / ghrm /
subscription) registers its own ``SearchProvider`` in its ``on_enable``; this
plugin just aggregates whatever is registered, gated by the per-entity admin
toggles. GDPR personal-data entities (user / user_details / invoice) can never
be registered, so they can never appear in a result.
"""
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from flask import current_app

from vbwd.plugins.base import BasePlugin, PluginMetadata

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flask import Blueprint

    from plugins.bot_base.bot_base.types import BotCommand, BotInbound, BotReply


BOT_NAMESPACE = "search"
SEARCH_COMMAND = "search"

# action_data scheme (opaque to bot-base, routed back to handle_action by the
# dispatcher's command/namespace index):
#   search:view:<entity_type>:<key>   — a tapped result → show its detail card
#   search:open:<entity_type>:<key>   — the detail card's "Open page" choice;
#                                        carries a public ``url`` so a rich widget
#                                        navigates instead of dispatching back.
VIEW_ACTION_PREFIX = "search:view:"
OPEN_ACTION_PREFIX = "search:open:"

# Cap the number of result choices so the card list stays readable.
MAX_TOTAL_RESULTS = 10
# Per-provider fan-out cap handed to the registry.
LIMIT_PER_PROVIDER = 5

# Per-entity include toggles (admin checkboxes). The key is
# ``include_<entity_type>`` so the handler can map an entity_type straight to a
# config key. All default true.
INCLUDE_CONFIG_KEYS = (
    "include_shop_product",
    "include_booking_resource",
    "include_ghrm_package",
    "include_subscription_plan",
)

DEFAULT_CONFIG: Dict[str, Any] = {
    "include_shop_product": True,
    "include_booking_resource": True,
    "include_ghrm_package": True,
    "include_subscription_plan": True,
    "debug_mode": False,
}


class BotSearchPlugin(BasePlugin):
    """Catalog-search bot command (a bot-base consumer)."""

    #: The namespace bot-base routes commands / tapped choices to (D1 / D7).
    bot_namespace = BOT_NAMESPACE

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="bot-search",
            version="26.6",
            author="VBWD Team",
            description=(
                "A /search command that finds catalog entities (shop products, "
                "bookable resources, software packages, subscription plans) via "
                "the core cross-entity search registry."
            ),
            # bot-base is the command seam this plugin implements. The catalog
            # plugins are NOT runtime deps — this plugin reads the agnostic core
            # search registry, never a catalog model.
            dependencies=["bot-base"],
        )

    def initialize(self, config: Optional[Dict[str, Any]] = None) -> None:
        merged = {**DEFAULT_CONFIG}
        if config:
            merged.update(config)
        super().initialize(merged)

    def get_blueprint(self) -> Optional["Blueprint"]:
        # No HTTP surface — the command rides the bot bridge only.
        return None

    def get_url_prefix(self) -> Optional[str]:
        return ""

    def on_enable(self) -> None:
        # No repositories of its own and no extra registrations: being an enabled
        # plugin that implements ``BotCommandProvider`` is the whole registration
        # (CommandRegistry discovers it via isinstance over the enabled set).
        pass

    def on_disable(self) -> None:
        pass

    # ── bot-base consumer seam ───────────────────────────────────────────────
    def get_bot_commands(self) -> List["BotCommand"]:
        """The ``/search`` command — only while enabled (Liskov: [] disabled).

        ``CommandRegistry`` collects these from the *enabled* plugin set, so a
        disabled plugin contributes nothing. The neutral ``BotCommand`` DTO is
        imported lazily so this module loads even when bot-base is absent.
        """
        from plugins.bot_base.bot_base.types import BotCommand

        return [
            BotCommand(
                name=SEARCH_COMMAND,
                description="Search the catalog",
                namespace=BOT_NAMESPACE,
            )
        ]

    def handle_action(self, context: "BotInbound") -> "BotReply":
        """Route a search turn: a tapped result → detail card; the ``/search``
        command → a result card list."""
        action_data = getattr(context, "action_data", None)
        command = getattr(context, "command", None)

        if action_data and action_data.startswith(VIEW_ACTION_PREFIX):
            return self._handle_view(action_data)
        if command == SEARCH_COMMAND:
            return self._handle_search(context)

        # An unexpected turn for this namespace — prompt for a term.
        return self._ask_for_term()

    # ── handlers ─────────────────────────────────────────────────────────────
    def _handle_search(self, context: "BotInbound") -> "BotReply":
        from plugins.bot_base.bot_base.types import BotChoice, BotReply
        from vbwd.services.search import search_provider_registry

        query = self._extract_query(context)
        if not query:
            return self._ask_for_term()

        config = self._effective_config()
        enabled = [
            entity_type
            for entity_type in search_provider_registry.entity_types()
            if config.get(f"include_{entity_type}", True)
        ]
        hits = search_provider_registry.search(
            query, entity_types=enabled, limit_per_provider=LIMIT_PER_PROVIDER
        )[:MAX_TOTAL_RESULTS]

        if not hits:
            text = f'No results for "{query}". Try a different term.'
            return BotReply(text=text, meta={"kind": "bot_choices", "text": text})

        text = f'Found {len(hits)} result(s) for "{query}".'
        choices = [
            BotChoice(
                label=hit.title,
                hint=self._result_hint(hit),
                action_data=f"{VIEW_ACTION_PREFIX}{hit.entity_type}:{hit.key}",
            )
            for hit in hits
        ]
        return BotReply(
            text=text,
            choices=choices,
            meta={"kind": "bot_choices", "text": text},
        )

    def _handle_view(self, action_data: str) -> "BotReply":
        from plugins.bot_base.bot_base.types import BotChoice, BotReply
        from vbwd.services.search import search_provider_registry

        # ``search:view:<entity_type>:<key>`` — split into at most 4 parts so a
        # key that itself contains a colon stays intact.
        parts = action_data.split(":", 3)
        if len(parts) < 4:
            return BotReply(text="Sorry, I could not open that result.")
        entity_type, key = parts[2], parts[3]

        provider = search_provider_registry.get(entity_type)
        hit = provider.get_detail(key) if provider is not None else None
        if hit is None:
            return BotReply(
                text="That result is no longer available. Try searching again."
            )

        text = self._detail_text(hit)
        choices: List[BotChoice] = []
        if hit.url:
            choices.append(
                BotChoice(
                    label="Open page",
                    action_data=f"{OPEN_ACTION_PREFIX}{entity_type}:{key}",
                    url=hit.url,
                )
            )
        meta: Dict[str, Any] = {"kind": "bot_choices", "text": text}
        return BotReply(text=text, choices=choices, meta=meta)

    # ── helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def _ask_for_term() -> "BotReply":
        from plugins.bot_base.bot_base.types import BotReply

        return BotReply(
            text="What would you like to search for? Try: /search blue shirt"
        )

    @staticmethod
    def _extract_query(context: "BotInbound") -> str:
        """The query from ``args`` (preferred), else the text after ``/search``."""
        args = getattr(context, "args", None) or []
        if args:
            return " ".join(args).strip()
        text = (getattr(context, "text", None) or "").strip()
        if text.startswith(f"/{SEARCH_COMMAND}"):
            return text[len(SEARCH_COMMAND) + 1 :].strip()
        return text

    @staticmethod
    def _result_hint(hit) -> Optional[str]:
        label = hit.entity_label
        if hit.price:
            return f"{label} · {hit.price}"
        return label

    @staticmethod
    def _detail_text(hit) -> str:
        lines = [hit.title]
        if hit.snippet:
            lines.append("")
            lines.append(hit.snippet)
        if hit.price:
            lines.append("")
            lines.append(f"Price: {hit.price}")
        return "\n".join(lines)

    def _effective_config(self) -> Dict[str, Any]:
        """The merged config: plugin defaults overlaid with the admin-saved
        values (the same ``current_app.config_store.get_config`` pattern other
        bot plugins use) so per-entity checkbox toggles take effect at runtime.
        """
        config = {**DEFAULT_CONFIG, **(self._config or {})}
        try:
            store = getattr(current_app, "config_store", None)
            saved = store.get_config("bot-search") if store is not None else None
        except Exception:  # noqa: BLE001 — no app context / no store ⇒ use defaults
            saved = None
        if isinstance(saved, dict):
            config.update(saved)
        return config
