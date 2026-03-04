#!/usr/bin/env python
"""
Automatic Invoice Generator - Creates a beautiful demo invoice
Run this to see what Vanta Pilot can do!
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

def main():
    """Generate a complete demo invoice automatically."""
    
    print("=" * 70)
    print("🚀 Vanta Pilot - Automatic Invoice Generator")
    print("=" * 70)
    
    try:
        # Import services
        from services.customer_service import CustomerService
        from services.invoice_service import InvoiceService
        from services.pdf_service import PDFInvoiceService
        
        # Initialize services
        customer_service = CustomerService()
        invoice_service = InvoiceService()
        pdf_service = PDFInvoiceService()
        
        # STEP 1: Create a customer (if not exists)
        print("\n📋 Step 1: Setting up customer...")
        
        # Check if customer already exists
        customers = customer_service.get_all_customers()
        if customers:
            customer = customers[0]
            customer_id = customer['id']
            print(f"   ✅ Using existing customer: {customer['name']} {customer['surname']}")
        else:
            # Create a new customer
            customer_id = customer_service.create_customer(
                name="Demo",
                surname="Customer",
                id_number="9876543210123",
                company="Demo Company (Pty) Ltd",
                email="demo@example.com",
                phone="+27 11 123 4567"
            )
            print(f"   ✅ Created new customer with ID: {customer_id}")
        
        # STEP 2: Create invoice items
        print("\n📦 Step 2: Preparing invoice items...")
        
        items = [
            ("Professional Web Design - 5 page corporate website", 1, 4500.00),
            ("Premium Web Hosting - 12 months (includes SSL, backups)", 12, 150.00),
            ("SEO Optimization Package - Initial setup & 3 months", 1, 3500.00),
            ("Maintenance & Support Contract - 6 months", 6, 650.00),
            ("Domain Registration - 2 years (.co.za)", 2, 150.00),
            ("Email Hosting - 5 mailboxes (12 months)", 12, 50.00)
        ]
        
        print(f"   📊 Items:")
        subtotal = 0
        for desc, qty, price in items:
            line_total = qty * price
            subtotal += line_total
            print(f"      • {desc[:40]:<40} x{qty:>2} @ R{price:>7.2f} = R{line_total:>9.2f}")
        
        vat = subtotal * 0.15
        total = subtotal + vat
        
        print(f"\n   💰 Totals:")
        print(f"      Subtotal: R{subtotal:,.2f}")
        print(f"      VAT (15%): R{vat:,.2f}")
        print(f"      GRAND TOTAL: R{total:,.2f}")
        
        # STEP 3: Create the invoice
        print("\n🧾 Step 3: Creating invoice in database...")
        
        due_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        invoice_id = invoice_service.create_invoice(
            customer_id=customer_id,
            items=items,
            description="Digital Services & Web Development - February 2026",
            due_days=30
        )
        
        if not invoice_id:
            print("❌ Failed to create invoice")
            return 1
        
        print(f"   ✅ Invoice created with ID: {invoice_id}")
        
        # STEP 4: Generate PDF
        print("\n📄 Step 4: Generating professional PDF invoice...")
        
        invoice = invoice_service.get_invoice(invoice_id)
        if invoice:
            pdf_path = pdf_service.generate_invoice_from_db(invoice)
            if pdf_path:
                print(f"\n   ✅ PDF generated successfully!")
                print(f"   📁 Location: {pdf_path}")
                print(f"   📄 Filename: {pdf_path.name}")
            else:
                print("   ❌ PDF generation failed")
        
        # STEP 5: Display invoice summary
        print("\n" + "=" * 70)
        print("✅ INVOICE GENERATED SUCCESSFULLY!")
        print("=" * 70)
        print(f"\n📋 INVOICE SUMMARY:")
        print(f"   Invoice #: INV-{datetime.now().strftime('%Y%m%d')}-{invoice_id:03d}")
        print(f"   Date: {datetime.now().strftime('%Y-%m-%d')}")
        print(f"   Due Date: {due_date}")
        print(f"   Customer: Demo Customer")
        print(f"   Company: Demo Company (Pty) Ltd")
        print(f"   Items: {len(items)} line items")
        print(f"   Subtotal: R{subtotal:,.2f}")
        print(f"   VAT (15%): R{vat:,.2f}")
        print(f"   TOTAL: R{total:,.2f}")
        print(f"\n📁 PDF Location: invoices/Invoice_INV-{datetime.now().strftime('%Y%m%d')}-{invoice_id:03d}_*.pdf")
        print("\n" + "=" * 70)
        print("🎉 OPEN THE PDF TO SEE YOUR BEAUTIFUL INVOICE!")
        print("=" * 70)
        
        # Open the PDF automatically (Windows)
        if pdf_path and pdf_path.exists():
            import os
            os.startfile(str(pdf_path))
            print("\n📎 PDF opened automatically!")
        
        return 0
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Make sure you're in the invoice_pro_system directory")
        return 1
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
