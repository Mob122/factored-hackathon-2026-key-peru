"""Project hooks."""

import os

from kedro.framework.hooks import hook_impl
from kedro.io import MemoryDataset


class CardHashKeyHook:
    """Registers the card-number HMAC key as the ``card_hash_key`` dataset.

    The key is read from credentials (``card_hash_key.key`` in
    ``conf/local/credentials.yml``), else from the ``CARD_HASH_KEY`` environment
    variable. It is not a catalog.yml entry on purpose: an entry that names missing
    credentials stops Kedro from building the catalog, for every pipeline, on any
    clone without the key. Without a key only the gold pipeline fails, at its input.
    The key is never logged; ``MemoryDataset`` describes only its type.
    """

    @hook_impl
    def after_catalog_created(self, catalog, conf_creds) -> None:
        credentials = (conf_creds or {}).get("card_hash_key") or {}
        key = credentials.get("key") or os.environ.get("CARD_HASH_KEY")
        if key:
            catalog["card_hash_key"] = MemoryDataset(key)
