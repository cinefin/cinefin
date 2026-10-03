"""Ticket design elements: one model per kind, the single source of what an element can hold.

The API validates designs against these (and they reach the SPA as generated types), the service renders
from them, and they store as their JSON dumps. Sizes are a share (%) of the width an element sits in:
the paper, or its cell in a columns row.
"""

import os
from typing import Annotated, Literal

from ninja import Schema
from pydantic import Field, TypeAdapter, field_validator, model_validator

Align = Literal["left", "center", "right"]
Share = Annotated[int, Field(ge=10, le=100, description="Share (%) of the paper, or of the cell, to fill")]
# A columns row's relative cell widths: 2 or 3 cells.
COLUMN_WIDTHS = ([1, 1], [1, 2], [2, 1], [1, 1, 1], [1, 2, 1])
CELL_ITEMS_MAX = 10


class TextElement(Schema):
    type: Literal["text"] = "text"
    content: str = Field("", max_length=500, description="Text, with {tokens}")
    align: Align = "center"
    size: Literal["normal", "wide", "tall", "large"] = "normal"
    bold: bool = False
    invert: bool = False


class ImageElement(Schema):
    type: Literal["image"] = "image"
    file: str = Field("", max_length=200, description="A ticket-library image")
    width: Share | None = Field(None, description="Unset: the image's own size, shrunk only if too wide")
    align: Align = "center"

    @field_validator("file")
    @classmethod
    def _basename(cls, value: str) -> str:
        return os.path.basename(value)  # blocks path traversal on the library filename


class RatingElement(Schema):
    type: Literal["rating"] = "rating"
    width: Share = 25
    align: Align = "center"


class QrElement(Schema):
    type: Literal["qr"] = "qr"
    mode: Literal["fun", "content"] = Field("fun", description="fun: one of the design's surprise links")
    content: str = Field("", max_length=500)
    width: Share = 50
    error: Literal["low", "medium", "quartile", "high"] = "low"
    render: Literal["image", "printer"] = Field("image", description="Drawn here as an image, or by the printer")
    align: Align = "center"


class BarcodeElement(Schema):
    type: Literal["barcode"] = "barcode"
    content: str = Field("", max_length=500)
    symbology: Literal["code128", "code39", "ean13", "ean8", "upca", "itf", "codabar"] = "code128"
    align: Align = "center"


class RuleElement(Schema):
    type: Literal["rule"] = "rule"


class SpacerElement(Schema):
    type: Literal["spacer"] = "spacer"
    lines: int = Field(1, ge=1, le=10)


# What a columns cell can hold: no barcodes (the row is one bitmap) and no nested columns.
CellElement = Annotated[
    TextElement | ImageElement | RatingElement | QrElement | RuleElement | SpacerElement,
    Field(discriminator="type"),
]


class ColumnsElement(Schema):
    type: Literal["columns"] = "columns"
    widths: list[int] = Field(default_factory=lambda: [1, 1], description="Relative cell widths, 2 or 3 cells")
    cells: list[list[CellElement]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self):
        if self.widths not in COLUMN_WIDTHS:
            raise ValueError(f"widths must be one of {list(COLUMN_WIDTHS)}")
        self.cells = [cell[:CELL_ITEMS_MAX] for cell in (self.cells + [[]] * len(self.widths))[: len(self.widths)]]
        return self


Element = Annotated[
    TextElement
    | ImageElement
    | RatingElement
    | QrElement
    | BarcodeElement
    | RuleElement
    | SpacerElement
    | ColumnsElement,
    Field(discriminator="type"),
]
ELEMENTS = TypeAdapter(list[Element])
