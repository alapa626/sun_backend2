from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


# ═══════════════════════════════════════════════════════════════════════
#  CHOICES
# ═══════════════════════════════════════════════════════════════════════

LOAN_TYPE_CHOICES = [
    ('vehicle', 'Vehicle Loan'),
    ('gold', 'Gold Loan'),
]

VEHICLE_TYPE_CHOICES = [
    ('Bike', 'Bike'),
    ('Scooter', 'Scooter'),
    ('Car', 'Car'),
    ('Auto', 'Auto'),
    ('Other', 'Other'),
]

GOLD_ITEM_TYPE_CHOICES = [
    ('Chain', 'Chain'),
    ('Ring', 'Ring'),
    ('Earring', 'Earring'),
    ('Bangle', 'Bangle'),
    ('Necklace', 'Necklace'),
    ('Coin', 'Coin'),
    ('Bracelet', 'Bracelet'),
    ('Anklet', 'Anklet'),
    ('Other', 'Other'),
]

GOLD_PURITY_CHOICES = [
    ('24K', '24K'),
    ('22K', '22K'),
    ('18K', '18K'),
    ('916', '916 (22K)'),
    ('750', '750 (18K)'),
    ('Other', 'Other'),
]


# ═══════════════════════════════════════════════════════════════════════
#  CUSTOMER
# ═══════════════════════════════════════════════════════════════════════

class Customer(models.Model):
    vendor = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='customers'
    )
    loan_type = models.CharField(
        max_length=10,
        choices=LOAN_TYPE_CHOICES,
        default='vehicle',
    )

    # Personal
    name    = models.CharField(max_length=200)
    phone   = models.CharField(max_length=20)
    address = models.TextField()
    aadhaar = models.CharField(max_length=20, blank=True)

    # Vehicle (blank for gold loans)
    vehicle_type   = models.CharField(max_length=20, choices=VEHICLE_TYPE_CHOICES, blank=True)
    vehicle_model  = models.CharField(max_length=100, blank=True)
    vehicle_number = models.CharField(max_length=30,  blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.loan_type})"


# ═══════════════════════════════════════════════════════════════════════
#  GOLD ITEM  (linked to Customer, only used for gold loans)
# ═══════════════════════════════════════════════════════════════════════

class GoldItem(models.Model):
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name='gold_items'
    )
    item_type        = models.CharField(max_length=20, choices=GOLD_ITEM_TYPE_CHOICES, default='Other')
    item_description = models.CharField(max_length=200, blank=True)
    weight_grams     = models.DecimalField(max_digits=8, decimal_places=3)
    purity           = models.CharField(max_length=10, choices=GOLD_PURITY_CHOICES, default='22K')
    estimated_value  = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.item_type} {self.weight_grams}g ({self.purity})"


# ═══════════════════════════════════════════════════════════════════════
#  LOAN
# ═══════════════════════════════════════════════════════════════════════

class Loan(models.Model):
    customer      = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='loans')
    loan_amount   = models.DecimalField(max_digits=12, decimal_places=2)
    interest_rate = models.DecimalField(max_digits=5,  decimal_places=2, default=0)
    tenure_months = models.PositiveIntegerField(default=12)
    loan_date     = models.DateField(default=timezone.now)
    fine_amount   = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Guarantor
    guarantor_name     = models.CharField(max_length=200, blank=True)
    guarantor_phone    = models.CharField(max_length=20,  blank=True)
    guarantor_address  = models.TextField(blank=True)
    guarantor_aadhaar  = models.CharField(max_length=20,  blank=True)
    guarantor_relation = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    # Computed properties
    @property
    def total_interest(self):
        return float(self.loan_amount) * (float(self.interest_rate) / 100) * (self.tenure_months / 12)

    @property
    def total_payable(self):
        return float(self.loan_amount) + self.total_interest

    @property
    def emi(self):
        if self.tenure_months == 0:
            return 0
        return self.total_payable / self.tenure_months

    @property
    def total_paid(self):
        return sum(float(p.paid_amount) for p in self.emi_payments.all())

    @property
    def remaining(self):
        return max(0, self.total_payable - self.total_paid)

    @property
    def is_active(self):
        return self.remaining > 0

    @property
    def paid_count(self):
        return self.emi_payments.filter(is_paid=True).count()

    def __str__(self):
        return f"Loan #{self.id} — {self.customer.name}"


# ═══════════════════════════════════════════════════════════════════════
#  EMI PAYMENT
# ═══════════════════════════════════════════════════════════════════════

class EmiPayment(models.Model):
    loan               = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name='emi_payments')
    installment_number = models.PositiveIntegerField()
    due_date           = models.DateField()
    emi_amount         = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_paid            = models.BooleanField(default=False)
    paid_date          = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['installment_number']

    def __str__(self):
        return f"EMI #{self.installment_number} — Loan #{self.loan_id}"


# ═══════════════════════════════════════════════════════════════════════
#  LOAN PHOTO
# ═══════════════════════════════════════════════════════════════════════

class LoanPhoto(models.Model):
    VEHICLE_PHOTO_TYPES = ['customer', 'vehicle', 'rc_book']
    GOLD_PHOTO_TYPES    = ['customer', 'gold_items']

    customer    = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name='photos'
    )
    photo_type  = models.CharField(max_length=30)
    photo_url   = models.URLField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # ✅ unique_together REMOVED — multiple photos per type are now allowed
    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f"{self.customer.name} | {self.customer.loan_type} | {self.photo_type}"