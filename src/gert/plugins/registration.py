"""Plugin registration for EnIF."""

from gert.plugins.enif_update import EnIFUpdate
from gert.plugins.es_update import ESUpdate
from gert.plugins.plugins import gert_plugin
from gert.updates.base import UpdateAlgorithm


@gert_plugin
def gert_update_algorithms() -> list[UpdateAlgorithm]:
    """Register the update algorithm plugins."""
    return [EnIFUpdate(), ESUpdate()]
