"""Tests for the hook that registers the card-number HMAC key."""

from kedro.io import DataCatalog

from banking_cs.hooks import CardHashKeyHook


def test_key_from_credentials(monkeypatch):
    monkeypatch.setenv("CARD_HASH_KEY", "from-env")
    catalog = DataCatalog()
    CardHashKeyHook().after_catalog_created(
        catalog=catalog, conf_creds={"card_hash_key": {"key": "from-credentials"}}
    )
    assert catalog.load("card_hash_key") == "from-credentials"
    assert "from-credentials" not in str(catalog["card_hash_key"])


def test_key_from_environment_when_credentials_lack_it(monkeypatch):
    monkeypatch.setenv("CARD_HASH_KEY", "from-env")
    catalog = DataCatalog()
    CardHashKeyHook().after_catalog_created(catalog=catalog, conf_creds={})
    assert catalog.load("card_hash_key") == "from-env"


def test_no_key_registers_nothing(monkeypatch):
    monkeypatch.delenv("CARD_HASH_KEY", raising=False)
    catalog = DataCatalog()
    CardHashKeyHook().after_catalog_created(catalog=catalog, conf_creds=None)
    assert "card_hash_key" not in catalog
