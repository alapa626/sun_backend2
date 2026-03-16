from django.urls import path
from .views import (
    CustomerListCreateView, CustomerDetailView,
    LoanListCreateView, LoanDetailView,
    RecordPaymentView, DashboardView,
    RemindersView, StatementView,
)

urlpatterns = [
    # Customers
    path('customers/', CustomerListCreateView.as_view(), name='customer-list'),
    path('customers/<int:pk>/', CustomerDetailView.as_view(), name='customer-detail'),

    # Loans (nested under customer)
    path('customers/<int:customer_id>/loans/', LoanListCreateView.as_view(), name='loan-list'),
    path('loans/<int:pk>/', LoanDetailView.as_view(), name='loan-detail'),

    # EMI Payment
    path('loans/<int:loan_id>/pay/<int:installment_number>/', RecordPaymentView.as_view(), name='record-payment'),

    # Statement
    path('loans/<int:loan_id>/statement/', StatementView.as_view(), name='statement'),

    # Dashboard
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

    # Reminders
    path('reminders/', RemindersView.as_view(), name='reminders'),
]