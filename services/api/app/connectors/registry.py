from app.connectors.epads_federal import EPADSFederalConnector
from app.connectors.epms_federal import EPMSFederalConnector
from app.connectors.fixture_json import FixtureJsonConnector
from app.connectors.ntdc import NTDCConnector
from app.connectors.ppra_punjab import PPRAPunjabConnector
from app.connectors.wapda import WAPDAConnector

ADAPTERS = {
    "ppra_punjab": PPRAPunjabConnector,
    "epms_federal": EPMSFederalConnector,
    "epads_federal": EPADSFederalConnector,
    "ntdc": NTDCConnector,
    "wapda": WAPDAConnector,
    "fixture_json": FixtureJsonConnector,
}

ADAPTER_CATALOG = [
    {
        "adapter": "ppra_punjab",
        "label": "PPRA Punjab Active Procurement (WebForms grid)",
        "fields": ["url", "area"],
        "fixtures": ["listings.html", "documents.json"],
    },
    {
        "adapter": "epms_federal",
        "label": "Federal EPMS active tenders (HTML table)",
        "fields": ["url", "area"],
        "fixtures": ["listings.json", "documents.json"],
    },
    {
        "adapter": "epads_federal",
        "label": "Federal EPADS open opportunities (HTML table)",
        "fields": ["url", "area"],
        "fixtures": ["listings.json", "documents.json"],
    },
    {
        "adapter": "ntdc",
        "label": "NTDC tender notices (public JSON feed)",
        "fields": ["url", "area"],
        "fixtures": ["listings.json", "documents.json"],
    },
    {
        "adapter": "wapda",
        "label": "WAPDA tender notices (WordPress listing)",
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
