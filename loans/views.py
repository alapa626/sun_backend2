from django.shortcuts import render
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import timedelta, date, datetime
from .models import Customer, Loan, EmiPayment
from .serializers import (
    CustomerListSerializer, CustomerDetailSerializer,
    CustomerCreateSerializer, LoanSerializer,
    LoanCreateSerializer, EmiPaymentSerializer,
)
from .utils import generate_emi_schedule, regenerate_unpaid_schedule


# ═══════════════════════════════════════════════════════════════════════
#  CUSTOMER VIEWS
# ═══════════════════════════════════════════════════════════════════════

class CustomerListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Customer.objects.filter(
            vendor=self.request.user
        ).prefetch_related('loans__emi_payments')
        q = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(phone__icontains=q) |
                Q(vehicle_model__icontains=q) |
                Q(vehicle_number__icontains=q)
            )
        return qs

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CustomerCreateSerializer
        return CustomerListSerializer

    def perform_create(self, serializer):
        serializer.save(vendor=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = serializer.save(vendor=request.user)
        return Response(
            CustomerDetailSerializer(customer).data,
            status=status.HTTP_201_CREATED,
        )


class CustomerDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Customer.objects.filter(
            vendor=self.request.user
        ).prefetch_related('loans__emi_payments')

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return CustomerCreateSerializer
        return CustomerDetailSerializer


# ═══════════════════════════════════════════════════════════════════════
#  LOAN VIEWS
# ═══════════════════════════════════════════════════════════════════════

class LoanListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LoanSerializer

    def get_queryset(self):
        customer_id = self.kwargs.get('customer_id')
        return Loan.objects.filter(
            customer__vendor=self.request.user,
            customer_id=customer_id,
        ).prefetch_related('emi_payments')

    def create(self, request, *args, **kwargs):
        customer_id = self.kwargs.get('customer_id')
        try:
            customer = Customer.objects.get(
                id=customer_id, vendor=request.user
            )
        except Customer.DoesNotExist:
            return Response({'error': 'Customer not found'}, status=404)

        serializer = LoanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = serializer.save(customer=customer)
        generate_emi_schedule(loan)
        return Response(
            LoanSerializer(loan).data,
            status=status.HTTP_201_CREATED,
        )


class LoanDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Loan.objects.filter(
            customer__vendor=self.request.user
        ).prefetch_related('emi_payments')

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return LoanCreateSerializer
        return LoanSerializer

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        loan = self.get_object()
        serializer = LoanCreateSerializer(
            loan, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        loan = serializer.save()
        regenerate_unpaid_schedule(loan)
        return Response(LoanSerializer(loan).data)


# ═══════════════════════════════════════════════════════════════════════
#  EMI PAYMENT VIEW
# ═══════════════════════════════════════════════════════════════════════

class RecordPaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, loan_id, installment_number):
        try:
            loan = Loan.objects.get(
                id=loan_id, customer__vendor=request.user
            )
        except Loan.DoesNotExist:
            return Response({'error': 'Loan not found'}, status=404)

        try:
            emi = EmiPayment.objects.get(
                loan=loan, installment_number=installment_number
            )
        except EmiPayment.DoesNotExist:
            return Response({'error': 'Installment not found'}, status=404)

        paid_amount = float(request.data.get('paid_amount', 0))
        if paid_amount < 0:
            return Response({'error': 'Invalid amount'}, status=400)

        emi.paid_amount = paid_amount
        emi.is_paid = paid_amount >= float(emi.emi_amount)

        if paid_amount > 0:
            payment_date_str = request.data.get('payment_date')
            if payment_date_str:
                try:
                    emi.paid_date = datetime.strptime(
                        payment_date_str, '%Y-%m-%d'
                    ).date()
                except ValueError:
                    emi.paid_date = date.today()
            else:
                emi.paid_date = date.today()
        else:
            emi.paid_date = None

        emi.save()
        return Response(EmiPaymentSerializer(emi).data)


# ═══════════════════════════════════════════════════════════════════════
#  DASHBOARD VIEW — supports ?mode=daily|weekly|monthly|custom&days=N
# ═══════════════════════════════════════════════════════════════════════

class DashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        loans = Loan.objects.filter(
            customer__vendor=request.user
        ).prefetch_related('emi_payments')

        customers = Customer.objects.filter(vendor=request.user)

        total_lent      = sum(float(l.loan_amount) for l in loans)
        total_payable   = sum(l.total_payable for l in loans)
        total_collected = sum(l.total_paid for l in loans)
        total_pending   = max(0, total_payable - total_collected)
        active_count    = sum(1 for l in loans if l.is_active)
        closed_count    = sum(1 for l in loans if not l.is_active)

        now = timezone.now().date()
        overdue_count = EmiPayment.objects.filter(
            loan__customer__vendor=request.user,
            is_paid=False,
            due_date__lt=now,
        ).count()

        # ── Flexible time range ──────────────────────────────────────
        # mode: monthly (default) | weekly | daily | custom
        # days: number of days to look back (used for custom/daily/weekly)
        mode = request.query_params.get('mode', 'monthly')
        days_param = request.query_params.get('days', None)

        if mode == 'daily' or (days_param and int(days_param) == 1):
            # Single day — show hourly breakdown (today only)
            periods = self._build_daily_periods(now)
        elif mode == 'weekly' or (days_param and int(days_param) == 7):
            # Last 7 days — show each day
            periods = self._build_day_periods(now, 7)
        elif days_param:
            # Custom number of days
            days = int(days_param)
            if days <= 31:
                # Show each day
                periods = self._build_day_periods(now, days)
            else:
                # Show each week
                periods = self._build_week_periods(now, days)
        else:
            # Default: last 6 months
            periods = self._build_monthly_periods(now, 6)

        # ── Build collections for each period ────────────────────────
        result = []
        for period in periods:
            # ✅ FIX: Use paid_date for collected (actual payment date)
            # Use due_date for expected (when payment was scheduled)
            paid_emis = EmiPayment.objects.filter(
                loan__customer__vendor=request.user,
                is_paid=True,
                paid_date__gte=period['start'],
                paid_date__lte=period['end'],
            )
            due_emis = EmiPayment.objects.filter(
                loan__customer__vendor=request.user,
                due_date__gte=period['start'],
                due_date__lte=period['end'],
            )

            collected = sum(float(e.paid_amount) for e in paid_emis)
            expected  = sum(float(e.emi_amount)  for e in due_emis)

            result.append({
                'month':     period['label'],
                'year':      period['start'].year,
                'collected': round(collected, 2),
                'expected':  round(expected, 2),
                'start':     period['start'].isoformat(),
                'end':       period['end'].isoformat(),
            })

        return Response({
            'total_customers':     customers.count(),
            'total_lent':          round(total_lent, 2),
            'total_payable':       round(total_payable, 2),
            'total_collected':     round(total_collected, 2),
            'total_pending':       round(total_pending, 2),
            'active_loans':        active_count,
            'closed_loans':        closed_count,
            'overdue_emis':        overdue_count,
            'monthly_collections': result,
        })

    # ── Period builders ──────────────────────────────────────────────

    def _build_monthly_periods(self, today, count):
        """Last N months, one period per month."""
        periods = []
        for i in range(count - 1, -1, -1):
            m = today.month - i
            y = today.year
            while m <= 0:
                m += 12
                y -= 1
            # First and last day of the month
            first = date(y, m, 1)
            if m == 12:
                last = date(y + 1, 1, 1) - timedelta(days=1)
            else:
                last = date(y, m + 1, 1) - timedelta(days=1)
            periods.append({
                'label': first.strftime('%b'),
                'start': first,
                'end':   min(last, today),
            })
        return periods

    def _build_day_periods(self, today, count):
        """Last N days, one period per day."""
        periods = []
        for i in range(count - 1, -1, -1):
            d = today - timedelta(days=i)
            periods.append({
                'label': d.strftime('%d %b') if count > 7 else d.strftime('%a'),
                'start': d,
                'end':   d,
            })
        return periods

    def _build_week_periods(self, today, days):
        """Group into weeks."""
        periods = []
        start = today - timedelta(days=days - 1)
        current = start
        while current <= today:
            week_end = min(current + timedelta(days=6), today)
            periods.append({
                'label': f"{current.strftime('%d %b')}",
                'start': current,
                'end':   week_end,
            })
            current = week_end + timedelta(days=1)
        return periods

    def _build_daily_periods(self, today):
        """Today broken into morning / afternoon / evening / night."""
        periods = [
            {'label': 'Morn',  'start': today, 'end': today},
            {'label': 'After', 'start': today, 'end': today},
            {'label': 'Eve',   'start': today, 'end': today},
            {'label': 'Night', 'start': today, 'end': today},
        ]
        # For daily we just return today as one period for simplicity
        return [{'label': 'Today', 'start': today, 'end': today}]


# ═══════════════════════════════════════════════════════════════════════
#  REMINDERS VIEW
# ═══════════════════════════════════════════════════════════════════════

class RemindersView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        now          = timezone.now().date()
        upcoming_end = now + timedelta(days=3)

        base_qs = EmiPayment.objects.filter(
            loan__customer__vendor=request.user,
            is_paid=False,
        ).select_related('loan__customer')

        def format_item(emi):
            return {
                'emi_id':             emi.id,
                'loan_id':            emi.loan.id,
                'installment_number': emi.installment_number,
                'due_date':           emi.due_date,
                'emi_amount':         float(emi.emi_amount),
                'paid_amount':        float(emi.paid_amount),
                'customer': {
                    'id':             emi.loan.customer.id,
                    'name':           emi.loan.customer.name,
                    'phone':          emi.loan.customer.phone,
                    'vehicle_type':   emi.loan.customer.vehicle_type,
                    'vehicle_number': emi.loan.customer.vehicle_number,
                },
                'days_overdue': max(0, (now - emi.due_date).days) if emi.due_date < now else 0,
                'days_left':    max(0, (emi.due_date - now).days) if emi.due_date >= now else 0,
            }

        overdue  = [format_item(e) for e in base_qs.filter(due_date__lt=now).order_by('due_date')]
        today    = [format_item(e) for e in base_qs.filter(due_date=now)]
        upcoming = [format_item(e) for e in base_qs.filter(due_date__gt=now, due_date__lte=upcoming_end).order_by('due_date')]

        return Response({
            'overdue':  overdue,
            'today':    today,
            'upcoming': upcoming,
        })


# ═══════════════════════════════════════════════════════════════════════
#  STATEMENT VIEW
# ═══════════════════════════════════════════════════════════════════════

class StatementView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, loan_id):
        try:
            loan = Loan.objects.prefetch_related('emi_payments').get(
                id=loan_id, customer__vendor=request.user
            )
        except Loan.DoesNotExist:
            return Response({'error': 'Loan not found'}, status=404)

        customer = loan.customer
        now      = timezone.now().date()

        schedule = []
        for emi in loan.emi_payments.all():
            schedule.append({
                'installment_number': emi.installment_number,
                'due_date':           emi.due_date,
                'emi_amount':         float(emi.emi_amount),
                'paid_amount':        float(emi.paid_amount),
                'is_paid':            emi.is_paid,
                'paid_date':          emi.paid_date,
                'is_overdue':         not emi.is_paid and emi.due_date < now,
                'balance':            max(0, float(emi.emi_amount) - float(emi.paid_amount)),
            })

        return Response({
            'generated_on': now,
            'vendor': {
                'business_name': getattr(request.user, 'vendor_profile', None)
                    and request.user.vendor_profile.business_name or '',
            },
            'customer': {
                'name':           customer.name,
                'phone':          customer.phone,
                'address':        customer.address,
                'vehicle_type':   customer.vehicle_type,
                'vehicle_model':  customer.vehicle_model,
                'vehicle_number': customer.vehicle_number,
            },
            'loan': {
                'id':            loan.id,
                'loan_amount':   float(loan.loan_amount),
                'interest_rate': float(loan.interest_rate),
                'tenure_months': loan.tenure_months,
                'loan_date':     loan.loan_date,
                'total_interest':round(loan.total_interest, 2),
                'total_payable': round(loan.total_payable, 2),
                'emi':           round(loan.emi, 2),
                'total_paid':    round(loan.total_paid, 2),
                'remaining':     round(loan.remaining, 2),
                'paid_count':    loan.paid_count,
                'is_active':     loan.is_active,
            },
            'guarantor': {
                'name':     loan.guarantor_name,
                'phone':    loan.guarantor_phone,
                'address':  loan.guarantor_address,
                'aadhaar':  loan.guarantor_aadhaar,
                'relation': loan.guarantor_relation,
            },
            'emi_schedule': schedule,
        })