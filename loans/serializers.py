from rest_framework import serializers
from django.utils import timezone
from .models import Customer, Loan, EmiPayment
from .utils import generate_emi_schedule


class EmiPaymentSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    fine_amount = serializers.SerializerMethodField()

    class Meta:
        model = EmiPayment
        fields = [
            'id', 'installment_number', 'due_date',
            'emi_amount', 'paid_amount', 'is_paid',
            'paid_date', 'balance', 'is_overdue', 'fine_amount',
        ]

    def get_balance(self, obj):
        if obj.is_paid:
            return 0
        return max(0, float(obj.emi_amount) - float(obj.paid_amount))

    def get_is_overdue(self, obj):
        if obj.is_paid:
            return False
        return obj.due_date < timezone.now().date()

    def get_fine_amount(self, obj):
        """Return fine amount from parent loan if this EMI is overdue and unpaid."""
        if obj.is_paid:
            return 0
        if obj.due_date < timezone.now().date():
            return float(obj.loan.fine_amount)
        return 0


class LoanSerializer(serializers.ModelSerializer):
    emi_payments = EmiPaymentSerializer(many=True, read_only=True)
    total_interest = serializers.ReadOnlyField()
    total_payable = serializers.ReadOnlyField()
    emi = serializers.ReadOnlyField()
    total_paid = serializers.ReadOnlyField()
    remaining = serializers.ReadOnlyField()
    is_active = serializers.ReadOnlyField()
    paid_count = serializers.ReadOnlyField()

    class Meta:
        model = Loan
        fields = [
            'id', 'customer', 'loan_amount', 'interest_rate',
            'tenure_months', 'loan_date',
            'fine_amount',                          # ✅ NEW
            'guarantor_name', 'guarantor_phone', 'guarantor_address',
            'guarantor_aadhaar', 'guarantor_relation',
            'total_interest', 'total_payable', 'emi',
            'total_paid', 'remaining', 'is_active', 'paid_count',
            'emi_payments', 'created_at',
        ]
        read_only_fields = ['customer', 'created_at']


class LoanCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Loan
        fields = [
            'loan_amount', 'interest_rate', 'tenure_months', 'loan_date',
            'fine_amount',                          # ✅ NEW
            'guarantor_name', 'guarantor_phone', 'guarantor_address',
            'guarantor_aadhaar', 'guarantor_relation',
        ]


class CustomerListSerializer(serializers.ModelSerializer):
    active_loans_count = serializers.SerializerMethodField()
    total_loan_amount = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id', 'name', 'phone', 'address', 'aadhaar',
            'vehicle_type', 'vehicle_model', 'vehicle_number',
            'active_loans_count', 'total_loan_amount', 'created_at',
        ]

    def get_active_loans_count(self, obj):
        return sum(1 for loan in obj.loans.all() if loan.is_active)

    def get_total_loan_amount(self, obj):
        return sum(float(loan.loan_amount) for loan in obj.loans.all())


class CustomerDetailSerializer(serializers.ModelSerializer):
    loans = LoanSerializer(many=True, read_only=True)

    class Meta:
        model = Customer
        fields = [
            'id', 'name', 'phone', 'address', 'aadhaar',
            'vehicle_type', 'vehicle_model', 'vehicle_number',
            'loans', 'created_at',
        ]


class CustomerCreateSerializer(serializers.ModelSerializer):
    loan_amount = serializers.DecimalField(max_digits=12, decimal_places=2, write_only=True)
    interest_rate = serializers.DecimalField(max_digits=5, decimal_places=2, write_only=True, default=0)
    tenure_months = serializers.IntegerField(write_only=True, default=12)
    loan_date = serializers.DateField(write_only=True, required=False)
    fine_amount = serializers.DecimalField(             # ✅ NEW
        max_digits=10, decimal_places=2,
        write_only=True, default=0, required=False
    )
    guarantor_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    guarantor_phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    guarantor_address = serializers.CharField(write_only=True, required=False, allow_blank=True)
    guarantor_aadhaar = serializers.CharField(write_only=True, required=False, allow_blank=True)
    guarantor_relation = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Customer
        fields = [
            'id', 'name', 'phone', 'address', 'aadhaar',
            'vehicle_type', 'vehicle_model', 'vehicle_number',
            'loan_amount', 'interest_rate', 'tenure_months', 'loan_date',
            'fine_amount',                          # ✅ NEW
            'guarantor_name', 'guarantor_phone', 'guarantor_address',
            'guarantor_aadhaar', 'guarantor_relation',
        ]

    def create(self, validated_data):
        loan_fields = {
            'loan_amount': validated_data.pop('loan_amount'),
            'interest_rate': validated_data.pop('interest_rate', 0),
            'tenure_months': validated_data.pop('tenure_months', 12),
            'loan_date': validated_data.pop('loan_date', timezone.now().date()),
            'fine_amount': validated_data.pop('fine_amount', 0),   # ✅ NEW
            'guarantor_name': validated_data.pop('guarantor_name', ''),
            'guarantor_phone': validated_data.pop('guarantor_phone', ''),
            'guarantor_address': validated_data.pop('guarantor_address', ''),
            'guarantor_aadhaar': validated_data.pop('guarantor_aadhaar', ''),
            'guarantor_relation': validated_data.pop('guarantor_relation', ''),
        }
        customer = Customer.objects.create(**validated_data)
        loan = Loan.objects.create(customer=customer, **loan_fields)
        generate_emi_schedule(loan)
        return customer