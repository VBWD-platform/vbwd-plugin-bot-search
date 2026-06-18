# bot-search

A provider-neutral **`/search <query>` catalog-search bot command**. It lights up
over every bot adapter (meinchat, Telegram, …) with no consumer change, finding
catalog entities — shop products, bookable resources, software packages,
subscription plans — through the agnostic core cross-entity search registry.

## What it does

- **Implements the `BotCommandProvider` seam** (`bot_namespace="search"`). It is
  discovered automatically: `CommandRegistry` collects command providers from the
  *enabled* plugin set via `isinstance(plugin, BotCommandProvider)` — being an
  enabled plugin that implements the seam **is** the registration (mirrors
  `bot-meinchat-llm`). A disabled plugin contributes nothing (Liskov).
- **Reads the core registry only.** It aggregates whatever each catalog plugin
  has registered in `vbwd/services/search` (`search_provider_registry`); it never
  imports a catalog plugin's model. Each catalog plugin (shop / booking / ghrm /
  subscription) registers its own `SearchProvider` in its `on_enable`.
- **GDPR-safe by construction.** Personal-data entities (`user`,
  `user_details`, `invoice`) can never be registered as search providers, so they
  can never appear in a result.
- **Tapped result → detail card.** A `/search` turn returns a result-choice list;
  tapping a result shows its detail card, whose optional **"Open page"** choice
  carries a public `BotChoice.url` so a rich client navigates instead of
  dispatching back.

## Config keys (`config.json` / `admin-config.json`)

| Key | Default | Purpose |
| --- | --- | --- |
| `include_shop_product` | `true` | Include shop products in `/search` results. |
| `include_booking_resource` | `true` | Include bookable resources in `/search` results. |
| `include_ghrm_package` | `true` | Include software packages in `/search` results. |
| `include_subscription_plan` | `true` | Include subscription plans in `/search` results. |
| `debug_mode` | `false` | Verbose server-side debug logging. Disable in production. |

Each `include_<entity_type>` checkbox gates one registered provider at runtime;
the handler maps an `entity_type` straight to its `include_<entity_type>` key.

## How it fits the bot stack

```
bot-base              the transport-neutral bot core (command dispatcher + DTOs)
  ├─ bot-meinchat       a meinchat IMessengerProvider adapter
  ├─ bot-telegram       a Telegram IMessengerProvider adapter
  └─ bot-search         a BotCommandProvider consumer (this plugin — /search)
```

Declared plugin dependencies: `bot-base` (the command seam). The catalog plugins
are **not** runtime dependencies — this plugin reads the agnostic core search
registry, never a catalog model, so it works with whatever subset of
shop/booking/ghrm/subscription happens to be enabled.

## HTTP surface

None — `get_blueprint()` returns `None`. The command rides the bot bridge only.

## Action-data scheme

Routed back to `handle_action` by the dispatcher's command/namespace index
(opaque to bot-base):

- `search:view:<entity_type>:<key>` — a tapped result → show its detail card.
- `search:open:<entity_type>:<key>` — the detail card's "Open page" choice;
  carries a public `url` so a rich widget navigates instead of dispatching back.

## Quality gate

```
cd vbwd-backend && bin/pre-commit-check.sh --plugin bot_search --full
```
