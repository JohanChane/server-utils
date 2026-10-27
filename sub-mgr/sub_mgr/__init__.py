"""SubMgr - Subscription Manager"""

__version__ = "0.1.0"
__author__ = "SubMgr Developer"

from .core.sub_mgr import (
    SubscriptionConverter,
    load_config_from_toml,
    save_config_to_toml,
)
from .sub_mgr import (
    convert_subscriptions,
    create_subscription,
    install_subscription,
    list_location_links,
    list_subscriptions,
    quick_convert,
)

__all__ = [
    "SubscriptionConverter",
    "__author__",
    "__version__",
    "convert_subscriptions",
    "create_subscription",
    "install_subscription",
    "list_location_links",
    "list_subscriptions",
    "load_config_from_toml",
    "quick_convert",
    "save_config_to_toml",
]
