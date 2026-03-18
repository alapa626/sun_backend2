from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Customer(models.Model):
    vendor = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='customers'
    )
    # Personal
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=15)
    address = models.TextField(blank=True)
    aadhaar = models.CharField(max_length=20, blank=True)
    # Vehicle
    vehicle_type = models.CharField(max_length=50, blank=True)
    vehicle_model = models.CharField(max_length=100, blank=True)
    vehicle_number = models.CharField(max_length=30, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.phone})"


class Loan(models.Model):
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name='loans'
    )
    # Loan config
    loan_amount = models.DecimalField(max_digits=12, decimal_places=2)
    interest_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0
    )
    tenure_months = models.PositiveIntegerField(default=12)
    loan_date = models.DateField(default=timezone.now)

    # Guarantor
    guarantor_name = models.CharField(max_length=200, blank=True)
    guarantor_phone = models.CharField(max_length=15, blank=True)
    guarantor_address = models.TextField(blank=True)
    guarantor_aadhaar = models.CharField(max_length=20, blank=True)
    guarantor_relation = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-loan_date']

    def __str__(self):
        return f"Loan #{self.id} — {self.customer.name}"

    # ── Computed properties ───────────────────────────────────────
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
        return sum(
            float(p.paid_amount) for p in self.emi_payments.all()
        )

    @property
    def remaining(self):
        return max(0, self.total_payable - self.total_paid)

    @property
    def is_active(self):
        return self.remaining > 0

    @property
    def paid_count(self):
        return self.emi_payments.filter(is_paid=True).count()


class EmiPayment(models.Model):
    loan = models.ForeignKey(
        Loan, on_delete=models.CASCADE, related_name='emi_payments'
    )
    installment_number = models.PositiveIntegerField()
    due_date = models.DateField()
    emi_amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    is_paid = models.BooleanField(default=False)
    paid_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['installment_number']
        unique_together = ['loan', 'installment_number']

    def __str__(self):
        return f"Loan#{self.loan.id} — EMI {self.installment_number}"