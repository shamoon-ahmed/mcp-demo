"""
Dynamic Table Structure Analyzer
Analyzes and stores Google Sheets table structures for any business type
"""

import json
import os
import re
from typing import Dict, List, Tuple, Any, Optional
from googleapiclient.discovery import build

class TableStructureAnalyzer:
    """
    Analyzes table structure and creates intelligent column mappings
    for any business type and any table layout
    """
    
    # Universal column patterns for intelligent mapping
    UNIVERSAL_PATTERNS = {
        # Identifiers
        "order_id": ["order_id", "orderid", "order_no", "order_number", "id", "ref", "reference"],
        "item_id": ["item_id", "itemid", "product_id", "productid", "sku", "code"],
        
        # Customer Information
        "customer_name": ["customer_name", "customer", "name", "client_name", "buyer", "client"],
        "customer_email": ["customer_email", "email", "contact_email", "client_email"],
        "customer_phone": ["customer_phone", "phone", "contact", "mobile", "cell", "contact_number"],
        "customer_address": ["customer_address", "address", "delivery_address", "location"],
        
        # Item/Product Information
        "item_name": ["item_name", "item", "product_name", "product", "menu_item", "dish", "service", "name"],
        "quantity": ["quantity", "qty", "amount", "count", "pieces", "units"],
        "price": ["price", "unit_price", "cost", "rate", "amount", "fee"],
        "total": ["total", "subtotal", "grand_total", "final_amount"],
        
        # Order Details
        "payment_method": ["payment_method", "payment", "payment_mode", "pay_method"],
        "payment_status": ["payment_status", "status", "order_status", "state"],
        "delivery_method": ["delivery_method", "delivery", "shipping", "fulfillment"],
        "notes": ["notes", "remarks", "comments", "special_requests", "instructions"],
        "date": ["date", "order_date", "timestamp", "created_at", "time"],
        
        # Business Specific
        "category": ["category", "type", "group", "section"],
        "description": ["description", "details", "info", "specs"],
        "availability": ["availability", "available", "status", "stock", "in_stock"]
    }
    
    @staticmethod
    def analyze_sheet_structure(service, workbook_id: str, worksheet_name: str) -> Dict[str, Any]:
        """
        Analyzes a sheet and returns its complete structure
        """
        try:
            print(f"📊 Analyzing structure of '{worksheet_name}'...")
            
            # Get sheet data with a reasonable range
            range_name = f"{worksheet_name}!A1:ZZ100"
            result = service.spreadsheets().values().get(
                spreadsheetId=workbook_id,
                range=range_name,
                valueRenderOption='UNFORMATTED_VALUE'
            ).execute()
            
            rows = result.get('values', [])
            if not rows:
                return {"error": "No data found in sheet"}
            
            # Find table boundaries
            table_info = TableStructureAnalyzer._find_table_boundaries(rows)
            
            if not table_info["found"]:
                return {"error": "No table structure found"}
            
            # Analyze column types and create mappings
            column_mapping = TableStructureAnalyzer._create_column_mapping(table_info["headers"])
            
            # Detect business type
            business_type = TableStructureAnalyzer._detect_business_type(table_info["headers"], rows)
            
            structure = {
                "start_row": table_info["start_row"],
                "start_col": table_info["start_col"],
                "end_row": table_info["end_row"],
                "end_col": table_info["end_col"],
                "headers": table_info["headers"],
                "column_mapping": column_mapping,
                "business_type": business_type,
                "total_rows": len([row for row in rows[table_info["start_row"]+1:] if any(cell for cell in row)]),
                "analysis_timestamp": json.dumps({"timestamp": "analyzed"})
            }
            
            print(f"✅ Structure analyzed: {len(table_info['headers'])} columns, business type: {business_type}")
            return structure
            
        except Exception as e:
            print(f"❌ Error analyzing sheet structure: {e}")
            return {"error": str(e)}
    
    @staticmethod
    def _find_table_boundaries(rows: List[List[Any]]) -> Dict[str, Any]:
        """
        Finds where the actual table starts and ends
        """
        if not rows:
            return {"found": False}
        
        # Find first row with substantial data (headers)
        start_row = -1
        for i, row in enumerate(rows):
            non_empty = sum(1 for cell in row if str(cell).strip())
            if non_empty >= 2:  # At least 2 columns to be considered a table
                start_row = i
                break
        
        if start_row == -1:
            return {"found": False}
        
        # Find column boundaries
        start_col = len(rows[start_row])
        end_col = 0
        
        for row in rows[start_row:start_row+10]:  # Check first 10 rows for column span
            for j, cell in enumerate(row):
                if str(cell).strip():
                    start_col = min(start_col, j)
                    end_col = max(end_col, j)
        
        # Extract headers
        header_row = rows[start_row]
        headers = []
        for j in range(start_col, min(end_col + 1, len(header_row))):
            header = header_row[j] if j < len(header_row) else ""
            headers.append(str(header).strip())
        
        # Find end of data
        end_row = start_row
        for i in range(start_row + 1, min(len(rows), start_row + 100)):
            row = rows[i] if i < len(rows) else []
            if any(str(cell).strip() for cell in row[start_col:end_col+1]):
                end_row = i
        
        return {
            "found": True,
            "start_row": start_row,
            "start_col": start_col,
            "end_row": end_row,
            "end_col": end_col,
            "headers": headers
        }
    
    @staticmethod
    def _create_column_mapping(headers: List[str]) -> Dict[str, Any]:
        """
        Creates intelligent column mapping based on header names
        """
        mapping = {}
        
        for index, header in enumerate(headers):
            if not header:
                continue
                
            clean_header = TableStructureAnalyzer._clean_header(header)
            
            # Try to match with universal patterns
            best_match = None
            best_confidence = 0
            
            for field_type, patterns in TableStructureAnalyzer.UNIVERSAL_PATTERNS.items():
                for pattern in patterns:
                    confidence = TableStructureAnalyzer._calculate_match_confidence(clean_header, pattern)
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_match = field_type
            
            # Only map if confidence is high enough
            if best_match and best_confidence > 0.7:
                mapping[best_match] = {
                    "header": header,
                    "index": index,
                    "confidence": best_confidence,
                    "clean_header": clean_header
                }
        
        return mapping
    
    @staticmethod
    def _calculate_match_confidence(header: str, pattern: str) -> float:
        """
        Calculates how well a header matches a pattern
        """
        if header == pattern:
            return 1.0
        
        if pattern in header:
            return 0.9
        
        if header.startswith(pattern) or header.endswith(pattern):
            return 0.8
        
        # Check for partial word matches
        header_words = header.split('_')
        pattern_words = pattern.split('_')
        
        if any(word in header_words for word in pattern_words):
            return 0.7
        
        return 0.0
    
    @staticmethod
    def _clean_header(header: str) -> str:
        """
        Cleans header for pattern matching
        """
        if not header:
            return ""
        return re.sub(r'[^a-z0-9_]', '_', header.strip().lower()).strip('_')
    
    @staticmethod
    def _detect_business_type(headers: List[str], sample_rows: List[List[Any]]) -> str:
        """
        Detects business type based on headers and sample data
        """
        headers_text = " ".join(headers).lower()
        sample_text = " ".join([str(cell) for row in sample_rows[:5] for cell in row]).lower()
        all_text = headers_text + " " + sample_text
        
        business_indicators = {
            "restaurant": ["menu", "dish", "food", "cuisine", "meal", "recipe", "beverage"],
            "retail": ["product", "item", "sku", "inventory", "stock", "brand"],
            "services": ["service", "appointment", "consultation", "session", "booking"],
            "hotel": ["room", "suite", "reservation", "guest", "accommodation"],
            "healthcare": ["patient", "doctor", "appointment", "treatment", "medical"],
            "education": ["student", "course", "class", "subject", "grade", "lesson"],
            "beauty": ["treatment", "appointment", "client", "service", "beauty"],
            "fitness": ["member", "workout", "class", "trainer", "exercise"]
        }
        
        best_match = "general"
        best_score = 0
        
        for business_type, indicators in business_indicators.items():
            score = sum(1 for indicator in indicators if indicator in all_text)
            if score > best_score:
                best_score = score
                best_match = business_type
        
        return best_match

def save_structure_to_connection(inventory_structure: Dict, orders_structure: Dict, refresh_token: str, 
                               inventory_config: Dict, orders_config: Dict):
    """
    Saves complete structure information to connection.json
    """
    connection_data = {
        "inventory": {
            "workbook_id": inventory_config["workbook_id"],
            "worksheet_name": inventory_config["worksheet_name"],
            "table_structure": inventory_structure
        },
        "orders": {
            "workbook_id": orders_config["workbook_id"],
            "worksheet_name": orders_config["worksheet_name"],
            "table_structure": orders_structure
        },
        "refresh_token": refresh_token,
        "configuration_timestamp": json.dumps({"configured": True})
    }
    
    # Save to connection.json
    connection_file = os.path.join(os.path.dirname(__file__), "connection.json")
    with open(connection_file, 'w') as f:
        json.dump(connection_data, f, indent=2)
    
    print("✅ Table structures saved to connection.json")
    return connection_data

if __name__ == "__main__":
    print("📊 Table Structure Analyzer - Ready for integration!")