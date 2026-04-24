from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta, date, datetime
from .models import Customer, Loan, EmiPayment, GoldItem, LoanPhoto
from .serializers import (
    CustomerListSerializer, CustomerDetailSerializer,
    CustomerCreateSerializer, LoanSerializer,
    LoanCreateSerializer, EmiPaymentSerializer,
    GoldItemSerializer, GoldItemCreateSerializer,
)
from .utils import generate_emi_schedule, regenerate_unpaid_schedule
from django.conf import settings
from supabase import create_client
from .supabase_client import supabase
import uuid

# ── PDF imports ───────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable,
)
from io import BytesIO
from django.http import HttpResponse

ALLOWED_PHOTO_TYPES = {
    'vehicle': ['customer', 'vehicle', 'rc_book'],
    'gold':    ['customer', 'gold_items'],
}

MAX_PHOTOS_PER_TYPE = 4


# ═══════════════════════════════════════════════════════════════════════
#  PDF GENERATION HELPERS
# ═══════════════════════════════════════════════════════════════════════

# Brand colours
_PRIMARY   = colors.HexColor('#1a56db')
_SECONDARY = colors.HexColor('#1e429f')
_ACCENT    = colors.HexColor('#e1effe')
_GOLD      = colors.HexColor('#b7791f')
_GOLD_BG   = colors.HexColor('#fefce8')
_SUCCESS   = colors.HexColor('#057a55')
_DANGER    = colors.HexColor('#c81e1e')
_MUTED     = colors.HexColor('#6b7280')
_DARK      = colors.HexColor('#111827')
_LIGHT     = colors.HexColor('#f9fafb')
_BORDER    = colors.HexColor('#d1d5db')
_WHITE     = colors.white


def _pdf_styles():
    return {
        'title': ParagraphStyle(
            'title', fontSize=20, textColor=_WHITE,
            fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=2,
        ),
        'subtitle': ParagraphStyle(
            'subtitle', fontSize=9, textColor=colors.HexColor('#bfdbfe'),
            fontName='Helvetica', alignment=TA_CENTER,
        ),
        'section': ParagraphStyle(
            'section', fontSize=10, textColor=_PRIMARY,
            fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=4,
        ),
        'small': ParagraphStyle(
            'small', fontSize=7.5, textColor=_MUTED,
            fontName='Helvetica', alignment=TA_CENTER,
        ),
    }


def _fmt_inr(val):
    try:
        s = f"{abs(float(val)):,.2f}"
        return f"Rs. {s}"
    except Exception:
        return str(val)


def _p(text, size=8, bold=False, color=None, align=TA_LEFT):
    """Quick Paragraph factory."""
    return Paragraph(text, ParagraphStyle(
        '_p',
        fontSize=size,
        fontName='Helvetica-Bold' if bold else 'Helvetica',
        textColor=color or _DARK,
        alignment=align,
    ))


def _info_table(rows, avail_width):
    col_widths = [avail_width * 0.38, avail_width * 0.62]
    data = []
    for label, value in rows:
        data.append([
            _p(label, size=8, color=_MUTED),
            _p(str(value), size=8.5, bold=True),
        ])
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('GRID',          (0, 0), (-1, -1), 0.3, _BORDER),
        ('ROWBACKGROUNDS',(0, 0), (-1, -1), [_WHITE, _LIGHT]),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return t


def _amount_card(label, value, bg_color, text_color):
    inner = Table(
        [
            [_p(label, size=7.5, color=_MUTED, align=TA_CENTER)],
            [_p(value, size=9,   color=text_color, bold=True, align=TA_CENTER)],
        ],
    )
    inner.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), bg_color),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ('GRID',          (0, 0), (-1, -1), 0.3, _BORDER),
    ]))
    return inner


def generate_loan_statement_pdf(loan) -> bytes:
    buf    = BytesIO()
    PAGE_W, PAGE_H = A4
    MARGIN = 15 * mm
    avail  = PAGE_W - 2 * MARGIN

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN,  bottomMargin=MARGIN,
    )

    s        = _pdf_styles()
    story    = []
    now      = timezone.now().date()
    customer = loan.customer
    is_gold  = customer.loan_type == 'gold'

    # ── Header ─────────────────────────────────────────────────────────
    hdr = Table(
        [[
            Paragraph("LOAN STATEMENT", s['title']),
            Paragraph(
                f"Loan #{loan.id} &nbsp;|&nbsp; {now.strftime('%d %b %Y')}",
                s['subtitle'],
            ),
        ]],
        colWidths=[avail],
    )
    hdr.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), _PRIMARY),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING',   (0, 0), (-1, -1), 12),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 12),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 5 * mm))

    # ── Badges ─────────────────────────────────────────────────────────
    badge_color = _GOLD if is_gold else _PRIMARY
    badge_bg    = _GOLD_BG if is_gold else _ACCENT
    badge_label = "GOLD LOAN" if is_gold else "VEHICLE LOAN"
    status_color = _DANGER if loan.is_active else _SUCCESS
    status_label = "ACTIVE"  if loan.is_active else "CLOSED"

    badges = Table(
        [[
            _p(badge_label, size=8, bold=True, color=badge_color, align=TA_CENTER),
            _p(status_label, size=8, bold=True, color=status_color, align=TA_CENTER),
        ]],
        colWidths=[35 * mm, 30 * mm],
    )
    badges.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (0, 0), badge_bg),
        ('BACKGROUND',    (1, 0), (1, 0),
         colors.HexColor('#f0fdf4') if not loan.is_active else colors.HexColor('#fef2f2')),
        ('GRID',          (0, 0), (-1, -1), 0.5, _BORDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(badges)
    story.append(Spacer(1, 5 * mm))

    # ── Summary cards ──────────────────────────────────────────────────
    summary = Table(
        [[
            _amount_card("Loan Amount",   _fmt_inr(loan.loan_amount),   _ACCENT,  _PRIMARY),
            _amount_card("Total Payable", _fmt_inr(loan.total_payable), _ACCENT,  _PRIMARY),
            _amount_card("Total Paid",    _fmt_inr(loan.total_paid),
                         colors.HexColor('#d1fae5'), _SUCCESS),
            _amount_card("Remaining",     _fmt_inr(loan.remaining),
                         colors.HexColor('#fee2e2') if loan.remaining > 0 else colors.HexColor('#d1fae5'),
                         _DANGER if loan.remaining > 0 else _SUCCESS),
        ]],
        colWidths=[avail / 4] * 4,
    )
    summary.setStyle(TableStyle([
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        ('TOPPADDING',    (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(summary)
    story.append(Spacer(1, 5 * mm))

    # ── Customer details ───────────────────────────────────────────────
    story.append(Paragraph("Customer Details", s['section']))
    cust_rows = [
        ("Name",    customer.name),
        ("Phone",   customer.phone),
        ("Address", customer.address),
    ]
    if customer.aadhaar:  cust_rows.append(("Aadhaar", customer.aadhaar))
    if customer.pan_card: cust_rows.append(("PAN",     customer.pan_card))
    story.append(_info_table(cust_rows, avail))
    story.append(Spacer(1, 3 * mm))

    # ── Vehicle or Gold details ────────────────────────────────────────
    if not is_gold:
        if customer.vehicle_model or customer.vehicle_number:
            story.append(Paragraph("Vehicle Details", s['section']))
            veh_rows = []
            if customer.vehicle_type:   veh_rows.append(("Type",   customer.vehicle_type))
            if customer.vehicle_model:  veh_rows.append(("Model",  customer.vehicle_model))
            if customer.vehicle_number: veh_rows.append(("Number", customer.vehicle_number))
            story.append(_info_table(veh_rows, avail))
            story.append(Spacer(1, 3 * mm))
    else:
        gold_items = list(customer.gold_items.all())
        if gold_items:
            story.append(Paragraph("Gold Items", s['section']))
            gi_hdr = [
                _p("#",           size=8, bold=True, color=_WHITE, align=TA_CENTER),
                _p("Item",        size=8, bold=True, color=_WHITE),
                _p("Description", size=8, bold=True, color=_WHITE),
                _p("Wt (g)",      size=8, bold=True, color=_WHITE, align=TA_RIGHT),
                _p("Purity",      size=8, bold=True, color=_WHITE, align=TA_CENTER),
                _p("Est. Value",  size=8, bold=True, color=_WHITE, align=TA_RIGHT),
            ]
            gi_rows  = [gi_hdr]
            total_wt = total_val = 0
            for idx, item in enumerate(gold_items, 1):
                total_wt  += float(item.weight_grams)
                total_val += float(item.estimated_value)
                gi_rows.append([
                    _p(str(idx), size=8, align=TA_CENTER),
                    _p(item.item_type, size=8),
                    _p(item.item_description or '-', size=8),
                    _p(f"{float(item.weight_grams):.3f}", size=8, align=TA_RIGHT),
                    _p(item.purity, size=8, align=TA_CENTER),
                    _p(_fmt_inr(item.estimated_value), size=8, align=TA_RIGHT),
                ])
            gi_rows.append([
                '', '',
                _p("Total", size=8, bold=True),
                _p(f"{total_wt:.3f}", size=8, bold=True, align=TA_RIGHT),
                '',
                _p(_fmt_inr(total_val), size=8, bold=True, align=TA_RIGHT),
            ])
            cw = avail / 6
            gi_tbl = Table(gi_rows, colWidths=[cw*0.4, cw*0.8, cw*1.4, cw*0.7, cw*0.7, cw*1.0])
            gi_tbl.setStyle(TableStyle([
                ('BACKGROUND',    (0, 0), (-1, 0), _GOLD),
                ('BACKGROUND',    (0, -1), (-1, -1), _GOLD_BG),
                ('GRID',          (0, 0), (-1, -1), 0.3, _BORDER),
                ('ROWBACKGROUNDS',(0, 1), (-1, -2), [_WHITE, _LIGHT]),
                ('TOPPADDING',    (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING',   (0, 0), (-1, -1), 4),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
            ]))
            story.append(gi_tbl)
            story.append(Spacer(1, 3 * mm))

    # ── Loan details ───────────────────────────────────────────────────
    story.append(Paragraph("Loan Details", s['section']))
    loan_rows = [
        ("Loan Date",      loan.loan_date.strftime('%d %b %Y')),
        ("Loan Amount",    _fmt_inr(loan.loan_amount)),
        ("Interest Rate",  f"{float(loan.interest_rate):.2f}% per annum"),
        ("Tenure",         f"{loan.tenure_months} months"),
        ("Monthly EMI",    _fmt_inr(loan.emi)),
        ("Total Interest", _fmt_inr(loan.total_interest)),
        ("Total Payable",  _fmt_inr(loan.total_payable)),
        ("EMIs Paid",      f"{loan.paid_count} / {loan.tenure_months}"),
        ("Total Paid",     _fmt_inr(loan.total_paid)),
        ("Remaining",      _fmt_inr(loan.remaining)),
    ]
    if float(loan.fine_amount) > 0:
        loan_rows.append(("Fine Amount", _fmt_inr(loan.fine_amount)))
    story.append(_info_table(loan_rows, avail))
    story.append(Spacer(1, 3 * mm))

    # ── Guarantor ──────────────────────────────────────────────────────
    if loan.guarantor_name:
        story.append(Paragraph("Guarantor Details", s['section']))
        g_rows = [("Name", loan.guarantor_name)]
        if loan.guarantor_phone:    g_rows.append(("Phone",    loan.guarantor_phone))
        if loan.guarantor_address:  g_rows.append(("Address",  loan.guarantor_address))
        if loan.guarantor_aadhaar:  g_rows.append(("Aadhaar",  loan.guarantor_aadhaar))
        if loan.guarantor_relation: g_rows.append(("Relation", loan.guarantor_relation))
        story.append(_info_table(g_rows, avail))
        story.append(Spacer(1, 3 * mm))

    # ── EMI Schedule ───────────────────────────────────────────────────
    story.append(Paragraph("EMI Payment Schedule", s['section']))

    emi_hdr = [
        _p("#",        size=8, bold=True, color=_WHITE, align=TA_CENTER),
        _p("Due Date", size=8, bold=True, color=_WHITE),
        _p("EMI Amt",  size=8, bold=True, color=_WHITE, align=TA_RIGHT),
        _p("Paid Amt", size=8, bold=True, color=_WHITE, align=TA_RIGHT),
        _p("Balance",  size=8, bold=True, color=_WHITE, align=TA_RIGHT),
        _p("Paid On",  size=8, bold=True, color=_WHITE),
        _p("Status",   size=8, bold=True, color=_WHITE, align=TA_CENTER),
    ]
    emi_rows = [emi_hdr]
    ts_cmds  = [
        ('BACKGROUND',    (0, 0), (-1, 0), _PRIMARY),
        ('GRID',          (0, 0), (-1, -1), 0.3, _BORDER),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [_WHITE, _LIGHT]),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
    ]

    for i, emi in enumerate(loan.emi_payments.all(), start=1):
        balance = max(0, float(emi.emi_amount) - float(emi.paid_amount))
        overdue = not emi.is_paid and emi.due_date < now

        if emi.is_paid:
            status_txt   = "PAID"
            status_color = _SUCCESS
            ts_cmds.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f0fdf4')))
        elif overdue:
            status_txt   = "OVERDUE"
            status_color = _DANGER
            ts_cmds.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#fff7f7')))
        else:
            status_txt   = "PENDING"
            status_color = _MUTED

        emi_rows.append([
            _p(str(emi.installment_number), size=8, align=TA_CENTER),
            _p(emi.due_date.strftime('%d %b %Y'), size=8),
            _p(_fmt_inr(emi.emi_amount),  size=8, align=TA_RIGHT),
            _p(_fmt_inr(emi.paid_amount), size=8, align=TA_RIGHT),
            _p(_fmt_inr(balance),         size=8, align=TA_RIGHT),
            _p(emi.paid_date.strftime('%d %b %Y') if emi.paid_date else '-', size=8),
            _p(status_txt, size=7.5, bold=True, color=status_color, align=TA_CENTER),
        ])

    cw2 = avail / 7
    emi_tbl = Table(
        emi_rows,
        colWidths=[cw2*0.5, cw2*1.2, cw2*1.1, cw2*1.1, cw2*1.0, cw2*1.2, cw2*0.9],
        repeatRows=1,
    )
    emi_tbl.setStyle(TableStyle(ts_cmds))
    story.append(emi_tbl)
    story.append(Spacer(1, 6 * mm))

    # ── Footer ─────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=_BORDER))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        f"This is a computer-generated statement. Generated on {now.strftime('%d %b %Y')}.",
        s['small'],
    ))

    doc.build(story)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════
#  CUSTOMER VIEWS
# ═══════════════════════════════════════════════════════════════════════

class CustomerListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Customer.objects.filter(
            vendor=self.request.user
        ).prefetch_related('loans__emi_payments', 'gold_items')

        q         = self.request.query_params.get('q', '').strip()
        loan_type = self.request.query_params.get('loan_type', '').strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(phone__icontains=q) |
                Q(vehicle_model__icontains=q) |
                Q(vehicle_number__icontains=q)
            )
        if loan_type in ('vehicle', 'gold'):
            qs = qs.filter(loan_type=loan_type)

        return qs

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CustomerCreateSerializer
        return CustomerListSerializer

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
        ).prefetch_related('loans__emi_payments', 'gold_items')

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return CustomerCreateSerializer
        return CustomerDetailSerializer


# ═══════════════════════════════════════════════════════════════════════
#  GOLD ITEM VIEWS
# ═══════════════════════════════════════════════════════════════════════

class GoldItemListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return GoldItem.objects.filter(
            customer__vendor=self.request.user,
            customer_id=self.kwargs.get('customer_id'),
        )

    def get_serializer_class(self):
        return GoldItemCreateSerializer if self.request.method == 'POST' else GoldItemSerializer

    def create(self, request, *args, **kwargs):
        try:
            customer = Customer.objects.get(
                id=self.kwargs.get('customer_id'),
                vendor=request.user,
                loan_type='gold',
            )
        except Customer.DoesNotExist:
            return Response({'error': 'Gold loan customer not found'}, status=404)

        serializer = GoldItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save(customer=customer)
        return Response(GoldItemSerializer(item).data, status=status.HTTP_201_CREATED)


class GoldItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return GoldItem.objects.filter(customer__vendor=self.request.user)

    def get_serializer_class(self):
        return GoldItemCreateSerializer if self.request.method in ['PUT', 'PATCH'] else GoldItemSerializer


# ═══════════════════════════════════════════════════════════════════════
#  LOAN VIEWS
# ═══════════════════════════════════════════════════════════════════════

class LoanListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LoanSerializer

    def get_queryset(self):
        return Loan.objects.filter(
            customer__vendor=self.request.user,
            customer_id=self.kwargs.get('customer_id'),
        ).prefetch_related('emi_payments')

    def create(self, request, *args, **kwargs):
        try:
            customer = Customer.objects.get(
                id=self.kwargs.get('customer_id'), vendor=request.user
            )
        except Customer.DoesNotExist:
            return Response({'error': 'Customer not found'}, status=404)

        serializer = LoanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = serializer.save(customer=customer)
        generate_emi_schedule(loan)
        return Response(LoanSerializer(loan).data, status=status.HTTP_201_CREATED)


class LoanDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Loan.objects.filter(
            customer__vendor=self.request.user
        ).prefetch_related('emi_payments')

    def get_serializer_class(self):
        return LoanCreateSerializer if self.request.method in ['PUT', 'PATCH'] else LoanSerializer

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        loan    = self.get_object()
        serializer = LoanCreateSerializer(loan, data=request.data, partial=partial)
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
            loan = Loan.objects.get(id=loan_id, customer__vendor=request.user)
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
        emi.is_paid     = paid_amount >= float(emi.emi_amount)

        if paid_amount > 0:
            payment_date_str = request.data.get('payment_date')
            if payment_date_str:
                try:
                    emi.paid_date = datetime.strptime(payment_date_str, '%Y-%m-%d').date()
                except ValueError:
                    emi.paid_date = date.today()
            else:
                emi.paid_date = date.today()
        else:
            emi.paid_date = None

        emi.save()
        return Response(EmiPaymentSerializer(emi).data)


# ═══════════════════════════════════════════════════════════════════════
#  DASHBOARD VIEW
# ═══════════════════════════════════════════════════════════════════════

class DashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        loan_type_filter = request.query_params.get('loan_type', 'all')

        customers_qs = Customer.objects.filter(vendor=request.user)
        loans_qs     = Loan.objects.filter(
            customer__vendor=request.user
        ).prefetch_related('emi_payments')

        if loan_type_filter in ('vehicle', 'gold'):
            customers_qs = customers_qs.filter(loan_type=loan_type_filter)
            loans_qs     = loans_qs.filter(customer__loan_type=loan_type_filter)

        loans = list(loans_qs)

        total_lent      = sum(float(l.loan_amount) for l in loans)
        total_payable   = sum(l.total_payable for l in loans)
        total_collected = sum(l.total_paid for l in loans)
        total_pending   = max(0, total_payable - total_collected)
        active_count    = sum(1 for l in loans if l.is_active)
        closed_count    = sum(1 for l in loans if not l.is_active)

        gold_customers    = Customer.objects.filter(vendor=request.user, loan_type='gold').prefetch_related('gold_items')
        total_gold_weight = sum(float(item.weight_grams) for c in gold_customers for item in c.gold_items.all())
        total_gold_value  = sum(float(item.estimated_value) for c in gold_customers for item in c.gold_items.all())

        now        = timezone.now().date()
        overdue_qs = EmiPayment.objects.filter(
            loan__customer__vendor=request.user, is_paid=False, due_date__lt=now,
        )
        if loan_type_filter in ('vehicle', 'gold'):
            overdue_qs = overdue_qs.filter(loan__customer__loan_type=loan_type_filter)
        overdue_count = overdue_qs.count()

        mode       = request.query_params.get('mode', 'monthly')
        days_param = request.query_params.get('days', None)

        if mode == 'daily' or (days_param and int(days_param) == 1):
            periods = [{'label': 'Today', 'start': now, 'end': now}]
        elif mode == 'weekly' or (days_param and int(days_param) == 7):
            periods = self._build_day_periods(now, 7)
        elif days_param:
            days    = int(days_param)
            periods = (
                self._build_day_periods(now, days)
                if days <= 31
                else self._build_week_periods(now, days)
            )
        else:
            periods = self._build_monthly_periods(now, 6)

        result = []
        for period in periods:
            paid_emis_qs = EmiPayment.objects.filter(
                loan__customer__vendor=request.user,
                is_paid=True,
                paid_date__gte=period['start'],
                paid_date__lte=period['end'],
            )
            loans_given_qs = Loan.objects.filter(
                customer__vendor=request.user,
                loan_date__gte=period['start'],
                loan_date__lte=period['end'],
            )
            if loan_type_filter in ('vehicle', 'gold'):
                paid_emis_qs   = paid_emis_qs.filter(loan__customer__loan_type=loan_type_filter)
                loans_given_qs = loans_given_qs.filter(customer__loan_type=loan_type_filter)

            result.append({
                'month':     period['label'],
                'year':      period['start'].year,
                'collected': round(sum(float(e.paid_amount) for e in paid_emis_qs), 2),
                'expected':  round(sum(float(l.loan_amount) for l in loans_given_qs), 2),
                'start':     period['start'].isoformat(),
                'end':       period['end'].isoformat(),
            })

        return Response({
            'total_customers':         customers_qs.count(),
            'vehicle_customers':       Customer.objects.filter(vendor=request.user, loan_type='vehicle').count(),
            'gold_customers':          gold_customers.count(),
            'total_lent':              round(total_lent, 2),
            'total_payable':           round(total_payable, 2),
            'total_collected':         round(total_collected, 2),
            'total_pending':           round(total_pending, 2),
            'active_loans':            active_count,
            'closed_loans':            closed_count,
            'overdue_emis':            overdue_count,
            'total_gold_weight_grams': round(total_gold_weight, 3),
            'total_gold_value':        round(total_gold_value, 2),
            'monthly_collections':     result,
        })

    def _build_monthly_periods(self, today, count):
        periods = []
        for i in range(count - 1, -1, -1):
            m = today.month - i
            y = today.year
            while m <= 0:
                m += 12; y -= 1
            first = date(y, m, 1)
            last  = (
                date(y + 1, 1, 1) - timedelta(days=1)
                if m == 12
                else date(y, m + 1, 1) - timedelta(days=1)
            )
            periods.append({'label': first.strftime('%b'), 'start': first, 'end': min(last, today)})
        return periods

    def _build_day_periods(self, today, count):
        return [
            {
                'label': (today - timedelta(days=i)).strftime('%d %b' if count > 7 else '%a'),
                'start': today - timedelta(days=i),
                'end':   today - timedelta(days=i),
            }
            for i in range(count - 1, -1, -1)
        ]

    def _build_week_periods(self, today, days):
        periods = []
        current = today - timedelta(days=days - 1)
        while current <= today:
            week_end = min(current + timedelta(days=6), today)
            periods.append({'label': current.strftime('%d %b'), 'start': current, 'end': week_end})
            current = week_end + timedelta(days=1)
        return periods


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

        def fmt(emi):
            c = emi.loan.customer
            return {
                'emi_id':             emi.id,
                'loan_id':            emi.loan.id,
                'installment_number': emi.installment_number,
                'due_date':           emi.due_date,
                'emi_amount':         float(emi.emi_amount),
                'paid_amount':        float(emi.paid_amount),
                'customer': {
                    'id':             c.id,
                    'name':           c.name,
                    'phone':          c.phone,
                    'loan_type':      c.loan_type,
                    'vehicle_type':   c.vehicle_type,
                    'vehicle_number': c.vehicle_number,
                },
                'days_overdue': max(0, (now - emi.due_date).days) if emi.due_date < now else 0,
                'days_left':    max(0, (emi.due_date - now).days) if emi.due_date >= now else 0,
            }

        return Response({
            'overdue':  [fmt(e) for e in base_qs.filter(due_date__lt=now).order_by('due_date')],
            'today':    [fmt(e) for e in base_qs.filter(due_date=now)],
            'upcoming': [fmt(e) for e in base_qs.filter(due_date__gt=now, due_date__lte=upcoming_end).order_by('due_date')],
        })


# ═══════════════════════════════════════════════════════════════════════
#  STATEMENT VIEW  (JSON — existing)
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

        schedule = [
            {
                'installment_number': e.installment_number,
                'due_date':           e.due_date,
                'emi_amount':         float(e.emi_amount),
                'paid_amount':        float(e.paid_amount),
                'is_paid':            e.is_paid,
                'paid_date':          e.paid_date,
                'is_overdue':         not e.is_paid and e.due_date < now,
                'balance':            max(0, float(e.emi_amount) - float(e.paid_amount)),
            }
            for e in loan.emi_payments.all()
        ]

        gold_items = []
        if customer.loan_type == 'gold':
            gold_items = [
                {
                    'item_type':        item.item_type,
                    'item_description': item.item_description,
                    'weight_grams':     float(item.weight_grams),
                    'purity':           item.purity,
                    'estimated_value':  float(item.estimated_value),
                }
                for item in customer.gold_items.all()
            ]

        return Response({
            'generated_on': now,
            'vendor': {
                'business_name': (
                    getattr(request.user, 'vendor_profile', None)
                    and request.user.vendor_profile.business_name or ''
                ),
            },
            'customer': {
                'name':              customer.name,
                'phone':             customer.phone,
                'address':           customer.address,
                'loan_type':         customer.loan_type,
                'vehicle_type':      customer.vehicle_type,
                'vehicle_model':     customer.vehicle_model,
                'vehicle_number':    customer.vehicle_number,
                'gold_items':        gold_items,
                'total_gold_weight': sum(i['weight_grams'] for i in gold_items),
                'total_gold_value':  sum(i['estimated_value'] for i in gold_items),
            },
            'loan': {
                'id':            loan.id,
                'loan_amount':   float(loan.loan_amount),
                'interest_rate': float(loan.interest_rate),
                'tenure_months': loan.tenure_months,
                'loan_date':     loan.loan_date,
                'fine_amount':   float(loan.fine_amount),
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


# ═══════════════════════════════════════════════════════════════════════
#  ✅ NEW — PDF STATEMENT VIEW
# ═══════════════════════════════════════════════════════════════════════

class LoanStatementPDFView(APIView):
    """
    GET /loans/<loan_id>/statement/pdf/

    Returns a styled PDF of the full loan statement.
    Share directly via WhatsApp, SMS, or the system share sheet.

    Query params:
      ?download=true   →  Content-Disposition: attachment  (force download)
      (default)        →  Content-Disposition: inline      (open in viewer)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, loan_id):
        try:
            loan = Loan.objects.prefetch_related(
                'emi_payments', 'customer__gold_items'
            ).get(id=loan_id, customer__vendor=request.user)
        except Loan.DoesNotExist:
            return Response({'error': 'Loan not found'}, status=404)

        pdf_bytes = generate_loan_statement_pdf(loan)

        customer_name = loan.customer.name.replace(' ', '_')
        filename      = f"Loan_{loan.id}_{customer_name}_Statement.pdf"
        disposition   = 'attachment' if request.query_params.get('download') else 'inline'

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
        response['Content-Length']      = len(pdf_bytes)
        return response


# ═══════════════════════════════════════════════════════════════════════
#  PHOTO VIEWS
# ═══════════════════════════════════════════════════════════════════════

class UploadPhotoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, customer_id):
        try:
            customer = Customer.objects.get(id=customer_id, vendor=request.user)
        except Customer.DoesNotExist:
            return Response({'error': 'Customer not found'}, status=404)

        photo_type = request.data.get('photo_type', '').strip()
        file       = request.FILES.get('photo')

        if not photo_type or not file:
            return Response({'error': 'photo_type and photo are required'}, status=400)

        allowed = ALLOWED_PHOTO_TYPES.get(customer.loan_type, [])
        if photo_type not in allowed:
            return Response(
                {'error': f"Invalid photo_type for {customer.loan_type} loan. Allowed: {allowed}"},
                status=400,
            )

        existing_count = LoanPhoto.objects.filter(customer=customer, photo_type=photo_type).count()
        if existing_count >= MAX_PHOTOS_PER_TYPE:
            return Response(
                {'error': (
                    f"Maximum {MAX_PHOTOS_PER_TYPE} photos allowed per type. "
                    f"Please delete an existing '{photo_type}' photo before uploading a new one."
                )},
                status=400,
            )

        bucket_name  = settings.SUPABASE_STORAGE_BUCKET
        ext          = file.name.rsplit('.', 1)[-1].lower() if '.' in file.name else 'jpg'
        unique_id    = uuid.uuid4().hex[:8]
        storage_path = (
            f"{customer.loan_type}-loans/{customer.id}/{photo_type}_{unique_id}.{ext}"
        )

        try:
            supabase.storage.from_(bucket_name).upload(
                path=storage_path,
                file=file.read(),
                file_options={'content-type': file.content_type or 'image/jpeg', 'upsert': 'true'},
            )
            public_url = supabase.storage.from_(bucket_name).get_public_url(storage_path)
        except Exception as e:
            print(f"Storage upload error: {str(e)}")
            return Response({'error': f'Storage upload failed: {str(e)}'}, status=500)

        photo = LoanPhoto.objects.create(customer=customer, photo_type=photo_type, photo_url=public_url)

        return Response(
            {
                'id':          photo.id,
                'photo_type':  photo_type,
                'photoUrl':    public_url,
                'uploaded_at': photo.uploaded_at.isoformat(),
                'count':       existing_count + 1,
                'max':         MAX_PHOTOS_PER_TYPE,
            },
            status=status.HTTP_201_CREATED,
        )


class GetPhotosView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, customer_id):
        try:
            customer = Customer.objects.get(id=customer_id, vendor=request.user)
        except Customer.DoesNotExist:
            return Response({'error': 'Customer not found'}, status=404)

        photos = LoanPhoto.objects.filter(customer=customer).order_by('uploaded_at')

        photo_list = [
            {
                'id':          p.id,
                'photoUrl':    p.photo_url,
                'photo_type':  p.photo_type,
                'uploaded_at': p.uploaded_at.isoformat(),
            }
            for p in photos
        ]

        allowed_types = ALLOWED_PHOTO_TYPES.get(customer.loan_type, [])
        counts        = {
            pt: sum(1 for p in photo_list if p['photo_type'] == pt)
            for pt in allowed_types
        }

        return Response({
            'photos':       photo_list,
            'counts':       counts,
            'max_per_type': MAX_PHOTOS_PER_TYPE,
        })


class DeletePhotoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, customer_id, photo_id):
        try:
            photo = LoanPhoto.objects.get(
                id=photo_id, customer__id=customer_id, customer__vendor=request.user,
            )
        except LoanPhoto.DoesNotExist:
            return Response({'error': 'Photo not found'}, status=404)

        bucket_name = settings.SUPABASE_STORAGE_BUCKET
        try:
            url    = photo.photo_url
            marker = f'/{bucket_name}/'
            if marker in url:
                storage_path = url.split(marker, 1)[1].split('?')[0]
                supabase.storage.from_(bucket_name).remove([storage_path])
        except Exception as e:
            print(f"Error deleting from Supabase: {str(e)}")

        photo.delete()
        return Response({'deleted': photo_id}, status=status.HTTP_200_OK)