from app.connectors.epms_federal import EPMSFederalConnector
from app.connectors.fixture_json import FixtureJsonConnector
from app.connectors.ppra_punjab import PPRAPunjabConnector

ADAPTERS = {
    "ppra_punjab": PPRAPunjabConnector,
    "epms_federal": EPMSFederalConnector,
    "fixture_json": FixtureJsonConnector,
}

ADAPTER_CATALOG = [
    {
        "adapter": "ppra_punjab",
        "label": "PPRA Punjab e-Procurement (HTML listing parser)",
        "fields": ["url", "area"],
        "fixtures": ["listings.html", "documents.json"],
    },
    {
        "adapter": "epms_federal",
        "label": "Federal EPMS / EPADS (notice JSON)",
        "fields": ["url", "area"],
        "fixtures": ["listings.json", "documents.json"],
    },
    {
        "adapter": "fixture_json",
        "label": "Generic JSON portal template (NTDC, WAPDA, utilities)",
        "fields": ["url", "area"],
        "fixtures": ["listings.json", "documents.json"],
    },
]


def get_connector(source):
    cls = ADAPTERS.get(source.adapter)
    if not cls:
        return None
    return cls(source)
