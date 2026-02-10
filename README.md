# ATP Checker Agent - Autogen Framework

An intelligent Available-to-Promise (ATP) checker agent built with the Autogen framework that validates product availability and calculates earliest ship dates based on inventory, purchase orders, and lead times.

## Overview

The ATP Checker Agent runs ATP checks against inventory and capacity to compute earliest available dates per order line and outputs availability results for scheduling. It integrates with ERP systems to access real-time inventory data and open purchase orders.

## Features

- **Real-time ATP Checking**: Validates product availability against current inventory levels
- **Multi-source Availability**: Checks stock, inbound purchase orders, and future production
- **Safety Stock Validation**: Respects safety stock rules and inventory policies
- **Lead Time Calculation**: Automatically calculates delivery dates based on supplier lead times
- **ERP Integration**: Connects to ERP/MM modules via REST API
- **Intelligent Agent**: Uses Autogen framework for conversational AI capabilities
- **Batch Processing**: Handle multiple order lines in a single request

## Architecture

```
┌─────────────────┐
│   Main.py       │  Entry point and orchestration
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  atp_agent.py   │  Autogen-based ATP Checker Agent
└────────┬────────┘
         │
         ├──────────────────┬─────────────────┐
         ▼                  ▼                 ▼
┌─────────────────┐  ┌──────────────┐  ┌─────────────┐
│  atp_engine.py  │  │erp_integration│  │  Models.py  │
│                 │  │     .py       │  │             │
│ ATP Logic &     │  │               │  │ Data Models │
│ Calculations    │  │ ERP API Calls │  │             │
└─────────────────┘  └──────────────┘  └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │  Config.py   │
                     │              │
                     │ Configuration│
                     └──────────────┘
```

## Components

### 1. Models.py
Defines data models:
- `OrderLine`: Customer order line details
- `InventorySnapshot`: Current inventory status
- `PurchaseOrder`: Inbound purchase order information
- `ATPResult`: ATP check results with availability dates
- `ATPCheckRequest`: Request container

### 2. Config.py
Configuration classes:
- `Policy`: Business rules (safety stock, lead times, partial shipments)
- `ERPConfig`: ERP API connection settings
- `AppConfig`: Application-wide configuration

### 3. atp_engine.py
Core ATP calculation engine:
- Stock availability checking
- Safety stock validation
- Purchase order consideration
- Lead time calculation
- Earliest date computation

### 4. erp_integration.py
ERP system integration:
- Inventory snapshot retrieval
- Purchase order data fetching
- Lead time queries
- Mock data for testing

### 5. atp_agent.py
Autogen-based agent:
- ATP orchestration
- Conversational AI interface
- Multi-agent coordination
- Result formatting

### 6. main.py
Example usage and execution

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure ERP settings in `Config.py`:
```python
erp=ERPConfig(
    base_url="https://your-erp-system.com/api",
    api_key="your-api-key",
    timeout_seconds=20
)
```

3. (Optional) Configure OpenAI API for conversational mode in `main.py`:
```python
llm_config = {
    "config_list": [{
        "model": "gpt-4",
        "api_key": "your-openai-api-key"
    }],
    "temperature": 0,
}
```

## Usage

### Basic Usage

```python
from datetime import date, timedelta
from Models import OrderLine
from Config import AppConfig
from atp_agent import ATPCheckerAgent

# Initialize configuration
config = AppConfig()

# Create ATP Checker Agent
atp_agent = ATPCheckerAgent(config=config)

# Create order lines
order_lines = [
    OrderLine(
        order_id="SO-1001",
        line_id="001",
        item="WIDGET-A",
        quantity=50,
        requested_date=date.today() + timedelta(days=7)
    )
]

# Process ATP check
results = atp_agent.process_atp_request(order_lines)

# Review results
for result in results:
    print(f"Item: {result.item}")
    print(f"Status: {result.status}")
    print(f"Available Qty: {result.available_quantity}")
    print(f"Earliest Date: {result.earliest_available_date}")
```

### Run Example

```bash
python main.py
```

## ATP Logic Flow

1. **Receive Order Line Request**
   - Extract item, quantity, requested date

2. **Fetch Data from ERP**
   - Get current inventory snapshot
   - Retrieve open purchase orders
   - Query lead times

3. **Check Stock Availability**
   - Calculate available stock (on-hand - safety stock)
   - If sufficient → return AVAILABLE with earliest date
   - If partial allowed and some available → return PARTIAL

4. **Check Inbound Purchase Orders**
   - Sort POs by expected delivery date
   - Accumulate quantities
   - If sufficient → return AVAILABLE/BACKORDER with PO date
   - If partial allowed → return PARTIAL

5. **Calculate from Lead Time**
   - Use default or supplier-specific lead time
   - Add buffer days (receiving, quality, transit)
   - Return BACKORDER with calculated date

## Configuration Options

### Policy Settings

```python
Policy(
    allow_partial_ship=True,          # Allow partial shipments
    consider_unconfirmed_pos=False,   # Include unconfirmed POs
    default_safety_stock=10,          # Default safety stock qty
    default_lead_time_days=14,        # Default lead time
    receiving_buffer_days=1,          # Receiving processing time
    quality_buffer_days=1,            # Quality inspection time
    transit_days_default=2            # Default transit time
)
```

## Output Format

ATP results include:
- `status`: "AVAILABLE", "PARTIAL", or "BACKORDER"
- `available_quantity`: Quantity that can be fulfilled
- `earliest_available_date`: Earliest ship date
- `source`: "STOCK", "INBOUND_PO", or "FUTURE_PRODUCTION"
- `messages`: Detailed explanation of availability

## Integration Points

### ERP API Endpoints

The system expects the following ERP API endpoints:

1. **GET /inventory/snapshot**
   - Returns current inventory levels
   - Parameters: items[], locations[]

2. **GET /purchasing/open-orders**
   - Returns open purchase orders
   - Parameters: items[], locations[]

3. **GET /items/{item}/lead-time**
   - Returns lead time for item
   - Parameters: supplier (optional)

## Testing

The system includes mock data for testing without ERP connectivity:

```python
# Mock data is automatically used if ERP API calls fail
inventory = erp_integration.get_inventory_snapshot(items=["WIDGET-A"])
# Returns mock data if API unavailable
```

## Downstream Integration

ATP results can be forwarded to:
- Order management systems
- Production scheduling
- Customer service portals
- Planning systems

Export results as JSON:
```python
import json
with open('atp_results.json', 'w') as f:
    json.dump(results_export, f, indent=2)
```

## Key Validations

1. **Stock Availability**: On-hand qty > Safety stock
2. **Safety Stock Rules**: Respects minimum stock levels
3. **Lead Time Calculation**: Supplier lead time + buffers
4. **Date Feasibility**: Earliest date ≥ Today + processing time
5. **Data Freshness**: Inventory staleness checks

## Error Handling

- ERP connection failures → Uses mock data
- Invalid order data → Returns error in messages
- Missing configuration → Uses defaults
- API timeouts → Configurable timeout settings

## Future Enhancements

- Multi-location ATP allocation optimization
- Capacity constraint checking
- Production schedule integration
- ML-based demand forecasting
- Real-time inventory updates via webhooks
- Advanced allocation rules (FIFO, priority-based)

## License

MIT License

## Support

For issues and questions, please refer to the project documentation or contact the development team.
