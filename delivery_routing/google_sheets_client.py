from __future__ import annotations

from datetime import datetime
from typing import Iterable, List

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from .models import DeliveryRequest

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _parse_date(value: str):
    """Parse a date value coming from Sheets.

    Google Sheets may return ISO strings or locale formatted dates; we lean on
    ``datetime.fromisoformat`` first and fall back to ``strptime`` with a few
    common formats.
    """

    if isinstance(value, (datetime, )):
        return value.date()

    for parser in (
        lambda v: datetime.fromisoformat(v).date(),
        lambda v: datetime.strptime(v, "%d/%m/%Y").date(),
        lambda v: datetime.strptime(v, "%m/%d/%Y").date(),
        lambda v: datetime.strptime(v, "%A, %B %d, %Y").date(),
    ):
        try:
            return parser(str(value))
        except (ValueError, TypeError):
            continue
    raise ValueError(f"Unrecognized date value: {value!r}")


def fetch_deliveries_from_sheet(
    spreadsheet_id: str,
    range_name: str,
    service_account_file: str,
    *,
    required_headers: Iterable[str] = ("recipient", "postcode", "desired_date"),
) -> List[DeliveryRequest]:

    credentials = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    service = build("sheets", "v4", credentials=credentials)

    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
    values = result.get("values", [])
    if not values:
        return []

    header = [h.strip().lower() for h in values[0]]
    missing = [field for field in required_headers if field not in header]
    if missing:
        raise KeyError(f"Missing columns in sheet: {', '.join(missing)}")

    deliveries: List[DeliveryRequest] = []

    # iterate with index so we know the sheet row number
    for i, row in enumerate(values[1:], start=2):  # row 2 on sheet = values[1]
        row_map = {header[j]: row[j].strip() if j < len(row) else "" for j in range(len(header))}

        deliveries.append(
            DeliveryRequest(
                recipient=row_map.get("recipient", ""),
                postcode=row_map.get("postcode", ""),
                desired_date=_parse_date(row_map.get("desired_date")),
                notes=row_map.get("notes", "") or None,
                row_number=i,  # <--- attach sheet row number
            )
        )

    return deliveries

