"""
Multi-Agent Order Confirmation Process System
Integrated with Autogen Framework

Agents:
1. ATP Checker - Validates inventory and capacity
2. Delivery Scheduler - Aligns with carrier calendars and customer windows
3. Split Shipment - Applies business rules for partial shipments
4. Confirm Composer - Generates confirmation payload
5. Channel Dispatcher - Sends confirmations via appropriate channels
6. Audit Logger - Captures immutable logs for compliance

Flow: ATP -> Scheduler -> Split -> Composer -> Dispatcher -> Audit
"""

import pandas as pd
from datetime import date, datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
import json
import random
import os

# Autogen imports with fallback
AUTOGEN_AVAILABLE = False
try:
    from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
    AUTOGEN_AVAILABLE = True
except ImportError:
    try:
        import autogen
        AssistantAgent = autogen.AssistantAgent
        UserProxyAgent = autogen.UserProxyAgent
        AUTOGEN_AVAILABLE = True
    except ImportError:
        pass


# =====================================================================
# DATA MODELS
# =====================================================================

@dataclass
class OrderLine:
    order_id: str
    line_id: str
    item: str
    quantity: int
    requested_date: date
    ship_from: str = "WAREHOUSE_01"
    priority: str = "NORMAL"
    customer_id: str = ""
    customer_name: str = ""
    customer_email: str = ""
    customer_delivery_window_start: Optional[str] = None  # e.g., "08:00"
    customer_delivery_window_end: Optional[str] = None    # e.g., "17:00"
    allow_partial: bool = True


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
    messages: List[str] = field(default_factory=list)


@dataclass
class ScheduleResult:
    order_id: str
    line_id: str
    item: str
    quantity: int
    ship_date: date
    delivery_date: date
    carrier: str
    transit_days: int
    meets_customer_window: bool
    messages: List[str] = field(default_factory=list)


@dataclass
class SplitDecision:
    order_id: str
    line_id: str
    item: str
    total_quantity: int
    shipments: List[Dict[str, Any]]  # Each: {quantity, ship_date, delivery_date, carrier}
    split_reason: str
    messages: List[str] = field(default_factory=list)


@dataclass
class Confirmation:
    order_id: str
    customer_id: str
    customer_name: str
    customer_email: str
    confirmation_number: str
    confirmation_date: datetime
    total_lines: int
    total_shipments: int
    shipment_details: List[Dict[str, Any]]
    terms: str
    formatted_email: str
    messages: List[str] = field(default_factory=list)


@dataclass
class DispatchResult:
    confirmation_number: str
    order_id: str
    channel: str  # "EMAIL", "API", "EDI"
    status: str   # "SENT", "FAILED", "RETRY"
    attempt_count: int
    sent_timestamp: Optional[datetime]
    receipt_confirmed: bool
    messages: List[str] = field(default_factory=list)


@dataclass
class AuditLog:
    log_id: str
    timestamp: datetime
    order_id: str
    agent: str
    action: str
    input_data: Dict[str, Any]
    output_data: Dict[str, Any]
    status: str
    duration_ms: float
    messages: List[str] = field(default_factory=list)


# =====================================================================
# CONFIGURATION
# =====================================================================

class SystemConfig:
    # ATP Config
    allow_partial_ship = True
    consider_unconfirmed_pos = False
    default_safety_stock = 10
    default_lead_time_days = 14
    receiving_buffer_days = 1
    
    # Carrier Config
    carriers = ["FedEx", "UPS", "DHL", "USPS"]
    carrier_transit_times = {
        "FedEx": {"MIN": 1, "MAX": 3},
        "UPS": {"MIN": 2, "MAX": 4},
        "DHL": {"MIN": 1, "MAX": 5},
        "USPS": {"MIN": 3, "MAX": 7}
    }
    carrier_blackout_dates = []  # Dates carriers don't operate
    
    # Split Shipment Rules
    max_splits_per_order = 3
    min_split_quantity = 5
    split_cost_threshold = 50.0  # USD
    
    # Channel Config
    channel_preference = {
        "PRIORITY": "API",
        "NORMAL": "EMAIL",
        "LOW": "EDI"
    }
    max_retry_attempts = 3
    
    # Audit Config
    audit_retention_days = 2555  # 7 years
    enable_compliance_reporting = True


# =====================================================================
# AGENT 1: ATP CHECKER
# =====================================================================

class ATPCheckerAgent:
    """Agent 1: Validates inventory and capacity to compute earliest available dates"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
        self.name = "ATP_Checker"
    
    def calculate_atp(
        self,
        order_line: OrderLine,
        inventory: List[InventorySnapshot],
        purchase_orders: List[PurchaseOrder]
    ) -> ATPResult:
        """Calculate ATP for a single order line"""
        
        messages = []
        
        # Find inventory for this item
        inv = next((i for i in inventory if i.item == order_line.item), None)
        
        if not inv:
            messages.append(f"No inventory found for {order_line.item}")
            return ATPResult(
                order_id=order_line.order_id,
                line_id=order_line.line_id,
                item=order_line.item,
                requested_quantity=order_line.quantity,
                requested_date=order_line.requested_date,
                available_quantity=0,
                earliest_available_date=order_line.requested_date + timedelta(days=self.config.default_lead_time_days),
                status="BACKORDER",
                source="FUTURE_PRODUCTION",
                messages=messages
            )
        
        available_stock = max(0, inv.on_hand_qty - inv.safety_stock_qty)
        
        # Check if current stock can fulfill
        if available_stock >= order_line.quantity:
            messages.append(f"Sufficient stock: {available_stock} units available")
            return ATPResult(
                order_id=order_line.order_id,
                line_id=order_line.line_id,
                item=order_line.item,
                requested_quantity=order_line.quantity,
                requested_date=order_line.requested_date,
                available_quantity=order_line.quantity,
                earliest_available_date=order_line.requested_date,
                status="AVAILABLE",
                source="STOCK",
                messages=messages
            )
        
        # Partial fulfillment
        if available_stock > 0 and self.config.allow_partial_ship:
            messages.append(f"Partial stock: {available_stock} of {order_line.quantity} units")
            return ATPResult(
                order_id=order_line.order_id,
                line_id=order_line.line_id,
                item=order_line.item,
                requested_quantity=order_line.quantity,
                requested_date=order_line.requested_date,
                available_quantity=available_stock,
                earliest_available_date=order_line.requested_date,
                status="PARTIAL",
                source="STOCK",
                messages=messages
            )
        
        # Check purchase orders
        relevant_pos = [
            po for po in purchase_orders
            if po.item == order_line.item and po.expected_delivery_date >= order_line.requested_date
        ]
        
        if relevant_pos:
            earliest_po = min(relevant_pos, key=lambda p: p.expected_delivery_date)
            delivery_date = earliest_po.expected_delivery_date + timedelta(days=self.config.receiving_buffer_days)
            messages.append(f"Will be available from PO {earliest_po.po_id} on {delivery_date}")
            
            return ATPResult(
                order_id=order_line.order_id,
                line_id=order_line.line_id,
                item=order_line.item,
                requested_quantity=order_line.quantity,
                requested_date=order_line.requested_date,
                available_quantity=order_line.quantity,
                earliest_available_date=delivery_date,
                status="AVAILABLE",
                source="INBOUND_PO",
                messages=messages
            )
        
        # Backorder
        future_date = order_line.requested_date + timedelta(days=self.config.default_lead_time_days)
        messages.append(f"Backordered - estimated {future_date}")
        return ATPResult(
            order_id=order_line.order_id,
            line_id=order_line.line_id,
            item=order_line.item,
            requested_quantity=order_line.quantity,
            requested_date=order_line.requested_date,
            available_quantity=0,
            earliest_available_date=future_date,
            status="BACKORDER",
            source="FUTURE_PRODUCTION",
            messages=messages
        )
    
    def process_batch(
        self,
        order_lines: List[OrderLine],
        inventory: List[InventorySnapshot],
        purchase_orders: List[PurchaseOrder]
    ) -> List[ATPResult]:
        """Process multiple order lines"""
        return [self.calculate_atp(ol, inventory, purchase_orders) for ol in order_lines]


# =====================================================================
# AGENT 2: DELIVERY SCHEDULER
# =====================================================================

class DeliverySchedulerAgent:
    """Agent 2: Aligns ATP results with carrier calendars and customer windows"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
        self.name = "Delivery_Scheduler"
    
    def schedule_delivery(self, atp_result: ATPResult, order_line: OrderLine) -> ScheduleResult:
        """Schedule delivery based on ATP result and customer requirements"""
        
        messages = []
        
        # Select carrier based on priority
        if order_line.priority == "PRIORITY":
            carrier = "FedEx"
        elif order_line.priority == "NORMAL":
            carrier = random.choice(["UPS", "FedEx"])
        else:
            carrier = random.choice(["USPS", "DHL"])
        
        # Get transit time
        transit_range = self.config.carrier_transit_times[carrier]
        transit_days = random.randint(transit_range["MIN"], transit_range["MAX"])
        
        # Calculate ship date (day before delivery needed)
        ship_date = atp_result.earliest_available_date
        delivery_date = ship_date + timedelta(days=transit_days)
        
        # Check customer delivery window
        meets_window = True
        if order_line.customer_delivery_window_start:
            # In real implementation, would check day of week and time windows
            # For now, assume it meets window if delivery is on weekday
            if delivery_date.weekday() >= 5:  # Weekend
                delivery_date += timedelta(days=(7 - delivery_date.weekday()))
                messages.append(f"Adjusted delivery to weekday: {delivery_date}")
        
        messages.append(f"Scheduled via {carrier}, transit {transit_days} days")
        
        return ScheduleResult(
            order_id=atp_result.order_id,
            line_id=atp_result.line_id,
            item=atp_result.item,
            quantity=atp_result.available_quantity,
            ship_date=ship_date,
            delivery_date=delivery_date,
            carrier=carrier,
            transit_days=transit_days,
            meets_customer_window=meets_window,
            messages=messages
        )
    
    def process_batch(
        self,
        atp_results: List[ATPResult],
        order_lines: List[OrderLine]
    ) -> List[ScheduleResult]:
        """Process batch of ATP results"""
        schedules = []
        for atp in atp_results:
            order_line = next(ol for ol in order_lines if ol.order_id == atp.order_id and ol.line_id == atp.line_id)
            schedules.append(self.schedule_delivery(atp, order_line))
        return schedules


# =====================================================================
# AGENT 3: SPLIT SHIPMENT
# =====================================================================

class SplitShipmentAgent:
    """Agent 3: Determines when partial shipments are required based on business rules"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
        self.name = "Split_Shipment"
    
    def evaluate_split(
        self,
        atp_result: ATPResult,
        schedule: ScheduleResult,
        order_line: OrderLine
    ) -> SplitDecision:
        """Determine if order should be split into multiple shipments"""
        
        messages = []
        shipments = []
        
        # If fully available, no split needed
        if atp_result.status == "AVAILABLE" and atp_result.available_quantity == atp_result.requested_quantity:
            shipments.append({
                "quantity": schedule.quantity,
                "ship_date": schedule.ship_date,
                "delivery_date": schedule.delivery_date,
                "carrier": schedule.carrier,
                "status": "COMPLETE"
            })
            messages.append("No split required - full quantity available")
            
            return SplitDecision(
                order_id=atp_result.order_id,
                line_id=atp_result.line_id,
                item=atp_result.item,
                total_quantity=atp_result.requested_quantity,
                shipments=shipments,
                split_reason="NONE",
                messages=messages
            )
        
        # Partial shipment scenario
        if atp_result.status == "PARTIAL" and order_line.allow_partial:
            remaining = atp_result.requested_quantity - atp_result.available_quantity
            
            # First shipment - available stock
            shipments.append({
                "quantity": atp_result.available_quantity,
                "ship_date": schedule.ship_date,
                "delivery_date": schedule.delivery_date,
                "carrier": schedule.carrier,
                "status": "PARTIAL_1"
            })
            
            # Second shipment - remaining quantity (estimated future date)
            future_ship_date = schedule.ship_date + timedelta(days=self.config.default_lead_time_days)
            future_delivery_date = future_ship_date + timedelta(days=schedule.transit_days)
            
            shipments.append({
                "quantity": remaining,
                "ship_date": future_ship_date,
                "delivery_date": future_delivery_date,
                "carrier": schedule.carrier,
                "status": "PARTIAL_2"
            })
            
            messages.append(f"Split into 2 shipments: {atp_result.available_quantity} + {remaining} units")
            
            return SplitDecision(
                order_id=atp_result.order_id,
                line_id=atp_result.line_id,
                item=atp_result.item,
                total_quantity=atp_result.requested_quantity,
                shipments=shipments,
                split_reason="PARTIAL_AVAILABILITY",
                messages=messages
            )
        
        # Backorder scenario
        if atp_result.status == "BACKORDER":
            shipments.append({
                "quantity": atp_result.requested_quantity,
                "ship_date": atp_result.earliest_available_date,
                "delivery_date": atp_result.earliest_available_date + timedelta(days=schedule.transit_days),
                "carrier": schedule.carrier,
                "status": "BACKORDER"
            })
            messages.append(f"Backordered - single shipment on {atp_result.earliest_available_date}")
            
            return SplitDecision(
                order_id=atp_result.order_id,
                line_id=atp_result.line_id,
                item=atp_result.item,
                total_quantity=atp_result.requested_quantity,
                shipments=shipments,
                split_reason="BACKORDER",
                messages=messages
            )
        
        # Default: single shipment
        shipments.append({
            "quantity": schedule.quantity,
            "ship_date": schedule.ship_date,
            "delivery_date": schedule.delivery_date,
            "carrier": schedule.carrier,
            "status": "COMPLETE"
        })
        
        return SplitDecision(
            order_id=atp_result.order_id,
            line_id=atp_result.line_id,
            item=atp_result.item,
            total_quantity=atp_result.requested_quantity,
            shipments=shipments,
            split_reason="NONE",
            messages=messages
        )
    
    def process_batch(
        self,
        atp_results: List[ATPResult],
        schedules: List[ScheduleResult],
        order_lines: List[OrderLine]
    ) -> List[SplitDecision]:
        """Process batch of schedules"""
        decisions = []
        for i, atp in enumerate(atp_results):
            order_line = next(ol for ol in order_lines if ol.order_id == atp.order_id and ol.line_id == atp.line_id)
            decisions.append(self.evaluate_split(atp, schedules[i], order_line))
        return decisions


# =====================================================================
# AGENT 4: CONFIRM COMPOSER
# =====================================================================

class ConfirmComposerAgent:
    """Agent 4: Generates confirmation payload with promise dates and terms"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
        self.name = "Confirm_Composer"
    
    def compose_confirmation(
        self,
        order_lines: List[OrderLine],
        split_decisions: List[SplitDecision]
    ) -> List[Confirmation]:
        """Generate confirmation documents grouped by order"""
        
        confirmations = []
        
        # Group by order_id
        orders = {}
        for ol in order_lines:
            if ol.order_id not in orders:
                orders[ol.order_id] = []
            orders[ol.order_id].append(ol)
        
        for order_id, lines in orders.items():
            # Get all split decisions for this order
            order_splits = [sd for sd in split_decisions if sd.order_id == order_id]
            
            # Generate confirmation number
            conf_number = f"CNF-{order_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            # Compile shipment details
            shipment_details = []
            total_shipments = 0
            
            for split in order_splits:
                for shipment in split.shipments:
                    shipment_details.append({
                        "line_id": split.line_id,
                        "item": split.item,
                        "quantity": shipment["quantity"],
                        "ship_date": str(shipment["ship_date"]),
                        "delivery_date": str(shipment["delivery_date"]),
                        "carrier": shipment["carrier"],
                        "status": shipment["status"]
                    })
                    total_shipments += 1
            
            # Get customer info from first line
            first_line = lines[0]
            
            # Format email
            email_body = self._format_email(
                order_id,
                conf_number,
                first_line.customer_name,
                shipment_details
            )
            
            confirmations.append(Confirmation(
                order_id=order_id,
                customer_id=first_line.customer_id,
                customer_name=first_line.customer_name,
                customer_email=first_line.customer_email,
                confirmation_number=conf_number,
                confirmation_date=datetime.now(),
                total_lines=len(lines),
                total_shipments=total_shipments,
                shipment_details=shipment_details,
                terms="Net 30 days. Free shipping on orders over $500.",
                formatted_email=email_body,
                messages=[f"Generated confirmation for {len(lines)} lines, {total_shipments} shipments"]
            ))
        
        return confirmations
    
    def _format_email(self, order_id: str, conf_number: str, customer_name: str, shipments: List[Dict]) -> str:
        """Format confirmation email"""
        
        email = f"""
========================================
ORDER CONFIRMATION
========================================

Dear {customer_name},

Thank you for your order!

Order ID: {order_id}
Confirmation Number: {conf_number}
Confirmation Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

SHIPMENT DETAILS:
----------------------------------------
"""
        for i, ship in enumerate(shipments, 1):
            email += f"""
Shipment {i}:
  Item: {ship['item']}
  Quantity: {ship['quantity']} units
  Ship Date: {ship['ship_date']}
  Delivery Date: {ship['delivery_date']}
  Carrier: {ship['carrier']}
  Status: {ship['status']}
"""
        
        email += """
----------------------------------------
TERMS & CONDITIONS:
Payment: Net 30 days
Shipping: Free on orders over $500
Returns: 30-day return policy applies

For questions, contact: support@company.com

Thank you for your business!

========================================
"""
        return email


# =====================================================================
# AGENT 5: CHANNEL DISPATCHER
# =====================================================================

class ChannelDispatcherAgent:
    """Agent 5: Sends confirmations via appropriate channels with retry logic"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
        self.name = "Channel_Dispatcher"
    
    def dispatch_confirmation(self, confirmation: Confirmation, order_line: OrderLine) -> DispatchResult:
        """Send confirmation via appropriate channel"""
        
        messages = []
        
        # Determine channel based on priority
        channel = self.config.channel_preference.get(order_line.priority, "EMAIL")
        
        # Simulate dispatch
        attempt_count = 1
        status = "SENT"
        receipt_confirmed = False
        
        # Simulate success rate (90% success on first try)
        if random.random() < 0.9:
            status = "SENT"
            receipt_confirmed = True
            messages.append(f"Successfully sent via {channel}")
        else:
            # Simulate retry
            if attempt_count < self.config.max_retry_attempts:
                attempt_count += 1
                if random.random() < 0.7:  # 70% success on retry
                    status = "SENT"
                    receipt_confirmed = True
                    messages.append(f"Sent via {channel} on retry {attempt_count}")
                else:
                    status = "RETRY"
                    messages.append(f"Retry scheduled for {channel}")
            else:
                status = "FAILED"
                messages.append(f"Failed after {attempt_count} attempts")
        
        return DispatchResult(
            confirmation_number=confirmation.confirmation_number,
            order_id=confirmation.order_id,
            channel=channel,
            status=status,
            attempt_count=attempt_count,
            sent_timestamp=datetime.now() if status == "SENT" else None,
            receipt_confirmed=receipt_confirmed,
            messages=messages
        )
    
    def process_batch(
        self,
        confirmations: List[Confirmation],
        order_lines: List[OrderLine]
    ) -> List[DispatchResult]:
        """Process batch of confirmations"""
        dispatches = []
        for conf in confirmations:
            # Get any order line from this order for priority info
            order_line = next(ol for ol in order_lines if ol.order_id == conf.order_id)
            dispatches.append(self.dispatch_confirmation(conf, order_line))
        return dispatches


# =====================================================================
# AGENT 6: AUDIT LOGGER
# =====================================================================

class AuditLoggerAgent:
    """Agent 6: Captures immutable logs for compliance and audit trails"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
        self.name = "Audit_Logger"
        self.logs: List[AuditLog] = []
    
    def log_action(
        self,
        order_id: str,
        agent: str,
        action: str,
        input_data: Any,
        output_data: Any,
        status: str,
        duration_ms: float
    ) -> AuditLog:
        """Create audit log entry"""
        
        log_id = f"LOG-{datetime.now().strftime('%Y%m%d%H%M%S%f')}-{len(self.logs)}"
        
        # Convert dataclasses to dicts for JSON serialization
        input_dict = self._serialize(input_data)
        output_dict = self._serialize(output_data)
        
        log = AuditLog(
            log_id=log_id,
            timestamp=datetime.now(),
            order_id=order_id,
            agent=agent,
            action=action,
            input_data=input_dict,
            output_data=output_dict,
            status=status,
            duration_ms=duration_ms,
            messages=[f"Logged {action} by {agent}"]
        )
        
        self.logs.append(log)
        return log
    
    def _serialize(self, obj: Any) -> Dict[str, Any]:
        """Serialize objects to dict"""
        if isinstance(obj, list):
            return [self._serialize(item) for item in obj]
        elif hasattr(obj, '__dict__'):
            result = {}
            for key, value in obj.__dict__.items():
                if isinstance(value, (date, datetime)):
                    result[key] = str(value)
                elif isinstance(value, list):
                    result[key] = self._serialize(value)
                elif hasattr(value, '__dict__'):
                    result[key] = self._serialize(value)
                else:
                    result[key] = value
            return result
        else:
            return str(obj)
    
    def get_audit_trail(self, order_id: Optional[str] = None) -> List[AuditLog]:
        """Retrieve audit logs for an order or all orders"""
        if order_id:
            return [log for log in self.logs if log.order_id == order_id]
        return self.logs
    
    def export_logs(self, filepath: str):
        """Export audit logs to JSON file"""
        logs_data = [self._serialize(log) for log in self.logs]
        with open(filepath, 'w') as f:
            json.dump(logs_data, f, indent=2, default=str)


# =====================================================================
# DATA GENERATION
# =====================================================================

class DataGenerator:
    """Generate sample data for testing"""
    
    @staticmethod
    def generate_customers(count: int = 50) -> List[Dict[str, Any]]:
        """Generate customer data"""
        customers = []
        for i in range(1, count + 1):
            customers.append({
                "customer_id": f"CUST-{i:04d}",
                "customer_name": f"Customer {i}",
                "customer_email": f"customer{i}@example.com",
                "delivery_window_start": random.choice(["08:00", "09:00", "10:00"]),
                "delivery_window_end": random.choice(["16:00", "17:00", "18:00"]),
                "allow_partial": random.choice([True, True, True, False])  # 75% allow partial
            })
        return customers
    
    @staticmethod
    def generate_items(count: int = 50) -> List[str]:
        """Generate item codes"""
        categories = ["WIDGET", "GADGET", "DEVICE", "COMPONENT", "MODULE"]
        items = []
        for i in range(1, count + 1):
            category = random.choice(categories)
            items.append(f"{category}-{i:03d}")
        return items
    
    @staticmethod
    def generate_order_lines(customers: List[Dict], items: List[str], count: int = 200) -> List[OrderLine]:
        """Generate order lines"""
        order_lines = []
        orders_per_customer = count // len(customers) + 1
        
        line_counter = 0
        for customer in customers:
            num_orders = random.randint(1, min(5, orders_per_customer))
            for order_num in range(num_orders):
                if line_counter >= count:
                    break
                
                order_id = f"ORD-{line_counter + 1:05d}"
                num_lines = random.randint(1, 3)
                
                for line_num in range(num_lines):
                    if line_counter >= count:
                        break
                    
                    order_lines.append(OrderLine(
                        order_id=order_id,
                        line_id=f"LINE-{line_counter + 1:05d}",
                        item=random.choice(items),
                        quantity=random.randint(5, 100),
                        requested_date=date.today() + timedelta(days=random.randint(1, 30)),
                        ship_from="WAREHOUSE_01",
                        priority=random.choice(["PRIORITY"] * 1 + ["NORMAL"] * 7 + ["LOW"] * 2),
                        customer_id=customer["customer_id"],
                        customer_name=customer["customer_name"],
                        customer_email=customer["customer_email"],
                        customer_delivery_window_start=customer["delivery_window_start"],
                        customer_delivery_window_end=customer["delivery_window_end"],
                        allow_partial=customer["allow_partial"]
                    ))
                    line_counter += 1
        
        return order_lines[:count]
    
    @staticmethod
    def generate_inventory(items: List[str]) -> List[InventorySnapshot]:
        """Generate inventory snapshots"""
        inventory = []
        for item in items:
            inventory.append(InventorySnapshot(
                item=item,
                location="WAREHOUSE_01",
                on_hand_qty=random.randint(20, 200),
                safety_stock_qty=random.randint(5, 20),
                last_updated=datetime.now()
            ))
        return inventory
    
    @staticmethod
    def generate_purchase_orders(items: List[str]) -> List[PurchaseOrder]:
        """Generate purchase orders"""
        pos = []
        # Generate POs for about 30% of items
        po_items = random.sample(items, k=int(len(items) * 0.3))
        
        for i, item in enumerate(po_items, 1):
            pos.append(PurchaseOrder(
                po_id=f"PO-{i:05d}",
                item=item,
                quantity=random.randint(50, 300),
                expected_delivery_date=date.today() + timedelta(days=random.randint(5, 20)),
                location="WAREHOUSE_01",
                confirmed=random.choice([True, True, False])  # 67% confirmed
            ))
        
        return pos


# =====================================================================
# ORCHESTRATOR - Main Process Flow
# =====================================================================

class OrderConfirmationOrchestrator:
    """Orchestrates the full order confirmation process through all 6 agents"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
        
        # Initialize all agents
        self.atp_checker = ATPCheckerAgent(config)
        self.scheduler = DeliverySchedulerAgent(config)
        self.split_agent = SplitShipmentAgent(config)
        self.composer = ConfirmComposerAgent(config)
        self.dispatcher = ChannelDispatcherAgent(config)
        self.auditor = AuditLoggerAgent(config)
    
    def process_orders(
        self,
        order_lines: List[OrderLine],
        inventory: List[InventorySnapshot],
        purchase_orders: List[PurchaseOrder]
    ) -> Dict[str, Any]:
        """Process orders through all 6 agents"""
        
        results = {
            "atp_results": [],
            "schedules": [],
            "split_decisions": [],
            "confirmations": [],
            "dispatches": [],
            "audit_logs": []
        }
        
        print("\n" + "=" * 80)
        print("MULTI-AGENT ORDER CONFIRMATION PROCESS")
        print("=" * 80)
        print(f"\nProcessing {len(order_lines)} order lines...")
        
        # AGENT 1: ATP Checker
        print("\n[AGENT 1: ATP CHECKER]")
        print("-" * 80)
        start_time = datetime.now()
        atp_results = self.atp_checker.process_batch(order_lines, inventory, purchase_orders)
        duration = (datetime.now() - start_time).total_seconds() * 1000
        
        # Log ATP check
        for atp in atp_results:
            self.auditor.log_action(
                atp.order_id, "ATP_Checker", "calculate_atp",
                {"line_id": atp.line_id, "item": atp.item, "quantity": atp.requested_quantity},
                {"status": atp.status, "available_qty": atp.available_quantity},
                "SUCCESS", duration / len(atp_results)
            )
        
        # Print summary
        status_counts = {}
        for atp in atp_results:
            status_counts[atp.status] = status_counts.get(atp.status, 0) + 1
        
        print(f"Processed {len(atp_results)} lines in {duration:.2f}ms")
        print(f"Status breakdown: {status_counts}")
        print(f"Sample: {atp_results[0].item} - {atp_results[0].status} - {atp_results[0].available_quantity}/{atp_results[0].requested_quantity} units")
        
        results["atp_results"] = atp_results
        
        # AGENT 2: Delivery Scheduler
        print("\n[AGENT 2: DELIVERY SCHEDULER]")
        print("-" * 80)
        start_time = datetime.now()
        schedules = self.scheduler.process_batch(atp_results, order_lines)
        duration = (datetime.now() - start_time).total_seconds() * 1000
        
        # Log scheduling
        for schedule in schedules:
            self.auditor.log_action(
                schedule.order_id, "Delivery_Scheduler", "schedule_delivery",
                {"line_id": schedule.line_id, "item": schedule.item},
                {"ship_date": str(schedule.ship_date), "carrier": schedule.carrier},
                "SUCCESS", duration / len(schedules)
            )
        
        carrier_counts = {}
        for sched in schedules:
            carrier_counts[sched.carrier] = carrier_counts.get(sched.carrier, 0) + 1
        
        print(f"Scheduled {len(schedules)} deliveries in {duration:.2f}ms")
        print(f"Carrier breakdown: {carrier_counts}")
        print(f"Sample: {schedules[0].item} via {schedules[0].carrier} - Ship: {schedules[0].ship_date}, Deliver: {schedules[0].delivery_date}")
        
        results["schedules"] = schedules
        
        # AGENT 3: Split Shipment
        print("\n[AGENT 3: SPLIT SHIPMENT ANALYZER]")
        print("-" * 80)
        start_time = datetime.now()
        split_decisions = self.split_agent.process_batch(atp_results, schedules, order_lines)
        duration = (datetime.now() - start_time).total_seconds() * 1000
        
        # Log split decisions
        for decision in split_decisions:
            self.auditor.log_action(
                decision.order_id, "Split_Shipment", "evaluate_split",
                {"line_id": decision.line_id, "total_qty": decision.total_quantity},
                {"split_reason": decision.split_reason, "num_shipments": len(decision.shipments)},
                "SUCCESS", duration / len(split_decisions)
            )
        
        split_counts = {}
        total_shipments = 0
        for dec in split_decisions:
            split_counts[dec.split_reason] = split_counts.get(dec.split_reason, 0) + 1
            total_shipments += len(dec.shipments)
        
        print(f"Analyzed {len(split_decisions)} orders in {duration:.2f}ms")
        print(f"Split breakdown: {split_counts}")
        print(f"Total shipments: {total_shipments} (avg {total_shipments/len(split_decisions):.2f} per order)")
        
        results["split_decisions"] = split_decisions
        
        # AGENT 4: Confirm Composer
        print("\n[AGENT 4: CONFIRMATION COMPOSER]")
        print("-" * 80)
        start_time = datetime.now()
        confirmations = self.composer.compose_confirmation(order_lines, split_decisions)
        duration = (datetime.now() - start_time).total_seconds() * 1000
        
        # Log confirmations
        for conf in confirmations:
            self.auditor.log_action(
                conf.order_id, "Confirm_Composer", "compose_confirmation",
                {"total_lines": conf.total_lines},
                {"confirmation_number": conf.confirmation_number, "total_shipments": conf.total_shipments},
                "SUCCESS", duration / len(confirmations)
            )
        
        print(f"Generated {len(confirmations)} confirmations in {duration:.2f}ms")
        print(f"Total orders: {len(set(ol.order_id for ol in order_lines))}")
        print(f"Sample confirmation: {confirmations[0].confirmation_number} for {confirmations[0].customer_name}")
        
        results["confirmations"] = confirmations
        
        # AGENT 5: Channel Dispatcher
        print("\n[AGENT 5: CHANNEL DISPATCHER]")
        print("-" * 80)
        start_time = datetime.now()
        dispatches = self.dispatcher.process_batch(confirmations, order_lines)
        duration = (datetime.now() - start_time).total_seconds() * 1000
        
        # Log dispatches
        for dispatch in dispatches:
            self.auditor.log_action(
                dispatch.order_id, "Channel_Dispatcher", "dispatch_confirmation",
                {"confirmation_number": dispatch.confirmation_number, "channel": dispatch.channel},
                {"status": dispatch.status, "receipt_confirmed": dispatch.receipt_confirmed},
                dispatch.status, duration / len(dispatches)
            )
        
        dispatch_status = {}
        channel_counts = {}
        for disp in dispatches:
            dispatch_status[disp.status] = dispatch_status.get(disp.status, 0) + 1
            channel_counts[disp.channel] = channel_counts.get(disp.channel, 0) + 1
        
        print(f"Dispatched {len(dispatches)} confirmations in {duration:.2f}ms")
        print(f"Status breakdown: {dispatch_status}")
        print(f"Channel breakdown: {channel_counts}")
        
        results["dispatches"] = dispatches
        
        # AGENT 6: Audit Logger Summary
        print("\n[AGENT 6: AUDIT LOGGER]")
        print("-" * 80)
        audit_logs = self.auditor.get_audit_trail()
        print(f"Total audit entries: {len(audit_logs)}")
        print(f"Agents logged: {len(set(log.agent for log in audit_logs))}")
        print(f"Actions logged: {len(set(log.action for log in audit_logs))}")
        
        results["audit_logs"] = audit_logs
        
        return results
    
    def print_detailed_output(self, results: Dict[str, Any], order_lines: List[OrderLine], limit: int = 10):
        """Print detailed results for first N orders"""
        
        print("\n" + "=" * 80)
        print(f"DETAILED OUTPUT (First {limit} Order Lines)")
        print("=" * 80)
        
        for i in range(min(limit, len(order_lines))):
            ol = order_lines[i]
            atp = results["atp_results"][i]
            sched = results["schedules"][i]
            split = results["split_decisions"][i]
            
            print(f"\n--- Order Line {i+1} ---")
            print(f"Order ID: {ol.order_id} | Line: {ol.line_id}")
            print(f"Customer: {ol.customer_name} ({ol.customer_id})")
            print(f"Item: {ol.item} | Qty: {ol.quantity} | Priority: {ol.priority}")
            print(f"Requested Date: {ol.requested_date}")
            print(f"\nATP Result: {atp.status} | Available: {atp.available_quantity}/{atp.requested_quantity}")
            print(f"Earliest Date: {atp.earliest_available_date} | Source: {atp.source}")
            print(f"\nSchedule: Ship {sched.ship_date} -> Deliver {sched.delivery_date}")
            print(f"Carrier: {sched.carrier} ({sched.transit_days} days)")
            print(f"\nSplit Decision: {split.split_reason}")
            print(f"Shipments: {len(split.shipments)}")
            for j, shipment in enumerate(split.shipments, 1):
                print(f"  Shipment {j}: {shipment['quantity']} units on {shipment['ship_date']} ({shipment['status']})")
        
        # Print sample confirmations
        print("\n" + "=" * 80)
        print("SAMPLE CONFIRMATIONS (First 3)")
        print("=" * 80)
        
        for i, conf in enumerate(results["confirmations"][:3], 1):
            print(f"\n--- Confirmation {i} ---")
            print(conf.formatted_email)


# =====================================================================
# MAIN EXECUTION
# =====================================================================

def main():
    """Main execution function"""
    
    print("=" * 80)
    print("MULTI-AGENT ORDER CONFIRMATION SYSTEM")
    print("Autogen Framework Integration")
    print("=" * 80)
    print(f"\nAutogen Available: {AUTOGEN_AVAILABLE}")
    
    # Initialize configuration
    config = SystemConfig()
    
    # Generate sample data
    print("\nGenerating sample data...")
    customers = DataGenerator.generate_customers(50)
    items = DataGenerator.generate_items(50)
    order_lines = DataGenerator.generate_order_lines(customers, items, 200)
    inventory = DataGenerator.generate_inventory(items)
    purchase_orders = DataGenerator.generate_purchase_orders(items)
    
    print(f"Generated:")
    print(f"  - {len(customers)} customers")
    print(f"  - {len(items)} items")
    print(f"  - {len(order_lines)} order lines")
    print(f"  - {len(inventory)} inventory records")
    print(f"  - {len(purchase_orders)} purchase orders")
    
    # Initialize orchestrator
    orchestrator = OrderConfirmationOrchestrator(config)
    
    # Process orders through all agents
    results = orchestrator.process_orders(order_lines, inventory, purchase_orders)
    
    # Print detailed output
    orchestrator.print_detailed_output(results, order_lines, limit=15)
    
    # Export audit logs
    audit_file = "order_confirmation_audit.json"
    orchestrator.auditor.export_logs(audit_file)
    print(f"\n{'=' * 80}")
    print(f"Audit logs exported to: {audit_file}")
    
    # Summary statistics
    print(f"\n{'=' * 80}")
    print("FINAL SUMMARY")
    print("=" * 80)
    print(f"Total Order Lines Processed: {len(order_lines)}")
    print(f"Unique Orders: {len(set(ol.order_id for ol in order_lines))}")
    print(f"Unique Customers: {len(set(ol.customer_id for ol in order_lines))}")
    print(f"ATP Results: {len(results['atp_results'])}")
    print(f"Schedules Created: {len(results['schedules'])}")
    print(f"Split Decisions: {len(results['split_decisions'])}")
    print(f"Confirmations Generated: {len(results['confirmations'])}")
    print(f"Dispatches Sent: {len(results['dispatches'])}")
    print(f"Audit Logs Created: {len(results['audit_logs'])}")
    
    # Dispatch success rate
    successful = sum(1 for d in results['dispatches'] if d.status == "SENT")
    print(f"\nDispatch Success Rate: {successful}/{len(results['dispatches'])} ({100*successful/len(results['dispatches']):.1f}%)")
    
    print("\n" + "=" * 80)
    print("PROCESS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
