# services/pdf_service.py - FIXED: Full descriptions & original logo size
import os
import re
from datetime import datetime
from pathlib import Path
import textwrap

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch, mm, cm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, 
        Spacer, Image, KeepTogether, PageBreak, Flowable
    )
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT, TA_JUSTIFY
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("WARNING: ReportLab not installed. Run: pip install reportlab")

# Optional: for image processing
try:
    from PIL import Image as PILImage
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

class PDFInvoiceService:
    """Generate professional PDF invoices with full descriptions and proper logo sizing."""
    
    def __init__(self, output_dir="invoices", logo_dir="logos"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.logo_dir = Path(logo_dir)
        
        # Modern SaaS color palette
        self.colors = {
            'primary': colors.HexColor('#1a1f36'),      # Deep navy - headers
            'secondary': colors.HexColor('#2d3a5e'),    # Medium navy - subheaders
            'accent': colors.HexColor('#0ba5e9'),       # Bright blue - totals
            'highlight': colors.HexColor('#635bff'),    # Purple - invoice #
            'success': colors.HexColor('#0e9f6e'),      # Green - paid
            'warning': colors.HexColor('#f59e0b'),      # Orange - pending
            'light_bg': colors.HexColor('#f9fafb'),     # Light gray - backgrounds
            'border': colors.HexColor('#e5e7eb'),       # Border color
            'text_primary': colors.HexColor('#111827'), # Dark text
            'text_secondary': colors.HexColor('#6b7280'), # Light text
            'white': colors.HexColor('#ffffff')         # White
        }
        
        # Layout constants
        self.page_width = A4[0]
        self.page_height = A4[1]
        self.left_margin = 0.75 * inch
        self.right_margin = 0.75 * inch
        self.top_margin = 0.75 * inch
        self.bottom_margin = 0.75 * inch
        self.content_width = self.page_width - self.left_margin - self.right_margin
    
    def _load_logo(self, explicit_logo_path: str = None):
        """Load company logo with ORIGINAL aspect ratio - NO STRETCHING!"""
        if explicit_logo_path:
            p = Path(explicit_logo_path)
            if p.exists():
                try:
                    if PIL_AVAILABLE:
                        img = PILImage.open(p)
                        orig_width, orig_height = img.size
                        target_height = 0.8 * inch
                        target_width = (orig_width / orig_height) * target_height
                        if target_width > 2.5 * inch:
                            target_width = 2.5 * inch
                            target_height = (orig_height / orig_width) * target_width
                        return {
                            'type': 'image',
                            'content': str(p),
                            'width': target_width,
                            'height': target_height,
                            'path': p
                        }
                    return {
                        'type': 'image',
                        'content': str(p),
                        'width': 1.5 * inch,
                        'height': 0.6 * inch,
                        'path': p
                    }
                except Exception:
                    pass
        logo_extensions = ['.png', '.jpg', '.jpeg', '.gif']
        
        for ext in logo_extensions:
            logo_path = self.logo_dir / f"logo{ext}"
            if logo_path.exists():
                try:
                    if PIL_AVAILABLE:
                        # Get original dimensions to preserve aspect ratio
                        img = PILImage.open(logo_path)
                        orig_width, orig_height = img.size
                        
                        # Target max height (0.8 inch) but keep aspect ratio
                        target_height = 0.8 * inch
                        target_width = (orig_width / orig_height) * target_height
                        
                        # Cap width at 2.5 inches to prevent huge logos
                        if target_width > 2.5 * inch:
                            target_width = 2.5 * inch
                            target_height = (orig_height / orig_width) * target_width
                        
                        return {
                            'type': 'image',
                            'content': str(logo_path),
                            'width': target_width,
                            'height': target_height,
                            'path': logo_path
                        }
                    else:
                        # Without PIL, use default sizing
                        return {
                            'type': 'image',
                            'content': str(logo_path),
                            'width': 1.5 * inch,
                            'height': 0.6 * inch,
                            'path': logo_path
                        }
                except Exception as e:
                    print(f"WARNING: Could not load logo: {e}")
                    continue
        return None
    
    def _create_styles(self):
        """Create modern typography styles."""
        styles = {}
        
        # Company name - large, bold
        styles['company_name'] = ParagraphStyle(
            'CompanyName',
            fontName='Helvetica-Bold',
            fontSize=18,
            textColor=self.colors['primary'],
            alignment=TA_LEFT,
            spaceAfter=2,
            leading=22
        )
        
        # Company tagline
        styles['company_tagline'] = ParagraphStyle(
            'CompanyTagline',
            fontName='Helvetica',
            fontSize=9,
            textColor=self.colors['text_secondary'],
            alignment=TA_LEFT,
            spaceAfter=4,
            leading=11
        )
        
        # Invoice title - large, clean
        styles['invoice_title'] = ParagraphStyle(
            'InvoiceTitle',
            fontName='Helvetica-Bold',
            fontSize=24,
            textColor=self.colors['primary'],
            alignment=TA_CENTER,
            spaceAfter=20,
            spaceBefore=10,
            leading=28
        )
        
        # Section headers
        styles['section_header'] = ParagraphStyle(
            'SectionHeader',
            fontName='Helvetica-Bold',
            fontSize=11,
            textColor=self.colors['primary'],
            alignment=TA_LEFT,
            spaceAfter=8,
            spaceBefore=16,
            leading=14
        )
        
        # Body text - FULL DESCRIPTIONS (no truncation)
        styles['body_text'] = ParagraphStyle(
            'BodyText',
            fontName='Helvetica',
            fontSize=10,
            textColor=self.colors['text_primary'],
            alignment=TA_LEFT,
            spaceAfter=4,
            leading=14,
            wordWrap='CJK'  # Better wrapping for long text
        )
        
        # Small text
        styles['small_text'] = ParagraphStyle(
            'SmallText',
            fontName='Helvetica',
            fontSize=8,
            textColor=self.colors['text_secondary'],
            alignment=TA_LEFT,
            spaceAfter=2,
            leading=10
        )
        
        # Labels
        styles['label'] = ParagraphStyle(
            'Label',
            fontName='Helvetica',
            fontSize=9,
            textColor=self.colors['text_secondary'],
            alignment=TA_LEFT,
            spaceAfter=0,
            leading=11
        )
        
        # Values
        styles['value'] = ParagraphStyle(
            'Value',
            fontName='Helvetica',
            fontSize=10,
            textColor=self.colors['text_primary'],
            alignment=TA_LEFT,
            spaceAfter=0,
            leading=12
        )
        
        # Right-aligned value
        styles['value_right'] = ParagraphStyle(
            'ValueRight',
            fontName='Helvetica',
            fontSize=10,
            textColor=self.colors['text_primary'],
            alignment=TA_RIGHT,
            spaceAfter=0,
            leading=12
        )
        
        # Total amount - large, bold, accent color
        styles['total'] = ParagraphStyle(
            'Total',
            fontName='Helvetica-Bold',
            fontSize=14,
            textColor=self.colors['accent'],
            alignment=TA_RIGHT,
            spaceAfter=4,
            leading=16
        )
        
        # Thank you message
        styles['thank_you'] = ParagraphStyle(
            'ThankYou',
            fontName='Helvetica-Oblique',
            fontSize=10,
            textColor=self.colors['text_secondary'],
            alignment=TA_CENTER,
            spaceAfter=10,
            leading=12
        )
        
        return styles

    def _normalize_banking_rows(self, banking_details: str, invoice_number: str):
        """Normalize banking details into ordered key/value rows for right-side layout."""
        raw = (banking_details or "").replace("{invoice_number}", invoice_number).strip()
        if not raw:
            return []

        canonical_order = [
            "Bank",
            "Account Holder",
            "Account Number",
            "Branch Code",
            "Reference",
        ]
        synonyms = {
            "bank": "Bank",
            "bank name": "Bank",
            "account holder": "Account Holder",
            "account name": "Account Holder",
            "account number": "Account Number",
            "acc number": "Account Number",
            "branch code": "Branch Code",
            "reference": "Reference",
            "payment reference": "Reference",
        }

        values = {}
        extras = []
        for line in raw.splitlines():
            text = line.strip()
            if not text:
                continue
            if ":" in text:
                key, value = text.split(":", 1)
                k = synonyms.get(key.strip().lower(), key.strip())
                values[k] = value.strip()
            else:
                extras.append(text)

        rows = []
        for key in canonical_order:
            value = values.get(key, "")
            if key == "Reference":
                value = invoice_number
            if value:
                rows.append((key, value))

        for idx, extra in enumerate(extras, start=1):
            rows.append((f"Details {idx}", extra))

        return rows
    
    def _create_header(self, business_data, styles, logo):
        """Create header with logo at ORIGINAL ASPECT RATIO."""
        elements = []
        
        # Header table
        header_data = []
        
        # Left column - Logo (preserved aspect ratio)
        left_content = []
        if logo and logo['type'] == 'image':
            try:
                img = Image(logo['content'])
                # Use the calculated dimensions that preserve aspect ratio
                img.drawHeight = logo['height']
                img.drawWidth = logo['width']
                left_content.append(img)
            except:
                left_content.append(Paragraph(business_data.get('name', 'YOUR COMPANY'), 
                                            styles['company_name']))
        else:
            left_content.append(Paragraph(business_data.get('name', 'YOUR COMPANY'), 
                                        styles['company_name']))
        
        # Right column - Company Info
        right_content = []
        right_content.append(Paragraph(business_data.get('name', ''), styles['company_name']))
        
        if business_data.get('address'):
            right_content.append(Paragraph(business_data['address'].replace('\n', '<br/>'), 
                                         styles['small_text']))
        if business_data.get('phone'):
            right_content.append(Paragraph(f"Tel: {business_data['phone']}", styles['small_text']))
        if business_data.get('email'):
            right_content.append(Paragraph(f"Email: {business_data['email']}", styles['small_text']))
        vat_digits = re.sub(r"\D", "", str(business_data.get("vat_number", "")).strip())
        if len(vat_digits) == 10:
            right_content.append(Paragraph(f"VAT: {vat_digits}", styles['small_text']))
        
        # Build header table
        header_table = Table([[left_content, right_content]], 
                            colWidths=[2.5*inch, self.content_width - 2.5*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (0,0), 'MIDDLE'),
            ('VALIGN', (1,0), (1,0), 'TOP'),
            ('ALIGN', (0,0), (0,0), 'LEFT'),
            ('ALIGN', (1,0), (1,0), 'RIGHT'),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        
        elements.append(header_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Subtle separator line
        line = Table([['']], colWidths=[self.content_width])
        line.setStyle(TableStyle([
            ('LINEBELOW', (0,0), (-1,-1), 1, self.colors['border']),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(line)
        elements.append(Spacer(1, 0.1*inch))
        
        return elements
    
    def generate_invoice(self, invoice_data, customer_data, items_data, business_data=None):
        """Generate a professional PDF invoice with full descriptions and proper logo."""
        
        if not REPORTLAB_AVAILABLE:
            print("ERROR: ReportLab not installed. Run: pip install reportlab")
            return None
        
        # Default business data
        if not business_data:
            business_data = {
                'name': 'Your Company Name',
                'vat_number': '',
                'address': 'Your Address',
                'phone': '',
                'email': '',
                'banking_details': ''
            }
        
        try:
            # Create styles
            styles = self._create_styles()
            
            # Load logo (preserves aspect ratio)
            logo = self._load_logo(business_data.get('logo_file_path') if business_data else None)
            
            # Clean invoice number
            invoice_num = invoice_data.get('invoice_number', 'INV-001').replace(' ', '')
            filename = f"Invoice_{invoice_num}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            filepath = self.output_dir / filename
            
            # Create PDF document
            doc = SimpleDocTemplate(
                str(filepath),
                pagesize=A4,
                rightMargin=self.right_margin,
                leftMargin=self.left_margin,
                topMargin=self.top_margin,
                bottomMargin=self.bottom_margin,
                title=f"Invoice {invoice_num}",
                author=business_data.get('name', 'Vanta Pilot')
            )
            
            story = []
            
            # 1. HEADER WITH LOGO
            story.extend(self._create_header(business_data, styles, logo))
            
            # 2. INVOICE TITLE
            story.append(Paragraph("INVOICE", styles['invoice_title']))
            story.append(Spacer(1, 0.1*inch))

            # Client-facing metadata should stay neutral: no internal status labels.
            preview_subtotal = float(invoice_data.get("subtotal", 0) or 0)
            preview_tax = float(invoice_data.get("tax_amount", 0) or 0)
            preview_total = float(invoice_data.get("total_amount", preview_subtotal + preview_tax) or 0)

            # 3. INVOICE METADATA
            meta_data = [
                [Paragraph("Invoice Number:", styles['label']),
                 Paragraph(invoice_num, styles['value']),
                 Paragraph("Date:", styles['label']),
                 Paragraph(invoice_data.get('invoice_date', ''), styles['value'])],
                [Paragraph("Due Date:", styles['label']),
                 Paragraph(invoice_data.get('due_date', ''), styles['value']),
                 Paragraph("Amount Due:", styles['label']),
                 Paragraph(f"R {preview_total:,.2f}", styles['value'])]
            ]
            
            meta_table = Table(meta_data, colWidths=[1*inch, 2*inch, 0.8*inch, 2*inch])
            meta_table.setStyle(TableStyle([
                ('ALIGN', (0,0), (0,-1), 'RIGHT'),
                ('ALIGN', (1,0), (1,-1), 'LEFT'),
                ('ALIGN', (2,0), (2,-1), 'RIGHT'),
                ('ALIGN', (3,0), (3,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('FONTSIZE', (0,0), (-1,-1), 10),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ]))
            story.append(meta_table)
            story.append(Spacer(1, 0.3*inch))
            
            # 4. BILL TO SECTION
            story.append(Paragraph("Bill To", styles['section_header']))
            
            customer_info = []
            name = f"{customer_data.get('name', '')} {customer_data.get('surname', '')}".strip()
            if name:
                customer_info.append([Paragraph(name, styles['body_text'])])
            if customer_data.get('company'):
                customer_info.append([Paragraph(customer_data['company'], styles['body_text'])])
            if customer_data.get('address'):
                customer_info.append([Paragraph(customer_data['address'], styles['body_text'])])
            if customer_data.get('phone'):
                customer_info.append([Paragraph(customer_data['phone'], styles['small_text'])])
            if customer_data.get('email'):
                customer_info.append([Paragraph(customer_data['email'], styles['small_text'])])
            
            if customer_info:
                customer_table = Table(customer_info, colWidths=[self.content_width])
                customer_table.setStyle(TableStyle([
                    ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 2),
                ]))
                story.append(customer_table)
            
            story.append(Spacer(1, 0.3*inch))
            
            # 5. ITEMS TABLE - WITH FULL DESCRIPTIONS (no truncation)
            story.append(Paragraph("Items", styles['section_header']))
            
            # Table headers
            table_data = [
                ['Description', 'Qty', 'Unit Price', 'Amount']
            ]
            
            # Add items - FULL DESCRIPTION, no truncation
            for item in items_data:
                # Use Paragraph for automatic text wrapping instead of truncation
                description = item.get('description', '')
                table_data.append([
                    Paragraph(description, styles['body_text']),  # ← FULL description!
                    str(item.get('quantity', 1)),
                    f"R {item.get('unit_price', 0):,.2f}",
                    f"R {item.get('total', 0):,.2f}"
                ])
            
            # Calculate totals
            subtotal = float(invoice_data.get("subtotal", 0) or 0)
            vat = float(invoice_data.get("tax_amount", 0) or 0)
            total = float(invoice_data.get("total_amount", subtotal + vat) or 0)
            
            # Add totals
            table_data.append(['', '', 'Subtotal:', f"R {subtotal:,.2f}"])
            if abs(vat) > 0.0001:
                rate_pct = (vat / subtotal * 100) if subtotal else 0
                table_data.append(['', '', f"VAT ({rate_pct:.0f}%):", f"R {vat:,.2f}"])
            table_data.append(['', '', 'Total Due:', f"R {total:,.2f}"])
            
            # Create table with wider description column for full text
            col_widths = [3.5*inch, 0.6*inch, 1.2*inch, 1.2*inch]  # Wider description column
            table = Table(table_data, colWidths=col_widths, repeatRows=1)
            
            # Table styling
            table_style = [
                # Header row
                ('BACKGROUND', (0,0), (-1,0), self.colors['primary']),
                ('TEXTCOLOR', (0,0), (-1,0), self.colors['white']),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 10),
                ('ALIGN', (0,0), (0,-1), 'LEFT'),
                ('ALIGN', (1,0), (1,-1), 'CENTER'),
                ('ALIGN', (2,0), (2,-1), 'RIGHT'),
                ('ALIGN', (3,0), (3,-1), 'RIGHT'),
                
                # Grid for items
                ('LINEBELOW', (0,1), (-1,-4), 0.5, self.colors['border']),
                ('LINEABOVE', (0,-3), (-1,-3), 1, self.colors['border']),
                ('LINEBELOW', (0,-1), (-1,-1), 2, self.colors['accent']),
                
                # Totals background
                ('BACKGROUND', (0,-3), (-1,-1), self.colors['light_bg']),
                ('FONTNAME', (2,-3), (3,-1), 'Helvetica-Bold'),
                
                # Padding
                ('TOPPADDING', (0,0), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ]
            
            table.setStyle(TableStyle(table_style))
            story.append(table)
            story.append(Spacer(1, 0.3*inch))
            
            # 6. PAYMENT DETAILS (classic plain-text block, left aligned)
            banking_rows = self._normalize_banking_rows(
                business_data.get('banking_details', ''),
                invoice_num,
            )
            if banking_rows:
                payment_title_style = ParagraphStyle(
                    "PaymentTitleClassic",
                    parent=styles["section_header"],
                    alignment=TA_LEFT,
                )
                payment_line_style = ParagraphStyle(
                    "PaymentLineClassic",
                    parent=styles["small_text"],
                    alignment=TA_LEFT,
                    leading=15,
                    spaceAfter=2,
                )
                payment_block = [Paragraph("Payment Details", payment_title_style)]

                # Show bank name first without a label, then standard labeled lines.
                bank_row = next((row for row in banking_rows if row[0] == "Bank"), None)
                if bank_row:
                    payment_block.append(Paragraph(bank_row[1], payment_line_style))

                for label, value in banking_rows:
                    if not value or label == "Bank":
                        continue
                    if label.startswith("Details "):
                        payment_block.append(Paragraph(value, payment_line_style))
                        continue
                    payment_block.append(Paragraph(f"{label}: {value}", payment_line_style))
                payment_block.append(Spacer(1, 0.2*inch))
                story.append(KeepTogether(payment_block))
            
            # 7. NOTES
            if invoice_data.get('notes'):
                story.append(Paragraph("Notes", styles['section_header']))
                notes_para = Paragraph(invoice_data['notes'].replace('\n', '<br/>'), 
                                      styles['small_text'])
                story.append(notes_para)
                story.append(Spacer(1, 0.2*inch))
            
            # 8. THANK YOU
            story.append(Spacer(1, 0.3*inch))
            story.append(Paragraph("Thank you for your business!", styles['thank_you']))
            
            # 9. FOOTER
            story.append(Spacer(1, 0.2*inch))
            footer = Table([['']], colWidths=[self.content_width])
            footer.setStyle(TableStyle([
                ('LINEABOVE', (0,0), (-1,-1), 0.5, self.colors['border']),
                ('TOPPADDING', (0,0), (-1,-1), 8),
            ]))
            story.append(footer)
            
            footer_text = f"Invoice {invoice_num} | Generated {datetime.now().strftime('%Y-%m-%d')}"
            story.append(Paragraph(footer_text, styles['small_text']))
            
            # Build PDF
            doc.build(story)
            
            print(f"OK: Professional invoice generated: {filepath.name}")
            print(f"   Total: R {total:,.2f}")
            if logo:
                print("   Logo: Original aspect ratio preserved")
            print("   Descriptions: Full text visible")
            
            return filepath
            
        except Exception as e:
            print(f"ERROR: PDF generation failed: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def generate_invoice_from_db(self, invoice_data, business_profile=None):
        """Generate PDF from database invoice data."""
        if not invoice_data:
            return None
        
        # Extract data
        invoice_number = invoice_data.get('invoice_number', '').replace(' ', '')
        invoice_date = invoice_data.get('invoice_date', '')[:10]
        due_date = invoice_data.get('due_date', '')[:10] if invoice_data.get('due_date') else ''
        status = invoice_data.get('status', 'draft')
        
        # Customer data
        customer_data = {
            'name': invoice_data.get('customer_name', ''),
            'surname': invoice_data.get('customer_surname', ''),
            'company': invoice_data.get('customer_company', ''),
            'id_number': invoice_data.get('customer_id_number', ''),
            'email': invoice_data.get('customer_email', ''),
            'phone': invoice_data.get('customer_phone', ''),
            'address': invoice_data.get('customer_address', ''),
        }
        
        # Items data - FULL DESCRIPTIONS preserved
        items_data = []
        for item in invoice_data.get('items', []):
            items_data.append({
                'description': item.get('item_description', ''),  # Full description
                'quantity': item.get('quantity', 1),
                'unit_price': item.get('unit_price', 0),
                'total': item.get('line_total', 0)
            })
        
        # Invoice data
        inv_data = {
            'invoice_number': invoice_number,
            'invoice_date': invoice_date,
            'due_date': due_date,
            'status': status.upper(),
            'subtotal': invoice_data.get('subtotal', 0),
            'tax_amount': invoice_data.get('tax_amount', 0),
            'total_amount': invoice_data.get('total_amount', 0),
            'notes': f"Payment is due within 30 days.\nPlease quote invoice #{invoice_number} with payment."
        }
        
        if business_profile:
            raw_banking_details = (business_profile.get("banking_details") or "").strip()
            if not raw_banking_details:
                raw_banking_details = (
                    "Banking details not configured yet.\n"
                    "Go to Settings > Business to add your bank account details."
                )
            business_data = {
                'name': business_profile.get('business_name', 'Your Business Name'),
                'vat_number': (
                    re.sub(r"\D", "", str(business_profile.get('vat_number', '')).strip())
                    if len(re.sub(r"\D", "", str(business_profile.get('vat_number', '')).strip())) == 10
                    else ''
                ),
                'address': business_profile.get('business_address', ''),
                'phone': business_profile.get('business_phone', ''),
                'email': business_profile.get('business_email', ''),
                'logo_file_path': business_profile.get('logo_file_path', ''),
                'banking_details': raw_banking_details.replace('{invoice_number}', invoice_number),
            }
        else:
            # Neutral fallback (never another tenant's branded information)
            business_data = {
                'name': 'Your Business Name',
                'vat_number': '',
                'address': '',
                'phone': '',
                'email': '',
                'banking_details': (
                    "Banking details not configured yet.\n"
                    "Go to Settings > Business to add your bank account details."
                ),
            }
        
        return self.generate_invoice(inv_data, customer_data, items_data, business_data)


