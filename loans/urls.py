from django.urls import path
from .views import (
    CustomerListCreateView, CustomerDetailView,
    GoldItemListCreateView, GoldItemDetailView,
    LoanListCreateView, LoanDetailView,
    RecordPaymentView, DashboardView,
    RemindersView, StatementView,
    LoanStatementPDFView,
    UploadPhotoView, GetPhotosView, DeletePhotoView,
    # ── Daily Ledger ──────────────────────────────────────────────────
    DailyLedgerListCreateView,
    DailyLedgerDetailView,
    DailyLedgerSummaryView,
    PendingDuesView,
)

urlpatterns = [
    # ── Customers ─────────────────────────────────────────────────────
    path('customers/',          CustomerListCreateView.as_view(), name='customer-list'),
    path('customers/<int:pk>/', CustomerDetailView.as_view(),     name='customer-detail'),

    # ── Gold Items ────────────────────────────────────────────────────
    path('customers/<int:customer_id>/gold-items/', GoldItemListCreateView.as_view(), name='gold-item-list'),
    path('gold-items/<int:pk>/',                    GoldItemDetailView.as_view(),     name='gold-item-detail'),

    # ── Loans ─────────────────────────────────────────────────────────
    path('customers/<int:customer_id>/loans/', LoanListCreateView.as_view(), name='loan-list'),
    path('loans/<int:pk>/',                    LoanDetailView.as_view(),     name='loan-detail'),

    # ── EMI Payment ───────────────────────────────────────────────────
    path('loans/<int:loan_id>/pay/<int:installment_number>/', RecordPaymentView.as_view(), name='record-payment'),

    # ── Statement JSON ────────────────────────────────────────────────
    path('loans/<int:loan_id>/statement/', StatementView.as_view(), name='statement'),

    # ── Statement PDF ─────────────────────────────────────────────────
    path('loans/<int:loan_id>/statement/pdf/', LoanStatementPDFView.as_view(), name='statement-pdf'),

    # ── Dashboard ─────────────────────────────────────────────────────
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

    # ── Reminders ─────────────────────────────────────────────────────
    path('reminders/', RemindersView.as_view(), name='reminders'),

    # ── Photos ────────────────────────────────────────────────────────
    path('customers/<int:customer_id>/photos/',
         GetPhotosView.as_view(), name='get-photos'),
    path('customers/<int:customer_id>/photos/upload/',
         UploadPhotoView.as_view(), name='upload-photo'),
    path('customers/<int:customer_id>/photos/<int:photo_id>/',
         DeletePhotoView.as_view(), name='delete-photo'),

    # ── Daily Ledger ──────────────────────────────────────────────────
    # GET  /api/loans/ledger/?date=2025-01-15          → entries for that date
    # GET  /api/loans/ledger/?start=2025-01-01&end=... → date range
    # GET  /api/loans/ledger/?entry_type=credit        → filter by type
    # POST /api/loans/ledger/                          → create manual entry
    path('ledger/',          DailyLedgerListCreateView.as_view(), name='ledger-list'),
    path('ledger/<int:pk>/', DailyLedgerDetailView.as_view(),     name='ledger-detail'),

    # GET  /api/loans/ledger/summary/?date=2025-01-15  → totals for that date
    # GET  /api/loans/ledger/summary/?start=...&end=... → range totals
    path('ledger/summary/',  DailyLedgerSummaryView.as_view(),    name='ledger-summary'),

    # GET  /api/loans/ledger/pending-dues/?date=2025-01-15
    # Returns customers with unpaid EMIs due on/before given date
    path('ledger/pending-dues/', PendingDuesView.as_view(),       name='pending-dues'),
]