"""Compatibility import for the standalone :mod:`csrt_codeswitch` package.

New code should import from ``csrt_codeswitch`` directly. This shim keeps
frozen and historical CSRT experiments working while integrations migrate.
"""

from csrt_codeswitch import *  # noqa: F401,F403
from csrt_codeswitch import __all__
