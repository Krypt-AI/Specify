"""Thin Google Sheets REST client (values and batch updates only)."""
from typing import Protocol
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from app.models import Integration
from app.services.google_api import GoogleApiClient
from app.services.google_credentials import IntegrationCredentials

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"


def sheet_range(title: str, cells: str = "") -> str:
    quoted = "'" + title.replace("'", "''") + "'"
    return f"{quoted}!{cells}" if cells else quoted


def column_letter(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


class SheetsApi(Protocol):
    def get_spreadsheet(self, spreadsheet_id: str) -> dict: ...
    def create_spreadsheet(self, title: str, sheets: dict[str, list[str]]) -> dict: ...
    def add_sheet(self, spreadsheet_id: str, title: str) -> int: ...
    def read_values(self, spreadsheet_id: str, title: str) -> list[list]: ...
    def update_values(self, spreadsheet_id: str, data: list[dict]) -> None: ...
    def append_rows(self, spreadsheet_id: str, title: str, rows: list[list]) -> None: ...
    def delete_rows(self, spreadsheet_id: str, sheet_id: int, row_indexes: list[int]) -> None: ...


class SheetsClient(GoogleApiClient):
    service_name = "Google Sheets"

    def __init__(self, credentials: IntegrationCredentials, http: httpx.Client | None = None):
        super().__init__(credentials, SHEETS_API, http)

    def get_spreadsheet(self, spreadsheet_id: str) -> dict:
        fields = "spreadsheetId,spreadsheetUrl,properties.title,sheets.properties(sheetId,title)"
        return self._request("GET", f"/{spreadsheet_id}", params={"fields": fields})

    def create_spreadsheet(self, title: str, sheets: dict[str, list[str]]) -> dict:
        body = {
            "properties": {"title": title},
            "sheets": [
                {
                    "properties": {"title": name, "gridProperties": {"frozenRowCount": 1}},
                    "data": [{"rowData": [{"values": [{"userEnteredValue": {"stringValue": h}} for h in headers]}]}],
                }
                for name, headers in sheets.items()
            ],
        }
        return self._request("POST", "", json=body)

    def add_sheet(self, spreadsheet_id: str, title: str) -> int:
        body = {"requests": [{"addSheet": {"properties": {"title": title, "gridProperties": {"frozenRowCount": 1}}}}]}
        data = self._request("POST", f"/{spreadsheet_id}:batchUpdate", json=body)
        return data["replies"][0]["addSheet"]["properties"]["sheetId"]

    def read_values(self, spreadsheet_id: str, title: str) -> list[list]:
        params = {"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "FORMATTED_STRING"}
        data = self._request("GET", f"/{spreadsheet_id}/values/{quote(sheet_range(title), safe='')}", params=params)
        return data.get("values", [])

    def update_values(self, spreadsheet_id: str, data: list[dict]) -> None:
        if data:
            self._request("POST", f"/{spreadsheet_id}/values:batchUpdate", json={"valueInputOption": "RAW", "data": data})

    def append_rows(self, spreadsheet_id: str, title: str, rows: list[list]) -> None:
        if rows:
            target = quote(sheet_range(title, "A1"), safe="")
            params = {"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"}
            self._request("POST", f"/{spreadsheet_id}/values/{target}:append", params=params, json={"values": rows})

    def delete_rows(self, spreadsheet_id: str, sheet_id: int, row_indexes: list[int]) -> None:
        requests = [
            {"deleteDimension": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": i, "endIndex": i + 1}}}
            for i in sorted(row_indexes, reverse=True)  # bottom-up so earlier indexes stay valid
        ]
        if requests:
            self._request("POST", f"/{spreadsheet_id}:batchUpdate", json={"requests": requests})


def sheets_client_for(db: Session, integration: Integration) -> SheetsClient:
    """Factory used by sync; tests replace it with an in-memory fake."""
    return SheetsClient(IntegrationCredentials(db, integration))
