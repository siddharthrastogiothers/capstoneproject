"""
ATP Checker Agent using Autogen Framework
Orchestrates ATP checking process and provides intelligent responses
"""

import autogen
from typing import List, Dict, Any, Optional
from datetime import date, datetime
import json

from Models import OrderLine, ATPResult, ATPCheckRequest
from Config import AppConfig, Policy, ERPConfig
from atp_engine import ATPEngine
from erp_integration import ERPIntegration


class ATPCheckerAgent:
    """
    ATP Checker Agent using Autogen
    Handles ATP requests and provides availability information
    """
    
    def __init__(
        self,
        config: AppConfig,
        llm_config: Optional[Dict[str, Any]] = None
    ):
        self.config = config
        self.atp_engine = ATPEngine(config.policy)
        self.erp_integration = ERPIntegration(config.erp)
        
        # Default LLM config for Autogen
        if llm_config is None:
            llm_config = {
                "config_list": [{
                    "model": "gpt-4",
                    "api_key": "your-api-key-here"
                }],
                "temperature": 0,
            }
        
        self.llm_config = llm_config
        
        # Initialize Autogen agents
        self._setup_agents()
    
    def _setup_agents(self):
        """Setup Autogen conversable agents"""
        
        # ATP Checker Agent - handles ATP calculations
        self.atp_agent = autogen.AssistantAgent(
            name="ATP_Checker",
            llm_config=self.llm_config,
            system_message="""You are an ATP (Available-to-Promise) Checker Agent.
Your role is to:
1. Analyze order requests and check product availability
2. Calculate earliest ship dates based on inventory and lead times
3. Validate stock availability against safety stock rules
4. Consider inbound purchase orders for future availability
5. Provide clear, actionable availability information

When processing ATP requests:
- Check current inventory levels
- Apply safety stock rules
- Consider open purchase orders
- Calculate lead times for unavailable items
- Return earliest available dates per line item

Always provide detailed explanations of availability status and any constraints."""
        )
        
        # Data Fetcher Agent - handles ERP data retrieval
        self.data_agent = autogen.AssistantAgent(
            name="Data_Fetcher",
            llm_config=self.llm_config,
            system_message="""You are a Data Fetcher Agent responsible for retrieving data from ERP systems.
Your role is to:
1. Fetch inventory snapshots from ERP
2. Retrieve open purchase orders
3. Get lead time information
4. Validate data quality and freshness

Always ensure data is current and complete before forwarding to ATP calculations."""
        )
        
        # User Proxy - represents the user/system making requests
        self.user_proxy = autogen.UserProxyAgent(
            name="ATP_Requestor",
            human_input_mode="NEVER",
            max_consecutive_auto_reply=10,
            code_execution_config={"use_docker": False}
        )
        
        # Register function for ATP checking
        self._register_functions()
    
    def _register_functions(self):
        """Register callable functions for agents"""
        
        @self.user_proxy.register_for_execution()
        @self.atp_agent.register_for_llm(description="Check ATP for order lines and return availability results")
        def check_atp_availability(order_lines_json: str) -> str:
            """
            Check ATP for given order lines
            
            Args:
                order_lines_json: JSON string containing order line details
                
            Returns:
                JSON string with ATP results
            """
            return self._execute_atp_check(order_lines_json)
        
        @self.user_proxy.register_for_execution()
        @self.data_agent.register_for_llm(description="Fetch inventory data from ERP")
        def fetch_inventory_data(items_json: str) -> str:
            """
            Fetch inventory data from ERP
            
            Args:
                items_json: JSON string with list of items
                
            Returns:
                JSON string with inventory data
            """
            items = json.loads(items_json)
            inventory = self.erp_integration.get_inventory_snapshot(items=items)
            
            return json.dumps([{
                'item': inv.item,
                'location': inv.location,
                'on_hand_qty': inv.on_hand_qty,
                'safety_stock_qty': inv.safety_stock_qty,
                'last_updated': inv.last_updated.isoformat()
            } for inv in inventory])
        
        @self.user_proxy.register_for_execution()
        @self.data_agent.register_for_llm(description="Fetch purchase order data from ERP")
        def fetch_po_data(items_json: str) -> str:
            """
            Fetch purchase order data from ERP
            
            Args:
                items_json: JSON string with list of items
                
            Returns:
                JSON string with PO data
            """
            items = json.loads(items_json)
            pos = self.erp_integration.get_open_purchase_orders(items=items)
            
            return json.dumps([{
                'po_id': po.po_id,
                'item': po.item,
                'quantity': po.quantity,
                'expected_delivery_date': po.expected_delivery_date.isoformat(),
                'location': po.location,
                'confirmed': po.confirmed
            } for po in pos])
    
    def _execute_atp_check(self, order_lines_json: str) -> str:
        """Execute ATP check for order lines"""
        try:
            # Parse order lines
            order_lines_data = json.loads(order_lines_json)
            order_lines = []
            
            for line_data in order_lines_data:
                order_line = OrderLine(
                    order_id=line_data['order_id'],
                    line_id=line_data['line_id'],
                    item=line_data['item'],
                    quantity=int(line_data['quantity']),
                    requested_date=datetime.fromisoformat(line_data['requested_date']).date(),
                    ship_from=line_data.get('ship_from'),
                    priority=line_data.get('priority')
                )
                order_lines.append(order_line)
            
            # Get unique items
            items = list(set(line.item for line in order_lines))
            
            # Fetch data from ERP
            inventory = self.erp_integration.get_inventory_snapshot(items=items)
            purchase_orders = self.erp_integration.get_open_purchase_orders(items=items)
            
            # Calculate ATP
            results = self.atp_engine.batch_calculate_atp(
                order_lines,
                inventory,
                purchase_orders
            )
            
            # Format results
            return self._format_atp_results(results)
            
        except Exception as e:
            return json.dumps({
                'error': str(e),
                'message': 'Failed to process ATP check'
            })
    
    def _format_atp_results(self, results: List[ATPResult]) -> str:
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
                'messages': result.messages
            })
        
        return json.dumps(formatted_results, indent=2)
    
    def process_atp_request(
        self,
        order_lines: List[OrderLine],
        request_description: Optional[str] = None
    ) -> List[ATPResult]:
        """
        Process ATP request for given order lines
        
        Args:
            order_lines: List of order lines to check
            request_description: Optional description of the request
            
        Returns:
            List of ATP results
        """
        # Convert order lines to JSON
        order_lines_data = [{
            'order_id': line.order_id,
            'line_id': line.line_id,
            'item': line.item,
            'quantity': line.quantity,
            'requested_date': line.requested_date.isoformat(),
            'ship_from': line.ship_from,
            'priority': line.priority
        } for line in order_lines]
        
        order_lines_json = json.dumps(order_lines_data)
        
        # Execute ATP check directly
        results_json = self._execute_atp_check(order_lines_json)
        results_data = json.loads(results_json)
        
        # Convert back to ATPResult objects
        results = []
        for result_data in results_data:
            result = ATPResult(
                order_id=result_data['order_id'],
                line_id=result_data['line_id'],
                item=result_data['item'],
                requested_quantity=result_data['requested_quantity'],
                requested_date=datetime.fromisoformat(result_data['requested_date']).date(),
                available_quantity=result_data['available_quantity'],
                earliest_available_date=datetime.fromisoformat(result_data['earliest_available_date']).date() if result_data['earliest_available_date'] else None,
                status=result_data['status'],
                source=result_data['source'],
                messages=result_data['messages']
            )
            results.append(result)
        
        return results
    
    def process_conversational_request(self, message: str) -> str:
        """
        Process conversational ATP request using Autogen agents
        
        Args:
            message: Natural language request
            
        Returns:
            Agent response
        """
        # Initiate chat with ATP agent
        self.user_proxy.initiate_chat(
            self.atp_agent,
            message=message
        )
        
        # Get the last message from the conversation
        if self.user_proxy.chat_messages:
            last_messages = self.user_proxy.last_message(self.atp_agent)
            return last_messages.get('content', 'No response generated')
        
        return "Failed to process request"
    
    def get_summary_report(self, results: List[ATPResult]) -> str:
        """
        Generate summary report of ATP results
        
        Args:
            results: List of ATP results
            
        Returns:
            Formatted summary report
        """
        total_lines = len(results)
        available = sum(1 for r in results if r.status == "AVAILABLE")
        partial = sum(1 for r in results if r.status == "PARTIAL")
        backorder = sum(1 for r in results if r.status == "BACKORDER")
        
        report = f"""
ATP Check Summary Report
========================
Total Lines Checked: {total_lines}
Available: {available}
Partial: {partial}
Backorder: {backorder}

Detailed Results:
"""
        
        for result in results:
            report += f"""
Order: {result.order_id} | Line: {result.line_id}
Item: {result.item}
Requested Qty: {result.requested_quantity} | Requested Date: {result.requested_date}
Status: {result.status}
Available Qty: {result.available_quantity}
Earliest Date: {result.earliest_available_date}
Source: {result.source}
Notes: {'; '.join(result.messages)}
{'='*60}
"""
        
        return report
