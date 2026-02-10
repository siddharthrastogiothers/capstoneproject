# Multi-Agent Order Confirmation Process System

## Overview
A comprehensive order confirmation system built with the Autogen framework, featuring 6 specialized agents that work in sequence to process customer orders from ATP validation through dispatch and audit logging.

## System Architecture

### Architecture Flowchart

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           ORDER CONFIRMATION PROCESS FLOW                                │
│                                   (200 Order Lines)                                      │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              DATA GENERATION LAYER                                       │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────────────┐    │
│  │  200 Order Lines    │  │  50 Inventory       │  │  15 Purchase Orders         │    │
│  │  50 Customers       │  │  Records            │  │  Expected Delivery Dates    │    │
│  │  101 Unique Orders  │  │  Safety Stock Data  │  │  Inbound Material           │    │
│  └─────────────────────┘  └─────────────────────┘  └─────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
╔═════════════════════════════════════════════════════════════════════════════════════════╗
║                         AGENT 1: ATP CHECKER                                            ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Purpose: Validate inventory & capacity, compute earliest available dates               ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Process Flow:                                                                          ║
║    1. Validate Inventory Levels                                                         ║
║    2. Check Safety Stock Requirements                                                   ║
║    3. Evaluate Purchase Orders (Inbound)                                                ║
║    4. Calculate Earliest Available Date                                                 ║
║    5. Determine Status: AVAILABLE / PARTIAL / BACKORDER                                 ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Output: ATP Results (200 Lines)                                                        ║
║    ✓ 147 AVAILABLE (73.5%)  |  ⚠ 47 PARTIAL (23.5%)  |  ✗ 6 BACKORDER (3.0%)         ║
║    Source: STOCK / INBOUND_PO / FUTURE_PRODUCTION                                       ║
╚═════════════════════════════════════════════════════════════════════════════════════════╝
                                            │
                                            ▼
╔═════════════════════════════════════════════════════════════════════════════════════════╗
║                    AGENT 2: DELIVERY SCHEDULER                                          ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Purpose: Align ATP results with carrier calendars & customer windows                   ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Process Flow:                                                                          ║
║    1. Select Carrier (Priority-based: FedEx, UPS, DHL, USPS)                           ║
║    2. Calculate Transit Time (1-7 days by carrier)                                      ║
║    3. Check Customer Delivery Windows (08:00-17:00)                                     ║
║    4. Adjust for Weekends & Blackout Dates                                              ║
║    5. Generate Ship Date & Delivery Date                                                ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Output: Delivery Schedules (200 Lines)                                                 ║
║    FedEx: 82  |  UPS: 68  |  USPS: 25  |  DHL: 25                                      ║
║    Transit: 1-7 days  |  Customer Windows: Validated                                    ║
╚═════════════════════════════════════════════════════════════════════════════════════════╝
                                            │
                                            ▼
╔═════════════════════════════════════════════════════════════════════════════════════════╗
║                    AGENT 3: SPLIT SHIPMENT ANALYZER                                     ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Purpose: Apply business rules to determine partial shipment requirements               ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Process Flow:                                                                          ║
║    1. Evaluate Customer Partial Shipment Preferences                                    ║
║    2. Check Partial Allow Flag (75% allow, 25% don't)                                  ║
║    3. Decision Logic:                                                                   ║
║         ├─ Full Quantity Available → Single Shipment                                   ║
║         ├─ Partial Quantity Available → Create Split (Max 3 splits)                    ║
║         └─ No Quantity Available → Backorder Single Shipment                           ║
║    4. Apply Business Rules (Min 5 units per split)                                      ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Output: Split Decisions (200 Lines → 237 Shipments)                                    ║
║    NONE: 157 (78.5%)  |  PARTIAL_AVAILABILITY: 37 (18.5%)  |  BACKORDER: 6 (3.0%)     ║
║    Average: 1.19 shipments per order line                                               ║
╚═════════════════════════════════════════════════════════════════════════════════════════╝
                                            │
                                            ▼
╔═════════════════════════════════════════════════════════════════════════════════════════╗
║                    AGENT 4: CONFIRM COMPOSER                                            ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Purpose: Generate confirmation payload with promise dates & terms                      ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Process Flow:                                                                          ║
║    1. Group Shipments by Order ID (200 lines → 101 orders)                             ║
║    2. Generate Confirmation Number (CNF-ORD-XXXXX-timestamp)                            ║
║    3. Compile Shipment Details (Items, Quantities, Dates, Carriers)                     ║
║    4. Format Email Template with Terms & Conditions                                     ║
║    5. Create Complete Confirmation Payload                                              ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Output: Order Confirmations (101 Orders)                                               ║
║    Formatted Emails  |  Promise Dates  |  Shipment Details  |  Terms: Net 30 days      ║
╚═════════════════════════════════════════════════════════════════════════════════════════╝
                                            │
                                            ▼
╔═════════════════════════════════════════════════════════════════════════════════════════╗
║                    AGENT 5: CHANNEL DISPATCHER                                          ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Purpose: Send confirmations via appropriate channels with retry logic                  ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Process Flow:                                                                          ║
║    1. Determine Channel by Priority:                                                    ║
║         ├─ PRIORITY Orders → API Channel                                               ║
║         ├─ NORMAL Orders → EMAIL Channel                                               ║
║         └─ LOW Priority → EDI Channel                                                  ║
║    2. Send Confirmation via Selected Channel                                            ║
║    3. Apply Retry Logic (Max 3 attempts)                                                ║
║    4. Track Receipt Confirmation & Status                                               ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Output: Dispatch Results (101 Confirmations)                                           ║
║    ✓ SENT: 100  |  ⟳ RETRY: 1  |  Success Rate: 99.0%                                 ║
║    Channels: EMAIL (72)  |  EDI (22)  |  API (7)                                        ║
╚═════════════════════════════════════════════════════════════════════════════════════════╝
                                            │
                                            ▼
╔═════════════════════════════════════════════════════════════════════════════════════════╗
║                      AGENT 6: AUDIT LOGGER                                              ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Purpose: Capture immutable logs for compliance & audit trails                          ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Process Flow:                                                                          ║
║    1. Capture All Agent Actions & Data                                                  ║
║    2. Record Input/Output for Each Step                                                 ║
║    3. Add Timestamps & Performance Metrics (duration in ms)                             ║
║    4. Create Immutable Log with Unique Log ID                                           ║
║    5. Store in Audit Trail (7-year retention)                                           ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║  Output: Audit Logs (802 Entries)                                                       ║
║    5 Agents Tracked  |  5 Action Types  |  Queryable Compliance Data                   ║
╚═════════════════════════════════════════════════════════════════════════════════════════╝
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                   FINAL OUTPUT                                           │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────┐         ┌──────────────────────────────────┐       │
│  │  order_confirmation_audit.json │         │  Console Output                  │       │
│  ├────────────────────────────────┤         ├──────────────────────────────────┤       │
│  │  • 802 Audit Log Entries       │         │  • Agent Processing Summary      │       │
│  │  • Complete Compliance Trail   │         │  • Detailed Results (15 samples) │       │
│  │  • Input/Output Data           │         │  • Sample Confirmations (3)      │       │
│  │  • Performance Metrics          │         │  • Statistics & Success Rates    │       │
│  │  • Queryable JSON Format       │         │  • Final Summary Report          │       │
│  └────────────────────────────────┘         └──────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
                              ┌──────────────────────────┐
                              │   PROCESS COMPLETE ✓     │
                              │  99% Dispatch Success    │
                              │  200 Lines Processed     │
                              │  101 Orders Confirmed    │
                              └──────────────────────────┘
```

### Simplified Agent Flow
```
Order Lines (200) 
    ↓
[1] ATP Checker → Validates inventory & capacity
    ↓
[2] Delivery Scheduler → Aligns with carrier calendars & customer windows
    ↓
[3] Split Shipment → Applies business rules for partial shipments
    ↓
[4] Confirm Composer → Generates formatted confirmation emails
    ↓
[5] Channel Dispatcher → Sends via EMAIL/API/EDI channels
    ↓
[6] Audit Logger → Records immutable compliance logs
```

## Agent Details

### 1. ATP Checker Agent
- **Purpose**: Run ATP against inventory and capacity
- **Output**: Earliest available dates per line, availability status
- **Statuses**: AVAILABLE, PARTIAL, BACKORDER
- **Sources**: STOCK, INBOUND_PO, FUTURE_PRODUCTION

### 2. Delivery Scheduler Agent
- **Purpose**: Align ATP results with carrier calendars and transit times
- **Features**: 
  - Carrier selection based on priority (FedEx, UPS, DHL, USPS)
  - Transit time calculation (1-7 days)
  - Customer delivery window validation
  - Weekend adjustment

### 3. Split Shipment Agent
- **Purpose**: Determine when partial shipments are required
- **Business Rules**:
  - Customer partial shipment preferences
  - Max 3 splits per order
  - Min 5 units per split
- **Split Reasons**: NONE, PARTIAL_AVAILABILITY, BACKORDER

### 4. Confirm Composer Agent
- **Purpose**: Generate confirmation payload with promise dates
- **Output**: 
  - Formatted email with shipment details
  - Confirmation number (CNF-ORD-XXXXX-timestamp)
  - Terms & conditions
  - Grouped by order ID

### 5. Channel Dispatcher Agent
- **Purpose**: Send confirmations via appropriate channels
- **Channels**: EMAIL (72%), EDI (22%), API (7%)
- **Features**:
  - Channel selection by priority
  - Retry logic (max 3 attempts)
  - Receipt confirmation tracking
  - 99% dispatch success rate

### 6. Audit Logger Agent
- **Purpose**: Capture immutable logs for compliance
- **Features**:
  - Records all agent actions
  - Queryable audit trails
  - JSON export capability
  - 7-year retention configuration

## Sample Data Generation

### Generated for 200 Order Lines:
- **50 Customers** with unique IDs, names, emails
- **50 Items** across 5 categories (WIDGET, GADGET, DEVICE, COMPONENT, MODULE)
- **200 Order Lines** distributed across 101 unique orders
- **50 Inventory Records** with on-hand and safety stock quantities
- **15 Purchase Orders** with expected delivery dates

### Customer Attributes:
- Delivery windows (08:00-17:00)
- Partial shipment preferences (75% allow, 25% don't)
- Priority levels (PRIORITY: 10%, NORMAL: 70%, LOW: 20%)

## Execution Results

### Processing Statistics (Sample Run):
```
Total Order Lines: 200
Unique Orders: 101
Unique Customers: 31

ATP Results:
  - AVAILABLE: 147 (73.5%)
  - PARTIAL: 47 (23.5%)
  - BACKORDER: 6 (3.0%)

Carriers:
  - FedEx: 82
  - UPS: 68
  - USPS: 25
  - DHL: 25

Split Decisions:
  - NONE: 157 (78.5%)
  - PARTIAL_AVAILABILITY: 37 (18.5%)
  - BACKORDER: 6 (3.0%)
  - Total Shipments: 237 (avg 1.19 per order)

Confirmations: 101 generated
Dispatches: 101 sent (99% success rate)
Audit Logs: 802 entries
```

## Output Files

### 1. order_confirmation_audit.json
Complete audit trail with:
- All 802 log entries
- Agent actions and timestamps
- Input/output data for each step
- Performance metrics (duration in ms)

### 2. Console Output
- Agent-by-agent processing summary
- Detailed output for first 15 order lines
- Sample confirmation emails (first 3)
- Final statistics and success rates

## Key Features

### Business Logic:
- ✅ Safety stock protection
- ✅ Purchase order consideration
- ✅ Lead time calculation (14-day default)
- ✅ Partial shipment handling
- ✅ Priority-based carrier selection
- ✅ Customer delivery windows

### Technical Features:
- ✅ Autogen framework integration
- ✅ Dataclass-based models
- ✅ Sequential agent orchestration
- ✅ Comprehensive logging
- ✅ JSON audit export
- ✅ Randomized test data generation

## Configuration

### SystemConfig Parameters:
```python
# ATP Settings
allow_partial_ship = True
default_safety_stock = 10
default_lead_time_days = 14

# Carrier Settings
carriers = ["FedEx", "UPS", "DHL", "USPS"]
carrier_transit_times = {1-7 days by carrier}

# Split Rules
max_splits_per_order = 3
min_split_quantity = 5

# Dispatch Settings
channel_preference = {"PRIORITY": "API", "NORMAL": "EMAIL", "LOW": "EDI"}
max_retry_attempts = 3

# Audit Settings
audit_retention_days = 2555  # 7 years
enable_compliance_reporting = True
```

## Running the System

```bash
python Confirm_Order_Process.py
```

### Expected Output:
1. Data generation summary
2. Agent-by-agent processing logs
3. Detailed output for first 15 lines
4. Sample confirmations (first 3)
5. Final statistics
6. Audit log export confirmation

## Sample Confirmation Email

```
========================================
ORDER CONFIRMATION
========================================

Dear Customer 1,

Thank you for your order!

Order ID: ORD-00001
Confirmation Number: CNF-ORD-00001-20260115045859
Confirmation Date: 2026-01-15 04:58:59

SHIPMENT DETAILS:
----------------------------------------

Shipment 1:
  Item: MODULE-026
  Quantity: 90 units
  Ship Date: 2026-01-16
  Delivery Date: 2026-01-19
  Carrier: FedEx
  Status: COMPLETE

----------------------------------------
TERMS & CONDITIONS:
Payment: Net 30 days
Shipping: Free on orders over $500
Returns: 30-day return policy applies

For questions, contact: support@company.com

Thank you for your business!
========================================
```

## Extensions & Customization

### Easy Modifications:
1. **Add more carriers**: Update `SystemConfig.carriers` and `carrier_transit_times`
2. **Change split rules**: Modify `SystemConfig.max_splits_per_order` or `min_split_quantity`
3. **Adjust ATP logic**: Edit `ATPCheckerAgent.calculate_atp()` method
4. **Custom email templates**: Modify `ConfirmComposerAgent._format_email()`
5. **Additional channels**: Extend `ChannelDispatcherAgent.dispatch_confirmation()`

## Compliance & Audit

### Audit Log Structure:
```json
{
  "log_id": "LOG-20260115045859123456-0",
  "timestamp": "2026-01-15 04:58:59",
  "order_id": "ORD-00001",
  "agent": "ATP_Checker",
  "action": "calculate_atp",
  "input_data": {"line_id": "LINE-00001", "item": "MODULE-026"},
  "output_data": {"status": "AVAILABLE", "available_qty": 90},
  "status": "SUCCESS",
  "duration_ms": 0.0027
}
```

### Queryable Attributes:
- Order ID
- Agent name
- Action type
- Timestamp
- Status (SUCCESS/FAILED/RETRY)
- Processing duration

## Success Metrics

✅ **200 order lines** processed successfully  
✅ **101 unique orders** confirmed  
✅ **99% dispatch success** rate  
✅ **802 audit logs** captured  
✅ **6 agents** working in sequence  
✅ **237 shipments** planned (1.19 avg per order)  
✅ **73.5% immediate availability** from stock  

---

**Built with**: Python 3.13, Autogen Framework, Pandas, Dataclasses  
**Created**: January 15, 2026  
**Version**: 1.0
