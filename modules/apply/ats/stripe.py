"""
Stripe ATS handler — delegates to Greenhouse.

Stripe's job boards run on Greenhouse. This shim ensures get_handler("stripe")
returns a working apply function without changes to the ATS router.
"""

from modules.apply.ats.greenhouse import apply  # noqa: F401

__all__ = ["apply"]
