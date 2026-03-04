# cli/main.py - COMPLETE FIXED VERSION
#!/usr/bin/env python3
"""
Vanta Pilot - Professional Invoice Management System
Command Line Interface
"""

import sys
import argparse
from typing import List, Tuple
from config.settings import config
from config.logging_config import logger
from services.customer_service import CustomerService
from services.invoice_service import InvoiceService
from services.payment_service import PaymentService
from services.pdf_service import PDFInvoiceService

try:
    from database.connection import db as _db
except Exception:
    _db = None

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def setup_argparse():
    """Setup command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Vanta Pilot - Professional Invoice Management System",
        epilog="Example: python -m cli.main customer add --name John --surname Doe --id 1234567890123"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Customer commands
    customer_parser = subparsers.add_parser('customer', help='Customer management')
    customer_sub = customer_parser.add_subparsers(dest='customer_cmd')
    
    # Add customer
    add_customer = customer_sub.add_parser('add', help='Add new customer')
    add_customer.add_argument('--name', required=True, help='First name')
    add_customer.add_argument('--surname', required=True, help='Last name')
    add_customer.add_argument('--id', required=True, help='ID number (13 digits)')
    add_customer.add_argument('--company', help='Company name')
    add_customer.add_argument('--email', help='Email address')
    add_customer.add_argument('--phone', help='Phone number')
    
    # List customers
    list_customer = customer_sub.add_parser('list', help='List all customers')
    list_customer.add_argument('--all', action='store_true', help='Include inactive customers')
    
    # Find customer
    find_customer = customer_sub.add_parser('find', help='Find customer')
    find_customer.add_argument('--id', help='ID number to search')
    find_customer.add_argument('--customer-id', help='Database ID to search')
    find_customer.add_argument('--include-inactive', action='store_true', help='Include inactive customers')
    
    # Delete customer
    delete_customer = customer_sub.add_parser('delete', help='Delete customer')
    delete_customer.add_argument('--id', type=int, required=True, help='Customer ID')
    delete_customer.add_argument('--hard', action='store_true', help='Permanent delete')
    
    # Invoice commands
    invoice_parser = subparsers.add_parser('invoice', help='Invoice management')
    invoice_sub = invoice_parser.add_subparsers(dest='invoice_cmd')
    
    # Create invoice
    create_invoice = invoice_sub.add_parser('create', help='Create new invoice')
    create_invoice.add_argument('--customer-id', type=int, required=True, help='Customer ID')
    create_invoice.add_argument('--items', nargs='+', required=True, 
                               help='Items in format "description:quantity:price"')
    create_invoice.add_argument('--description', help='Invoice description')
    create_invoice.add_argument('--due-days', type=int, default=30, help='Days until due')
    create_invoice.add_argument('--pdf', action='store_true', help='Generate PDF')
    
    # View invoice
    view_invoice = invoice_sub.add_parser('view', help='View invoice')
    view_invoice.add_argument('--id', type=int, required=True, help='Invoice ID')
    view_invoice.add_argument('--pdf', action='store_true', help='Generate PDF')
    
    # List invoices
    list_invoices = invoice_sub.add_parser('list', help='List invoices')
    list_invoices.add_argument('--customer-id', type=int, help='Filter by customer ID')
    list_invoices.add_argument('--limit', type=int, default=50, help='Limit results')
    
    # Update invoice status
    status_invoice = invoice_sub.add_parser('status', help='Update invoice status')
    status_invoice.add_argument('--id', type=int, required=True, help='Invoice ID')
    status_invoice.add_argument('--status', required=True,
                               choices=['draft', 'sent', 'paid', 'overdue', 'cancelled', 'partial'],
                               help='New status')
    
    # Payment commands (under invoice)
    payment_parser = invoice_sub.add_parser('payment', help='Payment management')
    payment_sub = payment_parser.add_subparsers(dest='payment_cmd')
    
    # Payment add
    add_payment = payment_sub.add_parser('add', help='Record a payment against an invoice')
    add_payment.add_argument('--invoice-id', type=int, required=True, help='Invoice ID')
    add_payment.add_argument('--amount', type=float, required=True, help='Payment amount')
    add_payment.add_argument('--method', default='bank_transfer', 
                            choices=['cash', 'credit_card', 'bank_transfer', 'cheque', 'digital_wallet'],
                            help='Payment method')
    add_payment.add_argument('--reference', help='Reference number')
    add_payment.add_argument('--notes', help='Payment notes')
    
    # Payment list
    list_payments = payment_sub.add_parser('list', help='List payments for an invoice')
    list_payments.add_argument('--invoice-id', type=int, required=True, help='Invoice ID')
    
    # Outstanding invoices
    outstanding = payment_sub.add_parser('outstanding', help='List outstanding invoices')
    outstanding.add_argument('--customer-id', type=int, help='Filter by customer ID')
    
    # Payment summary
    summary = payment_sub.add_parser('summary', help='Payment summary')
    summary.add_argument('--days', type=int, default=30, help='Number of days to summarize')
    
    # PDF commands
    pdf_parser = subparsers.add_parser('pdf', help='PDF generation')
    pdf_sub = pdf_parser.add_subparsers(dest='pdf_cmd')
    
    # Generate PDF for invoice
    generate_pdf = pdf_sub.add_parser('generate', help='Generate PDF for invoice')
    generate_pdf.add_argument('--invoice-id', type=int, required=True, help='Invoice ID')
    
    # Test PDF
    pdf_sub.add_parser('test', help='Generate test PDF')
    
    # System commands
    subparsers.add_parser('status', help='Check system status')
    subparsers.add_parser('init', help='Initialize database')
    
    return parser

def parse_items(items_args: List[str]) -> List[Tuple[str, int, float]]:
    """Parse command line items into structured format."""
    parsed_items = []
    
    for item_str in items_args:
        try:
            if item_str.count(':') == 2:
                desc, qty, price = item_str.split(':')
                parsed_items.append((desc, int(qty), float(price)))
            else:
                logger.warning(f"Invalid item format: {item_str}. Use 'description:quantity:price'")
        except ValueError as e:
            logger.error(f"Failed to parse item '{item_str}': {e}")
            raise
    
    return parsed_items

def handle_customer_command(args):
    """Handle customer-related commands."""
    service = CustomerService()
    
    if args.customer_cmd == 'add':
        try:
            customer_id = service.create_customer(
                name=args.name,
                surname=args.surname,
                id_number=args.id,
                company=args.company,
                email=args.email,
                phone=args.phone
            )
            if customer_id:
                print(f"\n✅ Customer added successfully! ID: {customer_id}")
                return 0
            return 1
        except ValueError as e:
            print(f"\n❌ Error: {e}")
            return 1
        except Exception as e:
            logger.error(f"Failed to add customer: {e}")
            print(f"\n❌ Unexpected error: {e}")
            return 1
    
    elif args.customer_cmd == 'list':
        customers = service.get_all_customers(active_only=not args.all)
        
        if not customers:
            print("\n📋 No customers found")
            return 0
        
        print(f"\n📋 Customers ({len(customers)}):")
        print("-" * 90)
        print(f"{'ID':<5} {'Name':<30} {'ID Number':<15} {'Company':<20} {'Status':<10}")
        print("-" * 90)
        
        for c in customers:
            name = f"{c['name']} {c['surname']}"
            status = "Active" if c.get('is_active', 1) else "Inactive"
            company = c.get('company', '')[:18] + "..." if c.get('company') and len(c['company']) > 18 else c.get('company', '')
            print(f"{c['id']:<5} {name:<30} {c['id_number']:<15} {company:<20} {status:<10}")
        
        print("-" * 90)
        return 0
    
    elif args.customer_cmd == 'find':
        if args.id:
            customer = service.get_customer_by_id_number(args.id, active_only=not args.include_inactive)
        elif args.customer_id:
            customer = service.get_customer_by_id(int(args.customer_id), active_only=not args.include_inactive)
        else:
            print("❌ Please provide --id or --customer-id")
            return 1
        
        if customer:
            print(f"\n✅ Customer found:")
            print(f"   ID: {customer['id']}")
            print(f"   Name: {customer['name']} {customer['surname']}")
            print(f"   ID Number: {customer['id_number']}")
            print(f"   Company: {customer.get('company', 'N/A')}")
            print(f"   Email: {customer.get('email', 'N/A')}")
            print(f"   Phone: {customer.get('phone', 'N/A')}")
            print(f"   Status: {'Active' if customer.get('is_active', 1) else 'Inactive'}")
            return 0
        else:
            print(f"\n❌ Customer not found")
            return 1
    
    elif args.customer_cmd == 'delete':
        success = service.delete_customer(args.id, soft_delete=not args.hard)
        return 0 if success else 1

def handle_invoice_command(args):
    """Handle invoice-related commands."""
    invoice_service = InvoiceService()
    
    if args.invoice_cmd == 'create':
        try:
            items = parse_items(args.items)
            
            invoice_id = invoice_service.create_invoice(
                customer_id=args.customer_id,
                items=items,
                description=args.description,
                due_days=args.due_days
            )
            
            if invoice_id:
                print(f"\n✅ Invoice created successfully! ID: {invoice_id}")
                
                if args.pdf:
                    invoice = invoice_service.get_invoice(invoice_id)
                    if invoice:
                        pdf_service = PDFInvoiceService()
                        pdf_service.generate_invoice_from_db(invoice)
                return 0
            return 1
            
        except Exception as e:
            logger.error(f"Failed to create invoice: {e}")
            print(f"\n❌ Error: {e}")
            return 1
    
    elif args.invoice_cmd == 'view':
        try:
            invoice = invoice_service.get_invoice(args.id)
            
            if invoice:
                print(f"\n🧾 Invoice #{invoice['invoice_number']}")
                print(f"   Customer: {invoice.get('customer_name')} {invoice.get('customer_surname')}")
                print(f"   Total: R {invoice['total_amount']:,.2f}")
                print(f"   Status: {invoice['status']}")
                
                if args.pdf:
                    pdf_service = PDFInvoiceService()
                    pdf_service.generate_invoice_from_db(invoice)
                return 0
            else:
                print(f"\n❌ Invoice with ID {args.id} not found")
                return 1
                
        except Exception as e:
            logger.error(f"Failed to view invoice: {e}")
            print(f"\n❌ Error: {e}")
            return 1
    
    elif args.invoice_cmd == 'list':
        try:
            if args.customer_id:
                invoices = invoice_service.get_customer_invoices(args.customer_id)
            else:
                invoices = invoice_service.get_all_invoices(limit=args.limit)
            
            if not invoices:
                print("\n📋 No invoices found")
                return 0
            
            print(f"\n📋 Invoices ({len(invoices)}):")
            print("-" * 90)
            print(f"{'ID':<5} {'Invoice #':<20} {'Customer':<25} {'Date':<12} {'Total':>12} {'Status':<10}")
            print("-" * 90)
            
            for inv in invoices:
                customer = f"{inv.get('name', '')} {inv.get('surname', '')}".strip()
                date = inv.get('invoice_date', '')[:10] if inv.get('invoice_date') else ''
                print(f"{inv['id']:<5} {inv['invoice_number']:<20} {customer:<25} {date:<12} R{inv['total_amount']:>10,.2f} {inv['status']:<10}")
            
            print("-" * 90)
            return 0
            
        except Exception as e:
            logger.error(f"Failed to list invoices: {e}")
            print(f"\n❌ Error: {e}")
            return 1
    
    elif args.invoice_cmd == 'status':
        try:
            success = invoice_service.update_invoice_status(args.id, args.status)
            if not success and invoice_service.get_last_error():
                print(f"❌ {invoice_service.get_last_error()}")
            return 0 if success else 1
        except Exception as e:
            print(f"❌ Error: {e}")
            return 1
    
    elif args.invoice_cmd == 'payment':
        return handle_payment(args)
    
    else:
        return 1

def handle_payment(args):
    """Handle payment commands."""
    try:
        payment_service = PaymentService()
        invoice_service = InvoiceService()
        
        if args.payment_cmd == 'add':
            payment_id = payment_service.record_payment(
                invoice_id=args.invoice_id,
                amount=args.amount,
                payment_method=args.method,
                reference_number=args.reference,
                notes=args.notes
            )
            if not payment_id and payment_service.get_last_error():
                print(f"❌ {payment_service.get_last_error()}")
            return 0 if payment_id else 1
        
        elif args.payment_cmd == 'list':
            payments = payment_service.get_payments_for_invoice(args.invoice_id)
            
            if not payments:
                print(f"No payments found for invoice {args.invoice_id}")
                return 0
            
            invoice = invoice_service.get_invoice(args.invoice_id)
            if invoice:
                print(f"\n💰 Payments for Invoice {invoice['invoice_number']}")
            
            print("-" * 80)
            print(f"{'ID':<5} {'Date':<12} {'Amount':>12} {'Method':<15} {'Reference':<20}")
            print("-" * 80)
            
            for p in payments:
                date = p['payment_date'][:10] if p['payment_date'] else ''
                print(f"{p['id']:<5} {date:<12} R{p['amount']:>10,.2f} {p['payment_method']:<15} {p.get('reference_number', '')[:18]:<20}")
            
            print("-" * 80)
            total = sum(p['amount'] for p in payments)
            print(f"{'Total Paid:':<53} R{total:>10,.2f}")
            return 0
        
        elif args.payment_cmd == 'outstanding':
            invoices = payment_service.get_outstanding_invoices(args.customer_id)
            
            if not invoices:
                print("✅ No outstanding invoices found")
                return 0
            
            print("\n💰 Outstanding Invoices")
            print("-" * 90)
            print(f"{'ID':<5} {'Invoice #':<20} {'Customer':<25} {'Due Date':<12} {'Balance':>12} {'Status':<10}")
            print("-" * 90)
            
            for inv in invoices:
                customer = f"{inv.get('customer_name', '')} {inv.get('customer_surname', '')}".strip()
                due = inv['due_date'][:10] if inv.get('due_date') else ''
                print(f"{inv['id']:<5} {inv['invoice_number']:<20} {customer:<25} {due:<12} R{inv['balance_due']:>10,.2f} {inv['status']:<10}")
            
            print("-" * 90)
            total = sum(inv['balance_due'] for inv in invoices)
            print(f"{'Total Outstanding:':<69} R{total:>10,.2f}")
            return 0
        
        elif args.payment_cmd == 'summary':
            summary = payment_service.get_payment_summary(args.days)
            
            print(f"\n💰 Payment Summary (last {args.days} days)")
            print("=" * 60)
            print(f"Total Received:     R {summary.get('total_received', 0):>12,.2f}")
            print(f"Total Outstanding:  R {summary.get('total_outstanding', 0):>12,.2f}")
            print(f"Total Overdue:      R {summary.get('total_overdue', 0):>12,.2f}")
            
            if summary.get('by_method'):
                print("\n📊 By Payment Method:")
                for method in summary['by_method']:
                    print(f"   {method['method']:<15} {method['count']:>3} payments  R {method['total']:>12,.2f}")
            
            return 0
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

def handle_pdf_command(args):
    """Handle PDF generation commands."""
    try:
        pdf_service = PDFInvoiceService()
        
        if args.pdf_cmd == 'test':
            # Generate test PDF
            from datetime import datetime, timedelta
            
            invoice_data = {
                'invoice_number': f'TEST-{datetime.now().strftime("%Y%m%d-%H%M%S")}',
                'invoice_date': datetime.now().strftime("%Y-%m-%d"),
                'due_date': (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                'status': 'DRAFT'
            }
            
            customer_data = {
                'name': 'Test',
                'surname': 'Customer',
                'company': 'Test Company',
                'email': 'test@example.com'
            }
            
            items_data = [
                {'description': 'Test Item 1', 'quantity': 1, 'unit_price': 1000.00, 'total': 1150.00}
            ]
            
            pdf_path = pdf_service.generate_invoice(invoice_data, customer_data, items_data)
            print(f"✅ Test PDF generated: {pdf_path}")
            return 0
            
        elif args.pdf_cmd == 'generate':
            invoice_service = InvoiceService()
            invoice = invoice_service.get_invoice(args.invoice_id)
            
            if invoice:
                pdf_path = pdf_service.generate_invoice_from_db(invoice)
                print(f"✅ PDF generated: {pdf_path}")
                return 0
            else:
                print(f"❌ Invoice {args.invoice_id} not found")
                return 1
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

def handle_status():
    """Handle status command."""
    try:
        customer_service = CustomerService()
        payment_service = PaymentService()
        
        customers = customer_service.get_all_customers(active_only=False)
        active_customers = customer_service.get_all_customers(active_only=True)
        summary = payment_service.get_payment_summary(30)
        
        print("\n📊 SYSTEM STATUS")
        print("=" * 60)
        print(f"Database: {config.DB_PATH}")
        print(f"Customers (total): {len(customers)}")
        print(f"Customers (active): {len(active_customers)}")
        print(f"Outstanding: R {summary.get('total_outstanding', 0):,.2f}")
        print(f"Received (30d): R {summary.get('total_received', 0):,.2f}")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

def main():
    """Main entry point."""
    try:
        config.validate()
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        return 1
    
    parser = setup_argparse()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    try:
        if args.command == 'status':
            return handle_status()
        
        elif args.command == 'init':
            from database.init import init_database
            success = init_database()
            print("✅ Database initialized" if success else "❌ Database init failed")
            return 0 if success else 1
        
        elif args.command == 'customer':
            return handle_customer_command(args)
        
        elif args.command == 'invoice':
            return handle_invoice_command(args)
        
        elif args.command == 'pdf':
            return handle_pdf_command(args)
        
        else:
            print(f"❌ Unknown command: {args.command}")
            parser.print_help()
            return 1
            
    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled")
        return 130
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(f"\n❌ Unexpected error: {e}")
        return 1
    finally:
        if _db and hasattr(_db, "close_connection"):
            _db.close_connection()

if __name__ == "__main__":
    sys.exit(main())
