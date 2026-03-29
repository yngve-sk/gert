"""Plugin registration for EnIF."""

from gert.plugins.enif_update import EnIFUpdate
from gert.plugins.plugins import gert_plugin
from gert.updates.base import UpdateAlgorithm


@gert_plugin
def gert_update_algorithms() -> list[UpdateAlgorithm]:
    """Register the EnIF update algorithm plugin."""
    return [EnIFUpdate()]
