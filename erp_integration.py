"""
ERP Integration Module
Handles API calls to ERP system for inventory and purchase order data
"""

import requests
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from Models import InventorySnapshot, PurchaseOrder
from Config import ERPConfig
import json


class ERPIntegration:
    """Handles integration with ERP/MM module"""
    
    def __init__(self, config: ERPConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {config.api_key}',
            'Content-Type': 'application/json'
        })
    
    def get_inventory_snapshot(
        self,
        items: Optional[List[str]] = None,
        locations: Optional[List[str]] = None
    ) -> List[InventorySnapshot]:
        """
        Fetch current inventory snapshot from ERP
        
        Args:
            items: List of item codes to filter (None = all items)
            locations: List of locations to filter (None = all locations)
            
        Returns:
            List of InventorySnapshot objects
        """
        endpoint = f"{self.config.base_url}/inventory/snapshot"
        
        params = {}
        if items:
            params['items'] = ','.join(items)
        if locations:
            params['locations'] = ','.join(locations)
        
        try:
            response = self.session.get(
                endpoint,
                params=params,
                timeout=self.config.timeout_seconds
            )
            response.raise_for_status()
            
            data = response.json()
            
            return [self._parse_inventory_record(record) for record in data.get('inventory', [])]
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching inventory: {e}")
            # Return mock data for testing/fallback
            return self._get_mock_inventory(items, locations)
    
    def get_open_purchase_orders(
        self,
        items: Optional[List[str]] = None,
        locations: Optional[List[str]] = None
    ) -> List[PurchaseOrder]:
        """
        Fetch open purchase orders from ERP
        
        Args:
            items: List of item codes to filter (None = all items)
            locations: List of locations to filter (None = all locations)
            
        Returns:
            List of PurchaseOrder objects
        """
        endpoint = f"{self.config.base_url}/purchasing/open-orders"
        
        params = {}
        if items:
            params['items'] = ','.join(items)
        if locations:
            params['locations'] = ','.join(locations)
        
        try:
            response = self.session.get(
                endpoint,
                params=params,
                timeout=self.config.timeout_seconds
            )
            response.raise_for_status()
            
            data = response.json()
            
            return [self._parse_po_record(record) for record in data.get('purchase_orders', [])]
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching purchase orders: {e}")
            # Return mock data for testing/fallback
            return self._get_mock_purchase_orders(items, locations)
    
    def get_lead_time(self, item: str, supplier: Optional[str] = None) -> int:
        """
        Fetch lead time for an item from ERP
        
        Args:
            item: Item code
            supplier: Supplier code (optional)
            
        Returns:
            Lead time in days
        """
        endpoint = f"{self.config.base_url}/items/{item}/lead-time"
        
        params = {}
        if supplier:
            params['supplier'] = supplier
        
        try:
            response = self.session.get(
                endpoint,
                params=params,
                timeout=self.config.timeout_seconds
            )
            response.raise_for_status()
            
            data = response.json()
            return data.get('lead_time_days', 14)
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching lead time: {e}")
            return 14  # Default fallback
    
    def _parse_inventory_record(self, record: Dict[str, Any]) -> InventorySnapshot:
        """Parse ERP inventory record to InventorySnapshot"""
        return InventorySnapshot(
            item=record['item_code'],
            location=record.get('location', 'MAIN'),
            on_hand_qty=int(record['on_hand_quantity']),
            safety_stock_qty=int(record.get('safety_stock', 0)),
            last_updated=self._parse_datetime(record.get('last_updated', datetime.now().isoformat()))
        )
    
    def _parse_po_record(self, record: Dict[str, Any]) -> PurchaseOrder:
        """Parse ERP purchase order record to PurchaseOrder"""
        return PurchaseOrder(
            po_id=record['po_number'],
            item=record['item_code'],
            quantity=int(record['quantity']),
            expected_delivery_date=self._parse_date(record['expected_delivery_date']),
            location=record.get('destination_location', 'MAIN'),
            confirmed=record.get('status', '').upper() == 'CONFIRMED'
        )
    
    def _parse_datetime(self, dt_string: str) -> datetime:
        """Parse datetime string from ERP"""
        try:
            return datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        except:
            return datetime.now()
    
    def _parse_date(self, date_string: str) -> date:
        """Parse date string from ERP"""
        try:
            return datetime.fromisoformat(date_string).date()
        except:
            return date.today()
    
    # Mock data methods for testing
    def _get_mock_inventory(
        self,
        items: Optional[List[str]] = None,
        locations: Optional[List[str]] = None
    ) -> List[InventorySnapshot]:
        """Generate mock inventory data for testing"""
        mock_data = [
            InventorySnapshot(
                item="WIDGET-A",
                location="MAIN",
                on_hand_qty=100,
                safety_stock_qty=20,
                last_updated=datetime.now()
            ),
            InventorySnapshot(
                item="WIDGET-B",
                location="MAIN",
                on_hand_qty=50,
                safety_stock_qty=10,
                last_updated=datetime.now()
            ),
            InventorySnapshot(
                item="WIDGET-C",
                location="MAIN",
                on_hand_qty=5,
                safety_stock_qty=15,
                last_updated=datetime.now()
            ),
        ]
        
        if items:
            mock_data = [inv for inv in mock_data if inv.item in items]
        if locations:
            mock_data = [inv for inv in mock_data if inv.location in locations]
        
        return mock_data
    
    def _get_mock_purchase_orders(
        self,
        items: Optional[List[str]] = None,
        locations: Optional[List[str]] = None
    ) -> List[PurchaseOrder]:
        """Generate mock purchase order data for testing"""
        from datetime import timedelta
        
        mock_data = [
            PurchaseOrder(
                po_id="PO-001",
                item="WIDGET-C",
                quantity=100,
                expected_delivery_date=date.today() + timedelta(days=7),
                location="MAIN",
                confirmed=True
            ),
            PurchaseOrder(
                po_id="PO-002",
                item="WIDGET-A",
                quantity=200,
                expected_delivery_date=date.today() + timedelta(days=14),
                location="MAIN",
                confirmed=True
            ),
        ]
        
        if items:
            mock_data = [po for po in mock_data if po.item in items]
        if locations:
            mock_data = [po for po in mock_data if po.location in locations]
        
        return mock_data
