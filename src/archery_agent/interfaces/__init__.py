"""Adapters: CLI today, chat/HTTP later.

Interfaces are the thinnest layer in the system on purpose. Anything a CLI needs to *decide*
belongs in the layers below, so that a chat adapter, an HTTP API and a test harness all get the
same behaviour for free.
"""

from __future__ import annotations
