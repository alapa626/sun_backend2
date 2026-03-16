from datetime import date
from .models import EmiPayment


def generate_emi_schedule(loan):
    """
    Creates EmiPayment rows for all installments.
    Called on new loan creation.
    """
    emi = loan.emi
    start = loan.loan_date

    for i in range(loan.tenure_months):
        month = start.month + i + 1
        year = start.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        due_date = date(year, month, start.day)

        EmiPayment.objects.create(
            loan=loan,
            installment_number=i + 1,
            due_date=due_date,
            emi_amount=round(emi, 2),
        )


def regenerate_unpaid_schedule(loan):
    """
    Called when loan is edited.
    Preserves paid EMIs — deletes and regenerates only unpaid ones.
    Recalculates EMI amount based on remaining balance.
    """
    paid_emis = loan.emi_payments.filter(is_paid=True).order_by('installment_number')
    paid_count = paid_emis.count()

    # Delete all unpaid EMIs
    loan.emi_payments.filter(is_paid=False).delete()

    # Remaining balance after paid EMIs
    total_paid = sum(float(e.paid_amount) for e in paid_emis)
    remaining_balance = max(0, loan.total_payable - total_paid)
    remaining_months = loan.tenure_months - paid_count

    if remaining_months <= 0:
        return

    new_emi = remaining_balance / remaining_months
    start = loan.loan_date

    for i in range(paid_count, loan.tenure_months):
        month = start.month + i + 1
        year = start.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        due_date = date(year, month, start.day)

        EmiPayment.objects.create(
            loan=loan,
            installment_number=i + 1,
            due_date=due_date,
            emi_amount=round(new_emi, 2),
        )