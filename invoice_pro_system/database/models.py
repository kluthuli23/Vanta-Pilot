# database/models.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any
from decimal import Decimal

@dataclass
class Customer:
    """Customer data model."""
    id: Optional[int] = None
    name: str = ""
    surname: str = ""
    id_number: str = ""
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = True
    date_registered: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def full_name(self) -> str:
        return f"{self.name} {self.surname}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'surname': self.surname,
            'id_number': self.id_number,
            'company': self.company,
            'email': self.email,
            'phone': self.phone,
            'is_active': self.is_active,
            'date_registered': self.date_registered.isoformat() if self.date_registered else None,
            'full_name': self.full_name()
        }

@dataclass
class InvoiceItem:
    """Invoice line item model."""
    id: Optional[int] = None
    invoice_id: Optional[int] = None
    description: str = ""
    quantity: int = 1
    unit_price: Decimal = Decimal('0.00')
    tax_rate: Decimal = Decimal('0.15')
    discount: Decimal = Decimal('0.00')
    line_total: Optional[Decimal] = None
    
    def calculate_total(self) -> Decimal:
        """Calculate line total with tax and discount."""
        subtotal = Decimal(str(self.quantity)) * self.unit_price
        discounted = subtotal * (Decimal('1.00') - self.discount)
        tax = discounted * self.tax_rate
        return discounted + tax

@dataclass
class Invoice:
    """Invoice data model."""
    id: Optional[int] = None
    customer_id: Optional[int] = None
    invoice_number: str = ""
    status: str = "draft"  # draft, sent, paid, overdue, cancelled
    description: Optional[str] = None
    subtotal: Decimal = Decimal('0.00')
    tax_amount: Decimal = Decimal('0.00')
    total_amount: Decimal = Decimal('0.00')
    currency: str = "ZAR"
    due_date: Optional[datetime] = None
    invoice_date: Optional[datetime] = None
    paid_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Relationships
    customer: Optional[Customer] = None
    items: List[InvoiceItem] = None
    
    def __post_init__(self):
        if self.items is None:
            self.items = []
    
    def calculate_totals(self):
        """Recalculate invoice totals from items."""
        self.subtotal = Decimal('0.00')
        self.tax_amount = Decimal('0.00')
        
        for item in self.items:
            item.line_total = item.calculate_total()
            self.subtotal += item.quantity * item.unit_price
            self.tax_amount += item.line_total - (item.quantity * item.unit_price)
        
        self.total_amount = self.subtotal + self.tax_amount
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'invoice_number': self.invoice_number,
            'status': self.status,
            'customer_id': self.customer_id,
            'subtotal': float(self.subtotal),
            'tax_amount': float(self.tax_amount),
            'total_amount': float(self.total_amount),
            'currency': self.currency,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'invoice_date': self.invoice_date.isoformat() if self.invoice_date else None,
            'items': [item.__dict__ for item in self.items]
        }