"""Server module registry."""

from __future__ import annotations

from . import email, linear, slack

SERVERS = [slack.register_tools, linear.register_tools, email.register_tools]
