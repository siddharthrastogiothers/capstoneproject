from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, List

@dataclass
class OrderLine:
    order_id: str
    line_id: str
    item: str
    quantity: int
    requested_date: date
    ship_from: Optional[str] = None
    priority: Optional[str] = None

@dataclass
class InventorySnapshot:
    item: str
    location: str
    on_hand_qty: int
    safety_stock_qty: int
    last_updated: datetime

@dataclass
class PurchaseOrder:
    po_id: str
    item: str
    quantity: int
    expected_delivery_date: date
    location: str
    confirmed: bool = False

@dataclass
class ATPResult:
    order_id: str
    line_id: str
    item: str
    requested_quantity: int
    requested_date: date
    available_quantity: int
    earliest_available_date: Optional[date]
    status: str  # "AVAILABLE", "PARTIAL", "BACKORDER"
    source: str  # "STOCK", "INBOUND_PO", "FUTURE_PRODUCTION"
    messages: List[str] = None
    
    def __post_init__(self):
        if self.messages is None:
            self.messages = []

@dataclass
class ATPCheckRequest:
    order_lines: List[OrderLine]
    check_timestamp: datetime = None
    
    def __post_init__(self):
        if self.check_timestamp is None:
            self.check_timestamp = datetime.now()
