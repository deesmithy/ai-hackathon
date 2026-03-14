"""Example tool — replace with your own business tools."""

from langchain_core.tools import tool


@tool
def lookup_inventory(product_name: str) -> str:
    """Look up current inventory for a product."""
    # TODO: wire up to a real data source
    return f"42 units of '{product_name}' in stock."
