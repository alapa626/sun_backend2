from django.urls import path
from .views import (
    CustomerListCreateView, CustomerDetailView,
    GoldItemListCreateView, GoldItemDetailView,
    LoanListCreateView, LoanDetailView,
    RecordPaymentView, DashboardView,
    RemindersView, StatementView,
)

urlpatterns = [
    # ── Customers ────────────────────────────────────────────────────
    # GET  ?loan_type=vehicle|gold   filter by type
    # GET  ?q=search                 search by name/phone/vehicle
    path('customers/',              CustomerListCreateView.as_view(), name='customer-list'),
    path('customers/<int:pk>/',     CustomerDetailView.as_view(),     name='customer-detail'),

    # ── Gold Items ────────────────────────────────────────────────────
    path('customers/<int:customer_id>/gold-items/', GoldItemListCreateView.as_view(), name='gold-item-list'),
    path('gold-items/<int:pk>/',                    GoldItemDetailView.as_view(),     name='gold-item-detail'),

    # ── Loans ─────────────────────────────────────────────────────────
    path('customers/<int:customer_id>/loans/', LoanListCreateView.as_view(), name='loan-list'),
    path('loans/<int:pk>/',                    LoanDetailView.as_view(),     name='loan-detail'),

    # ── EMI Payment ───────────────────────────────────────────────────
    path('loans/<int:loan_id>/pay/<int:installment_number>/', RecordPaymentView.as_view(), name='record-payment'),

    # ── Statement ─────────────────────────────────────────────────────
    path('loans/<int:loan_id>/statement/', StatementView.as_view(), name='statement'),

    # ── Dashboard  (?loan_type=vehicle|gold|all) ──────────────────────
    path('dashboard/',  DashboardView.as_view(),  name='dashboard'),

    # ── Reminders ─────────────────────────────────────────────────────
    path('reminders/', RemindersView.as_view(), name='reminders'),
]