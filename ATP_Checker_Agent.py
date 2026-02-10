import pandas as pd
from datetime import date, datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional, Any
import os
import json

#NOTE: For ATP Checker Agent the AutoGen classes used are AssistantAgent and UserProxyAgent

AUTOGEN_AVAILABLE = False
try:
    import autogen
    AUTOGEN_AVAILABLE = True
except ImportError:
    try:
        from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
        
        class autogen:
            AssistantAgent = AssistantAgent
            UserProxyAgent = UserProxyAgent
        AUTOGEN_AVAILABLE = True
    except ImportError:
        pass  




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
    status: str
    source: str
    messages: List[str] = None
    
    def __post_init__(self):
        if self.messages is None:
            self.messages = []



class ATPConfig:
    """ATP Configuration"""
    allow_partial_ship = True
    consider_unconfirmed_pos = False
    default_safety_stock = 10
    default_lead_time_days = 14
    receiving_buffer_days = 1
    quality_buffer_days = 1
    transit_days_default = 2


class ATPEngine:
    """Core ATP calculation engine"""
    
    def __init__(self, config: ATPConfig):
        self.config = config
    
    def calculate_atp(
        self,
        order_line: OrderLine,
        inventory: List[InventorySnapshot],
        purchase_orders: List[PurchaseOrder]
    ) -> ATPResult:
        """Calculate ATP for a single order line"""
        messages = []
        
        # Filter relevant inventory and POs
        relevant_inventory = [inv for inv in inventory if inv.item == order_line.item]
        if order_line.ship_from:
            relevant_inventory = [inv for inv in relevant_inventory if inv.location == order_line.ship_from]
        
        relevant_pos = [po for po in purchase_orders if po.item == order_line.item]
        if order_line.ship_from:
            relevant_pos = [po for po in relevant_pos if po.location == order_line.ship_from]
        
        if not self.config.consider_unconfirmed_pos:
            relevant_pos = [po for po in relevant_pos if po.confirmed]
        
        relevant_pos.sort(key=lambda x: x.expected_delivery_date)
        
        # Calculate available stock
        total_on_hand = sum(inv.on_hand_qty for inv in relevant_inventory)
        total_safety_stock = sum(inv.safety_stock_qty for inv in relevant_inventory)
        available_stock = max(0, total_on_hand - total_safety_stock)
        
        messages.append(f"On-hand: {total_on_hand}, Safety stock: {total_safety_stock}, Available: {available_stock}")
        
        # Check if current stock can fulfill
        if available_stock >= order_line.quantity:
            buffer_days = (self.config.receiving_buffer_days + 
                          self.config.quality_buffer_days + 
                          self.config.transit_days_default)
            earliest_date = max(order_line.requested_date, date.today() + timedelta(days=buffer_days))
            
            return ATPResult(
                order_id=order_line.order_id,
                line_id=order_line.line_id,
                item=order_line.item,
                requested_quantity=order_line.quantity,
                requested_date=order_line.requested_date,
                available_quantity=order_line.quantity,
                earliest_available_date=earliest_date,
                status="AVAILABLE",
                source="STOCK",
                messages=messages + ["Full quantity available from stock"]
            )
        
        # Check partial shipment
        if self.config.allow_partial_ship and available_stock > 0:
            buffer_days = (self.config.receiving_buffer_days + 
                          self.config.quality_buffer_days + 
                          self.config.transit_days_default)
            earliest_date = max(order_line.requested_date, date.today() + timedelta(days=buffer_days))
            
            return ATPResult(
                order_id=order_line.order_id,
                line_id=order_line.line_id,
                item=order_line.item,
                requested_quantity=order_line.quantity,
                requested_date=order_line.requested_date,
                available_quantity=available_stock,
                earliest_available_date=earliest_date,
                status="PARTIAL",
                source="STOCK",
                messages=messages + [f"Partial quantity {available_stock} available, Short {order_line.quantity - available_stock} units"]
            )
        
        # Check purchase orders
        accumulated_qty = available_stock
        for po in relevant_pos:
            accumulated_qty += po.quantity
            
            if accumulated_qty >= order_line.quantity:
                buffer_days = (self.config.receiving_buffer_days + 
                              self.config.quality_buffer_days + 
                              self.config.transit_days_default)
                earliest_po_date = po.expected_delivery_date + timedelta(days=buffer_days)
                
                return ATPResult(
                    order_id=order_line.order_id,
                    line_id=order_line.line_id,
                    item=order_line.item,
                    requested_quantity=order_line.quantity,
                    requested_date=order_line.requested_date,
                    available_quantity=order_line.quantity,
                    earliest_available_date=max(order_line.requested_date, earliest_po_date),
                    status="AVAILABLE" if earliest_po_date <= order_line.requested_date else "BACKORDER",
                    source="INBOUND_PO",
                    messages=messages + [f"Available from PO {po.po_id} (EDD: {po.expected_delivery_date})"]
                )
        
        # Fallback to lead time
        total_lead_time = (self.config.default_lead_time_days + 
                          self.config.receiving_buffer_days + 
                          self.config.quality_buffer_days + 
                          self.config.transit_days_default)
        earliest_date = date.today() + timedelta(days=total_lead_time)
        
        return ATPResult(
            order_id=order_line.order_id,
            line_id=order_line.line_id,
            item=order_line.item,
            requested_quantity=order_line.quantity,
            requested_date=order_line.requested_date,
            available_quantity=order_line.quantity,
            earliest_available_date=earliest_date,
            status="BACKORDER",
            source="FUTURE_PRODUCTION",
            messages=messages + [f"No stock or POs available. Using lead time of {total_lead_time} days"]
        )
    
    def batch_calculate_atp(
        self,
        order_lines: List[OrderLine],
        inventory: List[InventorySnapshot],
        purchase_orders: List[PurchaseOrder]
    ) -> List[ATPResult]:
        """Calculate ATP for multiple order lines"""
        results = []
        for order_line in order_lines:
            result = self.calculate_atp(order_line, inventory, purchase_orders)
            results.append(result)
        return results



class DataManager:
    """Manages inventory and purchase order data"""
    
    @staticmethod
    def get_sample_inventory() -> List[InventorySnapshot]:
        """Get sample inventory data - expanded for 200+ orders"""
        import random
        
        items_pool = [
            'WIDGET-A', 'WIDGET-B', 'WIDGET-C', 'WIDGET-D', 'WIDGET-E',
            'GADGET-X', 'GADGET-Y', 'GADGET-Z',
            'PART-123', 'PART-456', 'PART-789',
            'COMPONENT-A1', 'COMPONENT-B2', 'COMPONENT-C3',
            'MODULE-10', 'MODULE-20', 'MODULE-30',
            'ASSEMBLY-AA', 'ASSEMBLY-BB', 'ASSEMBLY-CC'
        ]
        
        inventory = []
        for item in items_pool:
            # Randomize inventory levels for realistic scenarios
            on_hand = random.randint(20, 300)
            safety_stock = random.randint(10, 50)
            
            inventory.append(InventorySnapshot(
                item=item,
                location="MAIN",
                on_hand_qty=on_hand,
                safety_stock_qty=safety_stock,
                last_updated=datetime.now()
            ))
        
        return inventory
    
    @staticmethod
    def get_sample_purchase_orders() -> List[PurchaseOrder]:
        """Get sample purchase order data - expanded for multiple items"""
        import random
        
        items_with_pos = [
            'WIDGET-C', 'WIDGET-D', 'WIDGET-A', 'GADGET-X', 'GADGET-Y',
            'PART-123', 'PART-456', 'COMPONENT-A1', 'COMPONENT-B2',
            'MODULE-10', 'MODULE-20', 'ASSEMBLY-AA'
        ]
        
        pos = []
        po_counter = 1001
        
        for item in items_with_pos:
            # Some items may have multiple POs
            num_pos = random.randint(1, 2)
            for i in range(num_pos):
                pos.append(PurchaseOrder(
                    po_id=f"PO-{po_counter}",
                    item=item,
                    quantity=random.randint(50, 200),
                    expected_delivery_date=date.today() + timedelta(days=random.randint(5, 30)),
                    location="MAIN",
                    confirmed=random.choice([True, True, True, False])  # 75% confirmed
                ))
                po_counter += 1
        
        return pos



class ExcelManager:
    """Manages Excel file operations"""
    
    @staticmethod
    def create_sample_order_excel(filename: str = "sample_orders.xlsx", num_orders: int = 200):
        """Create a sample Excel file with order data"""
        import random
        today = date.today()
        
        # Define items pool
        items_pool = [
            'WIDGET-A', 'WIDGET-B', 'WIDGET-C', 'WIDGET-D', 'WIDGET-E',
            'GADGET-X', 'GADGET-Y', 'GADGET-Z',
            'PART-123', 'PART-456', 'PART-789',
            'COMPONENT-A1', 'COMPONENT-B2', 'COMPONENT-C3',
            'MODULE-10', 'MODULE-20', 'MODULE-30',
            'ASSEMBLY-AA', 'ASSEMBLY-BB', 'ASSEMBLY-CC'
        ]
        
        priorities = ['HIGH', 'NORMAL', 'LOW']
        
        # Generate 200 orders
        order_ids = []
        line_ids = []
        items = []
        quantities = []
        requested_dates = []
        ship_froms = []
        priority_list = []
        
        order_counter = 1001
        for i in range(num_orders):
            # Every 3-5 lines create a new order
            if i % random.randint(3, 5) == 0:
                order_counter += 1
            
            order_ids.append(f'SO-{order_counter}')
            line_ids.append(f'{(i % 10):03d}')
            items.append(random.choice(items_pool))
            quantities.append(random.randint(10, 200))
            requested_dates.append(today + timedelta(days=random.randint(1, 45)))
            ship_froms.append('MAIN')
            priority_list.append(random.choice(priorities))
        
        sample_data = {
            'Order_ID': order_ids,
            'Line_ID': line_ids,
            'Item': items,
            'Quantity': quantities,
            'Requested_Date': requested_dates,
            'Ship_From': ship_froms,
            'Priority': priority_list
        }
        
        df = pd.DataFrame(sample_data)
        df.to_excel(filename, index=False, sheet_name='Orders')
        print(f"Generated {num_orders} order lines with {len(set(items))} unique items")
        return filename
    
    @staticmethod
    def read_orders_from_excel(filename: str) -> List[OrderLine]:
        """Read order lines from Excel file"""
        try:
            df = pd.read_excel(filename, sheet_name='Orders')
            
            order_lines = []
            for _, row in df.iterrows():
                req_date = row['Requested_Date']
                if isinstance(req_date, str):
                    req_date = datetime.strptime(req_date, '%Y-%m-%d').date()
                elif isinstance(req_date, pd.Timestamp):
                    req_date = req_date.date()
                
                order_line = OrderLine(
                    order_id=str(row['Order_ID']),
                    line_id=str(row['Line_ID']),
                    item=str(row['Item']),
                    quantity=int(row['Quantity']),
                    requested_date=req_date,
                    ship_from=str(row.get('Ship_From', 'MAIN')),
                    priority=str(row.get('Priority', 'NORMAL'))
                )
                order_lines.append(order_line)
            
            return order_lines
            
        except FileNotFoundError:
            ExcelManager.create_sample_order_excel(filename)
            return ExcelManager.read_orders_from_excel(filename)
    
    @staticmethod
    def write_results_to_excel(results: List[ATPResult], filename: str = "atp_results_autogen.xlsx"):
        """Write ATP results to Excel file with multiple sheets"""
        
        # Main results sheet
        results_data = []
        for result in results:
            results_data.append({
                'Order_ID': result.order_id,
                'Line_ID': result.line_id,
                'Item': result.item,
                'Requested_Qty': result.requested_quantity,
                'Requested_Date': result.requested_date,
                'Status': result.status,
                'Available_Qty': result.available_quantity,
                'Earliest_Available_Date': result.earliest_available_date,
                'Source': result.source,
                'Days_Delay': (result.earliest_available_date - result.requested_date).days if result.earliest_available_date else 0,
                'Notes': ' | '.join(result.messages)
            })
        
        df_results = pd.DataFrame(results_data)
        
        # Summary sheet
        summary_data = {
            'Metric': [
                'Total Lines',
                'Available',
                'Partial',
                'Backorder',
                'Available %',
                'On-Time %'
            ],
            'Value': [
                len(results),
                sum(1 for r in results if r.status == 'AVAILABLE'),
                sum(1 for r in results if r.status == 'PARTIAL'),
                sum(1 for r in results if r.status == 'BACKORDER'),
                f"{sum(1 for r in results if r.status == 'AVAILABLE') / len(results) * 100:.1f}%" if results else "0%",
                f"{sum(1 for r in results if r.earliest_available_date and r.earliest_available_date <= r.requested_date) / len(results) * 100:.1f}%" if results else "0%"
            ]
        }
        df_summary = pd.DataFrame(summary_data)
        
        # By Status sheet
        status_data = []
        for status in ['AVAILABLE', 'PARTIAL', 'BACKORDER']:
            status_results = [r for r in results if r.status == status]
            status_data.append({
                'Status': status,
                'Count': len(status_results),
                'Total_Qty': sum(r.requested_quantity for r in status_results),
                'Avg_Days_to_Ship': sum((r.earliest_available_date - date.today()).days for r in status_results if r.earliest_available_date) / len(status_results) if status_results else 0
            })
        df_by_status = pd.DataFrame(status_data)
        
        # By Item sheet with earliest available date per item
        items = {}
        for result in results:
            if result.item not in items:
                items[result.item] = {
                    'Available': 0,
                    'Partial': 0,
                    'Backorder': 0,
                    'Total_Qty': 0,
                    'Earliest_Available_Date': None,
                    'Total_Requested_Qty': 0
                }
            items[result.item][result.status] = items[result.item].get(result.status, 0) + 1
            items[result.item]['Total_Qty'] += result.requested_quantity
            items[result.item]['Total_Requested_Qty'] += result.requested_quantity
            
            # Track earliest available date per item
            if result.earliest_available_date:
                if items[result.item]['Earliest_Available_Date'] is None:
                    items[result.item]['Earliest_Available_Date'] = result.earliest_available_date
                else:
                    items[result.item]['Earliest_Available_Date'] = min(
                        items[result.item]['Earliest_Available_Date'],
                        result.earliest_available_date
                    )
        
        item_data = []
        for item, stats in items.items():
            item_data.append({
                'Item': item,
                'Earliest_Available_Date': stats['Earliest_Available_Date'],
                'Total_Lines': stats['Available'] + stats['Partial'] + stats['Backorder'],
                'Total_Qty_Requested': stats['Total_Requested_Qty'],
                'Available': stats['Available'],
                'Partial': stats['Partial'],
                'Backorder': stats['Backorder']
            })
        df_by_item = pd.DataFrame(item_data)
        
        # Earliest Available Date Per Item sheet (as per user requirement)
        earliest_per_item = []
        for item, stats in items.items():
            earliest_per_item.append({
                'Item': item,
                'Earliest_Available_Date': stats['Earliest_Available_Date'],
                'Total_Quantity_Requested': stats['Total_Requested_Qty'],
                'Total_Order_Lines': stats['Available'] + stats['Partial'] + stats['Backorder'],
                'Status_Summary': f"Available: {stats['Available']}, Partial: {stats['Partial']}, Backorder: {stats['Backorder']}"
            })
        df_earliest_per_item = pd.DataFrame(earliest_per_item).sort_values('Earliest_Available_Date')
        
        # Write to Excel with multiple sheets
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            df_results.to_excel(writer, sheet_name='ATP Results', index=False)
            df_earliest_per_item.to_excel(writer, sheet_name='Earliest Date Per Item', index=False)
            df_summary.to_excel(writer, sheet_name='Summary', index=False)
            df_by_status.to_excel(writer, sheet_name='By Status', index=False)
            df_by_item.to_excel(writer, sheet_name='By Item', index=False)
            
            # Auto-adjust column widths
            for sheet_name in writer.sheets:
                worksheet = writer.sheets[sheet_name]
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width




class ATPAutogenAgent:
    """ATP Checker using Autogen Framework"""
    
    def __init__(self, config: ATPConfig, llm_config: Optional[Dict[str, Any]] = None, enable_autogen: bool = False):
        self.config = config
        self.atp_engine = ATPEngine(config)
        self.data_manager = DataManager()
        self.excel_manager = ExcelManager()
        
        # Store data
        self.inventory = self.data_manager.get_sample_inventory()
        self.purchase_orders = self.data_manager.get_sample_purchase_orders()
        self.current_results = []
        
        # Setup LLM config
        if llm_config is None:
            llm_config = {
                "config_list": [{
                    "model": "gpt-4",
                    "api_key": os.getenv("OPENAI_API_KEY", "your-api-key-here")
                }],
                "temperature": 0,
            }
        
        self.llm_config = llm_config
        self.enable_autogen = enable_autogen
        
        # Only setup agents if explicitly enabled and Autogen is available
        if enable_autogen and AUTOGEN_AVAILABLE:
            try:
                self._setup_agents()
            except Exception as e:
                print(f"Warning: Could not setup Autogen agents: {e}")
                print("Continuing in direct execution mode...")
                self.enable_autogen = False
        elif enable_autogen and not AUTOGEN_AVAILABLE:
            print("Warning: Autogen framework not available. Running in direct execution mode.")
            self.enable_autogen = False
    
    def _setup_agents(self):
        """Setup Autogen conversable agents"""
        
        # ATP Checker Agent
        self.atp_agent = autogen.AssistantAgent(
            name="ATP_Checker",
            llm_config=self.llm_config,
            system_message="""You are an ATP (Available-to-Promise) Checker Agent.

User responsibilities:
1. Analyze order requests and validate product availability
2. Calculate earliest ship dates based on inventory, safety stock, and lead times
3. Check inbound purchase orders for future availability
4. Provide clear, actionable availability information with business insights

When processing ATP requests:
- Always verify current inventory levels
- Apply safety stock rules strictly
- Consider confirmed purchase orders for future availability
- Calculate realistic lead times including all buffer days
- Provide detailed explanations of availability status

Output format:
- Status: AVAILABLE, PARTIAL, or BACKORDER
- Available quantity and earliest date
- Source: STOCK, INBOUND_PO, or FUTURE_PRODUCTION
- Business recommendations for partial or backorder situations"""
        )
        
        self.analyst_agent = autogen.AssistantAgent(
            name="Data_Analyst",
            llm_config=self.llm_config,
            system_message="""You are a Data Analyst Agent specializing in supply chain analytics.

User responsibilities:
1. Analyze ATP results and identify patterns
2. Generate summary statistics and insights
3. Identify risks and opportunities
4. Provide actionable recommendations

Focus on:
- Overall availability rates
- Items with high backorder rates
- Lead time analysis
- Inventory optimization opportunities
- Priority order management"""
        )
        
        self.user_proxy = autogen.UserProxyAgent(
            name="User",
            human_input_mode="NEVER",
            max_consecutive_auto_reply=10,
            code_execution_config={"use_docker": False},
            is_termination_msg=lambda x: x.get("content", "").rstrip().endswith("TERMINATE")
        )
        
        self._register_functions()
    
    def _register_functions(self):
        """Register callable functions for agents"""
        
        @self.user_proxy.register_for_execution()
        @self.atp_agent.register_for_llm(description="Check ATP availability for order lines from Excel file")
        def check_atp_from_excel(filename: str) -> str:
            """
            Check ATP for orders in Excel file
            
            Args:
                filename: Path to Excel file with orders
                
            Returns:
                JSON string with ATP results
            """
            try:
                order_lines = self.excel_manager.read_orders_from_excel(filename)
                results = self.atp_engine.batch_calculate_atp(
                    order_lines,
                    self.inventory,
                    self.purchase_orders
                )
                self.current_results = results
                
                return self._format_results_json(results)
            except Exception as e:
                return json.dumps({"error": str(e)})
        
        @self.user_proxy.register_for_execution()
        @self.atp_agent.register_for_llm(description="Get inventory levels for specific items")
        def get_inventory_info(items_json: str) -> str:
            """
            Get inventory information for items
            
            Args:
                items_json: JSON array of item codes
                
            Returns:
                JSON string with inventory data
            """
            try:
                items = json.loads(items_json)
                relevant_inv = [inv for inv in self.inventory if inv.item in items]
                
                return json.dumps([{
                    'item': inv.item,
                    'location': inv.location,
                    'on_hand_qty': inv.on_hand_qty,
                    'safety_stock_qty': inv.safety_stock_qty,
                    'available': max(0, inv.on_hand_qty - inv.safety_stock_qty)
                } for inv in relevant_inv], indent=2)
            except Exception as e:
                return json.dumps({"error": str(e)})
        
        @self.user_proxy.register_for_execution()
        @self.atp_agent.register_for_llm(description="Get purchase order information for items")
        def get_po_info(items_json: str) -> str:
            """
            Get purchase order information for items
            
            Args:
                items_json: JSON array of item codes
                
            Returns:
                JSON string with PO data
            """
            try:
                items = json.loads(items_json)
                relevant_pos = [po for po in self.purchase_orders if po.item in items]
                
                return json.dumps([{
                    'po_id': po.po_id,
                    'item': po.item,
                    'quantity': po.quantity,
                    'expected_delivery_date': po.expected_delivery_date.isoformat(),
                    'confirmed': po.confirmed
                } for po in relevant_pos], indent=2)
            except Exception as e:
                return json.dumps({"error": str(e)})
        
        @self.user_proxy.register_for_execution()
        @self.analyst_agent.register_for_llm(description="Analyze ATP results and generate insights")
        def analyze_atp_results() -> str:
            """
            Analyze ATP results and provide insights
            
            Returns:
                JSON string with analysis
            """
            if not self.current_results:
                return json.dumps({"message": "No results to analyze"})
            
            results = self.current_results
            analysis = {
                'total_lines': len(results),
                'available': sum(1 for r in results if r.status == 'AVAILABLE'),
                'partial': sum(1 for r in results if r.status == 'PARTIAL'),
                'backorder': sum(1 for r in results if r.status == 'BACKORDER'),
                'on_time_rate': f"{sum(1 for r in results if r.earliest_available_date and r.earliest_available_date <= r.requested_date) / len(results) * 100:.1f}%",
                'high_priority_issues': [
                    f"{r.order_id}-{r.line_id}: {r.item}" 
                    for r in results 
                    if r.priority == 'HIGH' and r.status != 'AVAILABLE'
                ],
                'items_with_issues': list(set([
                    r.item for r in results if r.status == 'BACKORDER'
                ]))
            }
            
            return json.dumps(analysis, indent=2)
        
        @self.user_proxy.register_for_execution()
        @self.analyst_agent.register_for_llm(description="Export ATP results to Excel file")
        def export_to_excel(filename: str = "atp_results_autogen.xlsx") -> str:
            """
            Export current ATP results to Excel
            
            Args:
                filename: Output filename
                
            Returns:
                Success message
            """
            if not self.current_results:
                return "No results to export"
            
            try:
                self.excel_manager.write_results_to_excel(self.current_results, filename)
                return f"Results exported to {filename}"
            except Exception as e:
                return f"Error exporting: {str(e)}"
    
    def _format_results_json(self, results: List[ATPResult]) -> str:
        """Format ATP results as JSON"""
        formatted_results = []
        
        for result in results:
            formatted_results.append({
                'order_id': result.order_id,
                'line_id': result.line_id,
                'item': result.item,
                'requested_quantity': result.requested_quantity,
                'requested_date': result.requested_date.isoformat(),
                'available_quantity': result.available_quantity,
                'earliest_available_date': result.earliest_available_date.isoformat() if result.earliest_available_date else None,
                'status': result.status,
                'source': result.source,
                'days_delay': (result.earliest_available_date - result.requested_date).days if result.earliest_available_date else 0,
                'messages': result.messages
            })
        
        return json.dumps(formatted_results, indent=2)
    
    def process_excel_with_conversation(self, excel_file: str, user_message: str = None):
        """
        Process Excel file with conversational AI
        
        Args:
            excel_file: Path to input Excel file
            user_message: Optional custom message
        """
        if user_message is None:
            user_message = f"""Please perform an ATP check on the orders in {excel_file}.
            
After checking availability:
1. Provide a summary of the results
2. Identify any high-priority orders that cannot be fulfilled on time
3. Suggest actions for items with availability issues
4. Export the detailed results to Excel

Please proceed with the analysis."""
        
        self.user_proxy.initiate_chat(
            self.atp_agent,
            message=user_message
        )
    
    def process_batch_silent(self, excel_file: str) -> List[ATPResult]:
        """
        Process Excel file without conversation (direct execution)
        
        Args:
            excel_file: Path to input Excel file
            
        Returns:
            List of ATP results
        """
        order_lines = self.excel_manager.read_orders_from_excel(excel_file)
        results = self.atp_engine.batch_calculate_atp(
            order_lines,
            self.inventory,
            self.purchase_orders
        )
        self.current_results = results
        return results


def main():
    """Main execution function"""
    
    print("="*80)
    print("ATP CHECKER - AUTOGEN FRAMEWORK WITH EXCEL INTEGRATION")
    print("="*80)
    print()
    
    config = ATPConfig()
    
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key or api_key == "your-api-key-here":
        print("⚠️  OpenAI API key not found!")
        print("For conversational AI features, set OPENAI_API_KEY environment variable.")
        print("Running in SILENT MODE (without Autogen conversation)...\n")
        use_autogen = False
    else:
        print("✓ OpenAI API key detected")
        print("Running in AUTOGEN MODE (with conversational AI)...\n")
        use_autogen = True

    llm_config = {
        "config_list": [{
            "model": "gpt-4",
            "api_key": api_key if api_key else "dummy-key"
        }],
        "temperature": 0,
    }
    
    # Initialize agent with enable_autogen flag
    atp_agent = ATPAutogenAgent(config=config, llm_config=llm_config, enable_autogen=use_autogen)
    
    input_file = "sample_orders.xlsx"
    
    if not os.path.exists(input_file):
        print(f"Creating sample order file: {input_file}")
        ExcelManager.create_sample_order_excel(input_file)
        print(f"✓ Sample file created\n")
    
    print(f"Processing orders from: {input_file}\n")
    
    if use_autogen:
        
        print("="*80)
        print("AUTOGEN CONVERSATIONAL MODE")
        print("="*80)
        print("Initiating multi-agent conversation...\n")
        
        atp_agent.process_excel_with_conversation(input_file)
        
    else:
        
        print("="*80)
        print("DIRECT EXECUTION MODE")
        print("="*80)
        print()
        
        results = atp_agent.process_batch_silent(input_file)
        
    
        print(f"Processed {len(results)} order lines\n")
        
        available = sum(1 for r in results if r.status == 'AVAILABLE')
        partial = sum(1 for r in results if r.status == 'PARTIAL')
        backorder = sum(1 for r in results if r.status == 'BACKORDER')
        
        print("Summary:")
        print(f"  Available:  {available} ({available/len(results)*100:.1f}%)")
        print(f"  Partial:    {partial} ({partial/len(results)*100:.1f}%)")
        print(f"  Backorder:  {backorder} ({backorder/len(results)*100:.1f}%)")
        print()
        
        # Display ALL order lines sorted by earliest available date
        print("="*80)
        print(f"ATP CHECK RESULTS - ALL {len(results)} ORDER LINES")
        print("Sorted by Earliest Available Date (Earliest to Latest)")
        print("="*80)
        
        # Sort all results by earliest available date
        sorted_results = sorted(results, key=lambda x: (x.earliest_available_date if x.earliest_available_date else date.today() + timedelta(days=9999)))
        
        for i, result in enumerate(sorted_results, 1):
            days_from_today = (result.earliest_available_date - date.today()).days if result.earliest_available_date else 0
            status_icon = "✓" if result.status == "AVAILABLE" else "⚠" if result.status == "PARTIAL" else "✗"
            
            print(f"{i:3}. [{status_icon}] {result.order_id:10} Line {result.line_id:3} | {result.item:20} | "
                  f"Qty: {result.requested_quantity:3}/{result.available_quantity:3} | "
                  f"Date: {result.earliest_available_date} ({days_from_today:+3d} days) | "
                  f"{result.status:10} | {result.source}")
        
        print("="*80)
        print()
        
        output_file = "atp_results_autogen.xlsx"
        ExcelManager.write_results_to_excel(results, output_file)
        print(f"✓ Results exported to: {output_file}")
        print(f"  - Sheet 1: ATP Results (all {len(results)} lines)")
        print(f"  - Sheet 2: Earliest Date Per Item (unique items sorted by date) ⭐")
        print(f"  - Sheet 3: Summary")
        print(f"  - Sheet 4: By Status")
        print(f"  - Sheet 5: By Item")
    
    print()
    print("="*80)
    print("✓ ATP CHECK COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
