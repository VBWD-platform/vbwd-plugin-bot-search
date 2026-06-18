"""bot-search ``handle_action`` — the /search command + tapped-result detail.

Drives the plugin against the CORE ``search_provider_registry`` with an
in-memory fake ``SearchProvider`` (no DB, no app context):

* ``/search foo`` → a ``bot_choices`` reply, one choice per hit, with the
  ``search:view:<entity_type>:<key>`` action_data and an ``entity_label`` hint;
* tapping ``search:view:...`` → a detail reply carrying an "Open page" choice
  whose ``url`` is the public fe route (the navigable choice);
* a disabled entity type is excluded from results;
* a blank query asks for a search term;
* GDPR personal-data types can never be registered, so they can never appear.
"""
import pytest

from vbwd.services.search import SearchHit
from plugins.bot_base.bot_base.types import BotInbound, ChatRef
from plugins.bot_search import BotSearchPlugin


class FakeSearchProvider:
    """An in-memory ``SearchProvider`` over a fixed list of hits."""

    def __init__(self, entity_type, entity_label, hits):
        self.entity_type = entity_type
        self.entity_label = entity_label
        self._hits = hits

    def search(self, query, *, limit=5):
        lowered = query.lower()
        matches = [hit for hit in self._hits if lowered in hit.title.lower()]
        return matches[:limit]

    def get_detail(self, key):
        for hit in self._hits:
            if hit.key == key:
                return hit
        return None


def _inbound(*, command=None, args=None, text=None, action_data=None):
    return BotInbound(
        provider_id="meinchat",
        chat_ref=ChatRef(provider_id="meinchat", chat_id="conversation-1"),
        sender_ref="sender-1",
        text=text,
        command=command,
        args=args or [],
        action_data=action_data,
    )


def _plugin():
    plugin = BotSearchPlugin()
    plugin.initialize()
    return plugin


@pytest.fixture
def shop_provider():
    return FakeSearchProvider(
        entity_type="shop_product",
        entity_label="Shop",
        hits=[
            SearchHit(
                entity_type="shop_product",
                entity_label="Shop",
                key="blue-shirt",
                title="Blue Shirt",
                snippet="A comfy blue shirt.",
                url="/shop/product/blue-shirt",
                price="19.99 EUR",
            )
        ],
    )


def test_search_command_returns_choices_for_hits(clean_search_registry, shop_provider):
    clean_search_registry.register(shop_provider)
    plugin = _plugin()

    reply = plugin.handle_action(_inbound(command="search", args=["Blue"]))

    assert reply.text == 'Found 1 result(s) for "Blue".'
    assert reply.meta == {"kind": "bot_choices", "text": reply.text}
    assert len(reply.choices) == 1
    choice = reply.choices[0]
    assert choice.label == "Blue Shirt"
    assert choice.action_data == "search:view:shop_product:blue-shirt"
    assert choice.hint == "Shop · 19.99 EUR"
    # A result choice does NOT navigate — tapping it dispatches back for detail.
    assert choice.url is None


def test_tapping_a_result_returns_detail_with_open_page_url_choice(
    clean_search_registry, shop_provider
):
    clean_search_registry.register(shop_provider)
    plugin = _plugin()

    reply = plugin.handle_action(
        _inbound(action_data="search:view:shop_product:blue-shirt")
    )

    assert "Blue Shirt" in reply.text
    assert "A comfy blue shirt." in reply.text
    assert "Price: 19.99 EUR" in reply.text
    assert len(reply.choices) == 1
    open_choice = reply.choices[0]
    assert open_choice.label == "Open page"
    assert open_choice.action_data == "search:open:shop_product:blue-shirt"
    assert open_choice.url == "/shop/product/blue-shirt"


def test_view_key_with_colon_is_parsed_intact(clean_search_registry):
    hit = SearchHit(
        entity_type="shop_product",
        entity_label="Shop",
        key="weird:key",
        title="Weird",
        url="/shop/product/weird:key",
    )
    clean_search_registry.register(
        FakeSearchProvider("shop_product", "Shop", [hit])
    )
    plugin = _plugin()

    reply = plugin.handle_action(
        _inbound(action_data="search:view:shop_product:weird:key")
    )

    assert "Weird" in reply.text
    assert reply.choices[0].url == "/shop/product/weird:key"


def test_disabled_entity_type_is_excluded(clean_search_registry, shop_provider):
    clean_search_registry.register(shop_provider)
    plugin = BotSearchPlugin()
    plugin.initialize({"include_shop_product": False})

    reply = plugin.handle_action(_inbound(command="search", args=["Blue"]))

    assert reply.choices == []
    assert 'No results for "Blue"' in reply.text


def test_blank_query_asks_for_a_term(clean_search_registry):
    plugin = _plugin()

    reply = plugin.handle_action(_inbound(command="search", args=[]))

    assert "search for" in reply.text.lower()
    assert reply.choices == []


def test_query_falls_back_to_text_after_slash_search(
    clean_search_registry, shop_provider
):
    clean_search_registry.register(shop_provider)
    plugin = _plugin()

    reply = plugin.handle_action(_inbound(command="search", text="/search Blue"))

    assert reply.text == 'Found 1 result(s) for "Blue".'


def test_tapping_a_missing_result_degrades_gracefully(clean_search_registry):
    plugin = _plugin()

    reply = plugin.handle_action(
        _inbound(action_data="search:view:shop_product:gone")
    )

    assert "no longer available" in reply.text.lower()
    assert reply.choices == []


def test_gdpr_personal_data_types_cannot_be_registered(clean_search_registry):
    bad_provider = FakeSearchProvider("user", "User", [])

    with pytest.raises(ValueError):
        clean_search_registry.register(bad_provider)


def test_total_results_capped(clean_search_registry):
    hits = [
        SearchHit(
            entity_type="shop_product",
            entity_label="Shop",
            key=f"item-{index}",
            title=f"Item {index}",
            url=f"/shop/product/item-{index}",
        )
        for index in range(25)
    ]
    # limit_per_provider is 5, so a single provider already caps at 5 here; add a
    # second provider to exceed the total cap and confirm the slice.
    clean_search_registry.register(
        FakeSearchProvider("shop_product", "Shop", hits)
    )
    clean_search_registry.register(
        FakeSearchProvider("booking_resource", "Booking", hits)
    )
    plugin = _plugin()

    # A wide query matching every item across both providers.
    reply = plugin.handle_action(_inbound(command="search", args=["Item"]))

    assert len(reply.choices) <= 10
