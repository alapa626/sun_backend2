from rest_framework import serializers
from django.utils import timezone
from .models import Customer, Loan, EmiPayment, GoldItem, DailyLedger
from .utils import generate_emi_schedule


# ═══════════════════════════════════════════════════════════════════════
#  GOLD ITEM
# ═══════════════════════════════════════════════════════════════════════

class GoldItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoldItem
        fields = [
            'id', 'item_type', 'item_description',
            'weight_grams', 'purity', 'estimated_value',
        ]


class GoldItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoldItem
        fields = [
            'item_type', 'item_description',
            'weight_grams', 'purity', 'estimated_value',
        ]


# ═══════════════════════════════════════════════════════════════════════
#  EMI PAYMENT
# ═══════════════════════════════════════════════════════════════════════

class EmiPaymentSerializer(serializers.ModelSerializer):
    balance    = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = EmiPayment
        fields = [
            'id', 'installment_number', 'due_date',
            'emi_amount', 'paid_amount', 'is_paid',
            'paid_date', 'balance', 'is_overdue',
        ]

    def get_balance(self, obj):
        if obj.is_paid:
            return 0
        return max(0, float(obj.emi_amount) - float(obj.paid_amount))

    def get_is_overdue(self, obj):
        if obj.is_paid:
            return False
        return obj.due_date < timezone.now().date()


# ═══════════════════════════════════════════════════════════════════════
#  LOAN
# ═══════════════════════════════════════════════════════════════════════

class LoanSerializer(serializers.ModelSerializer):
    emi_payments    = EmiPaymentSerializer(many=True, read_only=True)
    total_interest  = serializers.ReadOnlyField()
    total_payable   = serializers.ReadOnlyField()
    emi             = serializers.ReadOnlyField()
    total_paid      = serializers.ReadOnlyField()
    remaining       = serializers.ReadOnlyField()
    is_active       = serializers.ReadOnlyField()
    paid_count      = serializers.ReadOnlyField()
    net_disbursed   = serializers.ReadOnlyField()

    class Meta:
        model = Loan
        fields = [
            'id', 'customer', 'loan_amount', 'interest_rate',
            'tenure_months', 'loan_date', 'fine_amount', 'document_charge',
            'guarantor_name', 'guarantor_phone', 'guarantor_address',
            'guarantor_aadhaar', 'guarantor_relation',
            'total_interest', 'total_payable', 'emi',
            'net_disbursed',
            'total_paid', 'remaining', 'is_active', 'paid_count',
            'emi_payments', 'created_at',
        ]
        read_only_fields = ['customer', 'created_at']


class LoanCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Loan
        fields = [
            'loan_amount', 'interest_rate', 'tenure_months', 'loan_date',
            'fine_amount', 'document_charge',
            'guarantor_name', 'guarantor_phone', 'guarantor_address',
            'guarantor_aadhaar', 'guarantor_relation',
        ]


# ═══════════════════════════════════════════════════════════════════════
#  CUSTOMER — LIST
# ═══════════════════════════════════════════════════════════════════════

class CustomerListSerializer(serializers.ModelSerializer):
    active_loans_count = serializers.SerializerMethodField()
    total_loan_amount  = serializers.SerializerMethodField()
    total_gold_weight  = serializers.SerializerMethodField()
    gold_items_count   = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id', 'loan_type', 'name', 'phone', 'address', 'aadhaar', 'pan_card',
            'vehicle_type', 'vehicle_model', 'vehicle_number',
            'total_gold_weight', 'gold_items_count',
            'ml_collateral_type', 'ml_collateral_description',
            'ml_property_address', 'ml_survey_number',
            'ml_collateral_value', 'ml_document_type',
            'proof_description',
            'active_loans_count', 'total_loan_amount', 'created_at',
        ]

    def get_active_loans_count(self, obj):
        return sum(1 for loan in obj.loans.all() if loan.is_active)

    def get_total_loan_amount(self, obj):
        return sum(float(loan.loan_amount) for loan in obj.loans.all())

    def get_total_gold_weight(self, obj):
        if obj.loan_type != 'gold':
            return None
        return float(sum(item.weight_grams for item in obj.gold_items.all()))

    def get_gold_items_count(self, obj):
        if obj.loan_type != 'gold':
            return None
        return obj.gold_items.count()


# ═══════════════════════════════════════════════════════════════════════
#  CUSTOMER — DETAIL
# ═══════════════════════════════════════════════════════════════════════

class CustomerDetailSerializer(serializers.ModelSerializer):
    loans             = LoanSerializer(many=True, read_only=True)
    gold_items        = GoldItemSerializer(many=True, read_only=True)
    total_gold_weight = serializers.SerializerMethodField()
    total_gold_value  = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id', 'loan_type', 'name', 'phone', 'address', 'aadhaar', 'pan_card',
            'vehicle_type', 'vehicle_model', 'vehicle_number',
            'gold_items', 'total_gold_weight', 'total_gold_value',
            'ml_collateral_type', 'ml_collateral_description',
            'ml_property_address', 'ml_survey_number',
            'ml_collateral_value', 'ml_document_type',
            'proof_description',
            'loans', 'created_at',
        ]

    def get_total_gold_weight(self, obj):
        if obj.loan_type != 'gold':
            return None
        return float(sum(item.weight_grams for item in obj.gold_items.all()))

    def get_total_gold_value(self, obj):
        if obj.loan_type != 'gold':
            return None
        return float(sum(item.estimated_value for item in obj.gold_items.all()))


# ═══════════════════════════════════════════════════════════════════════
#  CUSTOMER — CREATE
# ═══════════════════════════════════════════════════════════════════════

class CustomerCreateSerializer(serializers.ModelSerializer):
    loan_amount      = serializers.DecimalField(max_digits=12, decimal_places=2, write_only=True)
    interest_rate    = serializers.DecimalField(max_digits=5, decimal_places=2, write_only=True, default=0)
    tenure_months    = serializers.IntegerField(write_only=True, default=12)
    loan_date        = serializers.DateField(write_only=True, required=False)
    fine_amount      = serializers.DecimalField(max_digits=10, decimal_places=2, write_only=True, default=0)
    document_charge  = serializers.DecimalField(max_digits=10, decimal_places=2, write_only=True, default=0)

    guarantor_name     = serializers.CharField(write_only=True, required=False, allow_blank=True)
    guarantor_phone    = serializers.CharField(write_only=True, required=False, allow_blank=True)
    guarantor_address  = serializers.CharField(write_only=True, required=False, allow_blank=True)
    guarantor_aadhaar  = serializers.CharField(write_only=True, required=False, allow_blank=True)
    guarantor_relation = serializers.CharField(write_only=True, required=False, allow_blank=True)

    gold_items = GoldItemCreateSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = Customer
        fields = [
            'id', 'loan_type',
            'name', 'phone', 'address', 'aadhaar', 'pan_card',
            'vehicle_type', 'vehicle_model', 'vehicle_number',
            'gold_items',
            'ml_collateral_type', 'ml_collateral_description',
            'ml_property_address', 'ml_survey_number',
            'ml_collateral_value', 'ml_document_type',
            'proof_description',
            'loan_amount', 'interest_rate', 'tenure_months', 'loan_date',
            'fine_amount', 'document_charge',
            'guarantor_name', 'guarantor_phone', 'guarantor_address',
            'guarantor_aadhaar', 'guarantor_relation',
        ]

    def validate(self, data):
        loan_type = data.get('loan_type', 'vehicle')
        if loan_type == 'vehicle':
            if not data.get('vehicle_model', '').strip():
                raise serializers.ValidationError(
                    {'vehicle_model': 'Vehicle model is required for vehicle loans.'}
                )
        elif loan_type == 'gold':
            gold_items = data.get('gold_items', [])
            if not gold_items:
                raise serializers.ValidationError(
                    {'gold_items': 'At least one gold item is required for gold loans.'}
                )
            for item in gold_items:
                if float(item.get('weight_grams', 0)) <= 0:
                    raise serializers.ValidationError(
                        {'gold_items': 'Each gold item must have weight greater than 0.'}
                    )
        elif loan_type == 'ml':
            if not data.get('ml_collateral_type', '').strip():
                raise serializers.ValidationError(
                    {'ml_collateral_type': 'Collateral type is required for ML loans.'}
                )
            if float(data.get('ml_collateral_value', 0)) <= 0:
                raise serializers.ValidationError(
                    {'ml_collateral_value': 'Collateral value must be greater than 0 for ML loans.'}
                )

        doc_charge = float(data.get('document_charge', 0))
        loan_amount = float(data.get('loan_amount', 0))
        if doc_charge < 0:
            raise serializers.ValidationError(
                {'document_charge': 'Document charge cannot be negative.'}
            )
        if doc_charge >= loan_amount:
            raise serializers.ValidationError(
                {'document_charge': 'Document charge must be less than loan amount.'}
            )
        return data

    def create(self, validated_data):
        loan_fields = {
            'loan_amount':        validated_data.pop('loan_amount'),
            'interest_rate':      validated_data.pop('interest_rate', 0),
            'tenure_months':      validated_data.pop('tenure_months', 12),
            'loan_date':          validated_data.pop('loan_date', timezone.now().date()),
            'fine_amount':        validated_data.pop('fine_amount', 0),
            'document_charge':    validated_data.pop('document_charge', 0),
            'guarantor_name':     validated_data.pop('guarantor_name', ''),
            'guarantor_phone':    validated_data.pop('guarantor_phone', ''),
            'guarantor_address':  validated_data.pop('guarantor_address', ''),
            'guarantor_aadhaar':  validated_data.pop('guarantor_aadhaar', ''),
            'guarantor_relation': validated_data.pop('guarantor_relation', ''),
        }
        gold_items_data = validated_data.pop('gold_items', [])
        loan_type       = validated_data.get('loan_type')

        if loan_type == 'gold':
            validated_data['vehicle_type']   = ''
            validated_data['vehicle_model']  = ''
            validated_data['vehicle_number'] = ''
            validated_data.setdefault('ml_collateral_type', '')
            validated_data.setdefault('ml_collateral_description', '')
            validated_data.setdefault('ml_property_address', '')
            validated_data.setdefault('ml_survey_number', '')
            validated_data.setdefault('ml_collateral_value', 0)
            validated_data.setdefault('ml_document_type', '')
        elif loan_type == 'vehicle':
            validated_data.setdefault('ml_collateral_type', '')
            validated_data.setdefault('ml_collateral_description', '')
            validated_data.setdefault('ml_property_address', '')
            validated_data.setdefault('ml_survey_number', '')
            validated_data.setdefault('ml_collateral_value', 0)
            validated_data.setdefault('ml_document_type', '')
        elif loan_type == 'ml':
            validated_data['vehicle_type']   = ''
            validated_data['vehicle_model']  = ''
            validated_data['vehicle_number'] = ''

        customer = Customer.objects.create(**validated_data)

        for item_data in gold_items_data:
            GoldItem.objects.create(customer=customer, **item_data)

        loan = Loan.objects.create(customer=customer, **loan_fields)
        generate_emi_schedule(loan)

        # Auto-create credit ledger entry for document charge
        if float(loan.document_charge) > 0:
            from .models import DailyLedger
            loan_label = {
                'vehicle': f"Vehicle Loan ({customer.vehicle_type} {customer.vehicle_model})".strip(),
                'gold':    'Gold Loan',
                'ml':      f"ML Loan ({customer.ml_collateral_type})".strip(),
            }.get(customer.loan_type, 'Loan')
            DailyLedger.objects.create(
                vendor=self.context['request'].user,
                entry_type='credit',
                amount=loan.document_charge,
                description=(
                    f"Document charge collected from {customer.name} "
                    f"for {loan_label} — Loan #{loan.id}"
                ),
                customer=customer,
                loan=loan,
                loan_type=customer.loan_type,
                source='document_charge',
                entry_date=loan.loan_date,
            )

        return customer


# ═══════════════════════════════════════════════════════════════════════
#  DAILY LEDGER SERIALIZERS
# ═══════════════════════════════════════════════════════════════════════

class DailyLedgerSerializer(serializers.ModelSerializer):
    customer_name  = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    loan_id        = serializers.SerializerMethodField()

    class Meta:
        model = DailyLedger
        fields = [
            'id', 'entry_type', 'amount', 'description',
            'loan_type', 'source', 'entry_date',
            'customer',
            'customer_name',
            'customer_phone',
            'loan_id',
            'emi_payment',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'source', 'created_at', 'updated_at',
                            'customer_name', 'customer_phone', 'loan_id']

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else ''

    def get_customer_phone(self, obj):
        return obj.customer.phone if obj.customer else ''

    def get_loan_id(self, obj):
        return obj.loan.id if obj.loan else None


class DailyLedgerCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DailyLedger
        fields = [
            'entry_type', 'amount', 'description',
            'loan_type', 'entry_date',
            'customer', 'loan',
        ]

    def validate_amount(self, value):
        if float(value) <= 0:
            raise serializers.ValidationError('Amount must be greater than 0.')
        return value


class DailyLedgerUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DailyLedger
        fields = ['description', 'amount', 'entry_date', 'entry_type']