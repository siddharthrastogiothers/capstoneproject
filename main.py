"""
Main execution file for ATP Checker Agent
Demonstrates how to use the ATP Checker Agent with sample data
"""

from datetime import date, timedelta
from Models import OrderLine
from Config import AppConfig, Policy, ERPConfig
from atp_agent import ATPCheckerAgent


def main():
    """Main execution function"""
    
    print("="*70)
    print("ATP Checker Agent - Available-to-Promise System")
    print("="*70)
    print()
    
    # Configure the application
    config = AppConfig(
        policy=Policy(
            allow_partial_ship=True,
            consider_unconfirmed_pos=False,
            default_safety_stock=10,
            default_lead_time_days=14,
            receiving_buffer_days=1,
            quality_buffer_days=1,
            transit_days_default=2
        ),
        erp=ERPConfig(
            base_url="https://erp.example.com/api",
            api_key="DEMO_API_KEY",
            timeout_seconds=20
        )
    )
    
    # Initialize ATP Checker Agent
    # Note: For production, provide proper LLM config with valid API key
    llm_config = {
        "config_list": [{
            "model": "gpt-4",
            "api_key": "your-openai-api-key-here"  # Replace with actual key
        }],
        "temperature": 0,
    }
    
    print("Initializing ATP Checker Agent...")
    atp_agent = ATPCheckerAgent(config=config, llm_config=llm_config)
    print("✓ Agent initialized successfully")
    print()
    
    # Create sample order lines
    today = date.today()
    order_lines = [
        OrderLine(
            order_id="SO-1001",
            line_id="001",
            item="WIDGET-A",
            quantity=50,
            requested_date=today + timedelta(days=3),
            ship_from="MAIN",
            priority="HIGH"
        ),
        OrderLine(
            order_id="SO-1001",
            line_id="002",
            item="WIDGET-B",
            quantity=30,
            requested_date=today + timedelta(days=5),
            ship_from="MAIN",
            priority="NORMAL"
        ),
        OrderLine(
            order_id="SO-1002",
            line_id="001",
            item="WIDGET-C",
            quantity=75,
            requested_date=today + timedelta(days=7),
            ship_from="MAIN",
            priority="HIGH"
        ),
    ]
    
    print(f"Processing {len(order_lines)} order lines...")
    print()
    
    # Process ATP request
    try:
        results = atp_agent.process_atp_request(
            order_lines=order_lines,
            request_description="Check availability for customer order SO-1001 and SO-1002"
        )
        
        print("ATP Check Results:")
        print("="*70)
        
        # Display results
        for result in results:
            print(f"\nOrder: {result.order_id} | Line: {result.line_id}")
            print(f"Item: {result.item}")
            print(f"Requested: {result.requested_quantity} units by {result.requested_date}")
            print(f"Status: {result.status}")
            print(f"Available Quantity: {result.available_quantity}")
            print(f"Earliest Available Date: {result.earliest_available_date}")
            print(f"Source: {result.source}")
            
            if result.messages:
                print(f"Details:")
                for msg in result.messages:
                    print(f"  - {msg}")
            
            print("-"*70)
        
        # Generate and display summary report
        print("\n")
        summary = atp_agent.get_summary_report(results)
        print(summary)
        
        # Export results to JSON
        import json
        results_export = [{
            'order_id': r.order_id,
            'line_id': r.line_id,
            'item': r.item,
            'requested_quantity': r.requested_quantity,
            'requested_date': r.requested_date.isoformat(),
            'available_quantity': r.available_quantity,
            'earliest_available_date': r.earliest_available_date.isoformat() if r.earliest_available_date else None,
            'status': r.status,
            'source': r.source,
            'messages': r.messages
        } for r in results]
        
        with open('atp_results.json', 'w') as f:
            json.dump(results_export, f, indent=2)
        
        print("\n✓ Results exported to atp_results.json")
        
    except Exception as e:
        print(f"Error processing ATP request: {e}")
        import traceback
        traceback.print_exc()


def demo_conversational_mode():
    """
    Demonstrate conversational mode with Autogen
    Note: Requires valid OpenAI API key
    """
    
    print("\n" + "="*70)
    print("ATP Checker Agent - Conversational Mode Demo")
    print("="*70)
    print()
    
    config = AppConfig()
    
    llm_config = {
        "config_list": [{
            "model": "gpt-4",
            "api_key": "your-openai-api-key-here"  # Replace with actual key
        }],
        "temperature": 0,
    }
    
    atp_agent = ATPCheckerAgent(config=config, llm_config=llm_config)
    
    # Example conversational request
    message = """
    I need to check availability for the following order:
    - Order ID: SO-2001
    - Item WIDGET-A: 100 units needed by next week
    - Item WIDGET-B: 50 units needed by next week
    
    Can you check if we can fulfill this order and provide earliest ship dates?
    """
    
    print("User Request:")
    print(message)
    print()
    
    try:
        response = atp_agent.process_conversational_request(message)
        print("Agent Response:")
        print(response)
    except Exception as e:
        print(f"Note: Conversational mode requires valid OpenAI API key")
        print(f"Error: {e}")


if __name__ == "__main__":
    # Run main ATP check
    main()
    
    # Optionally run conversational demo
    # Uncomment the line below if you have a valid OpenAI API key
    # demo_conversational_mode()
