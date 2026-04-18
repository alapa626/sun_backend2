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

ALLOWED_PHOTO_TYPES = {
    'vehicle': ['customer', 'vehicle', 'rc_book'],
    'gold':    ['customer', 'gold_items'],
}


# ═══════════════════════════════════════════════════════════════════════
#  CUSTOMER VIEWS
# ═══════════════════════════════════════════════════════════════════════

class CustomerListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Customer.objects.filter(
            vendor=self.request.user
        ).prefetch_related('loans__emi_payments', 'gold_items')

        q = self.request.query_params.get('q', '').strip()
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
        loan = self.get_object()
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
        emi.is_paid = paid_amount >= float(emi.emi_amount)

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
        loans_qs = Loan.objects.filter(
            customer__vendor=request.user
        ).prefetch_related('emi_payments')

        if loan_type_filter in ('vehicle', 'gold'):
            customers_qs = customers_qs.filter(loan_type=loan_type_filter)
            loans_qs = loans_qs.filter(customer__loan_type=loan_type_filter)

        loans = list(loans_qs)

        total_lent      = sum(float(l.loan_amount) for l in loans)
        total_payable   = sum(l.total_payable for l in loans)
        total_collected = sum(l.total_paid for l in loans)
        total_pending   = max(0, total_payable - total_collected)
        active_count    = sum(1 for l in loans if l.is_active)
        closed_count    = sum(1 for l in loans if not l.is_active)

        gold_customers = Customer.objects.filter(
            vendor=request.user, loan_type='gold'
        ).prefetch_related('gold_items')
        total_gold_weight = sum(
            float(item.weight_grams)
            for c in gold_customers for item in c.gold_items.all()
        )
        total_gold_value = sum(
            float(item.estimated_value)
            for c in gold_customers for item in c.gold_items.all()
        )

        now = timezone.now().date()
        overdue_qs = EmiPayment.objects.filter(
            loan__customer__vendor=request.user,
            is_paid=False,
            due_date__lt=now,
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
            days = int(days_param)
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
            'total_customers':          customers_qs.count(),
            'vehicle_customers':        Customer.objects.filter(vendor=request.user, loan_type='vehicle').count(),
            'gold_customers':           gold_customers.count(),
            'total_lent':               round(total_lent, 2),
            'total_payable':            round(total_payable, 2),
            'total_collected':          round(total_collected, 2),
            'total_pending':            round(total_pending, 2),
            'active_loans':             active_count,
            'closed_loans':             closed_count,
            'overdue_emis':             overdue_count,
            'total_gold_weight_grams':  round(total_gold_weight, 3),
            'total_gold_value':         round(total_gold_value, 2),
            'monthly_collections':      result,
        })

    def _build_monthly_periods(self, today, count):
        periods = []
        for i in range(count - 1, -1, -1):
            m = today.month - i
            y = today.year
            while m <= 0:
                m += 12
                y -= 1
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
#  PHOTO VIEWS
# ═══════════════════════════════════════════════════════════════════════

class UploadPhotoView(APIView):
    """
    POST /customers/<customer_id>/photos/upload/
    Form fields: photo_type (str), photo (file)
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, customer_id):
        try:
            customer = Customer.objects.get(
                id=customer_id, vendor=request.user
            )
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

        # Get bucket name from settings
        bucket_name = settings.SUPABASE_STORAGE_BUCKET
        
        ext          = file.name.rsplit('.', 1)[-1].lower() if '.' in file.name else 'jpg'
        storage_path = f"{customer.loan_type}-loans/{customer.id}/{photo_type}.{ext}"

        try:
            supabase.storage.from_(bucket_name).upload(
                path=storage_path,
                file=file.read(),
                file_options={
                    'content-type': file.content_type or 'image/jpeg',
                    'upsert': True,
                },
            )
            public_url = supabase.storage.from_(bucket_name).get_public_url(storage_path)

        except Exception as e:
            print(f"Storage upload error: {str(e)}")
            return Response({'error': f'Storage upload failed: {str(e)}'}, status=500)

        photo, _ = LoanPhoto.objects.update_or_create(
            customer=customer,
            photo_type=photo_type,
            defaults={'photo_url': public_url},
        )

        return Response({
            'id':         photo.id,
            'photo_type': photo_type,
            'photoUrl':   public_url,
        }, status=status.HTTP_201_CREATED)


class GetPhotosView(APIView):
    """
    GET /customers/<customer_id>/photos/

    Returns a LIST of photo objects so Flutter's PhotoService can
    read each photo's 'id' (for deletion) and 'photoUrl' (for display).

    Response shape:
    [
      { "id": 1, "photoUrl": "https://...", "photo_type": "customer" },
      { "id": 2, "photoUrl": "https://...", "photo_type": "vehicle"  },
      ...
    ]
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, customer_id):
        # Scope to the logged-in vendor so no other vendor can read another vendor's customer photos
        try:
            customer = Customer.objects.get(
                id=customer_id, vendor=request.user
            )
        except Customer.DoesNotExist:
            return Response({'error': 'Customer not found'}, status=404)

        photos = LoanPhoto.objects.filter(customer=customer)

        # Return as a list with 'id' and 'photoUrl' fields
        photo_list = [
            {
                'id':         p.id,
                'photoUrl':   p.photo_url,
                'photo_type': p.photo_type,
                'uploaded_at': p.uploaded_at.isoformat(),
            }
            for p in photos
        ]

        return Response(photo_list)


class DeletePhotoView(APIView):
    """
    DELETE /customers/<customer_id>/photos/<photo_id>/

    Flutter's delete button calls PhotoService.deletePhoto(photoId).
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, customer_id, photo_id):
        try:
            photo = LoanPhoto.objects.get(
                id=photo_id,
                customer__id=customer_id,
                customer__vendor=request.user,   # vendor-scoped for security
            )
        except LoanPhoto.DoesNotExist:
            return Response({'error': 'Photo not found'}, status=404)

        # Also delete from Supabase storage
        bucket_name = settings.SUPABASE_STORAGE_BUCKET
        
        try:
            # Extract the storage path from the public URL
            # URL pattern: https://<project>.supabase.co/storage/v1/object/public/<bucket>/<path>
            url      = photo.photo_url
            marker   = f'/{bucket_name}/'
            if marker in url:
                storage_path = url.split(marker, 1)[1]
                # Strip any query string (e.g. ?t=timestamp added by Supabase)
                storage_path = storage_path.split('?')[0]
                supabase.storage.from_(bucket_name).remove([storage_path])
        except Exception as e:
            # Don't fail the request if Supabase delete fails —
            # the DB record is the source of truth for Flutter.
            print(f"Error deleting from Supabase: {str(e)}")
            pass

        photo.delete()
        return Response({'deleted': photo_id}, status=status.HTTP_200_OK)