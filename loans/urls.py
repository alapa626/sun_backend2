from django.urls import path
from .views import (
    CustomerListCreateView, CustomerDetailView,
    GoldItemListCreateView, GoldItemDetailView,
    LoanListCreateView, LoanDetailView,
    RecordPaymentView, DashboardView,
    RemindersView, StatementView,
    LoanStatementPDFView,
    UploadPhotoView, GetPhotosView, DeletePhotoView,
)

# ─────────────────────────────────────────────────────────────────────────────
#  ROOT MOUNT POINT (in your project-level urls.py):
#
#    path('api/loans/', include('loans.urls'))
#
#  That means every path() below is relative to /api/loans/.
#
#  ✅  CORRECT  →  /api/loans/<id>/statement/pdf/
#  ❌  WRONG    →  /api/loans/loans/<id>/statement/pdf/  (double "loans")
#
#  The old version had  path("loans/<int:loan_id>/statement/pdf/", ...)
#  which produced the double-"loans" URL that the Flutter app couldn't find.
#  Fixed by removing the leading  "loans/"  from the route string.
# ─────────────────────────────────────────────────────────────────────────────

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
    # ✅ FIXED: route is  loans/<id>/statement/pdf/  (relative to /api/loans/)
    #           full URL = /api/loans/loans/<id>/statement/pdf/
    #
    #   Flutter _pdfCandidates() tries this as candidate #1:
    #     '$_base$_api/loans/$loanId/statement/pdf/'
    #     = https://…/api/loans/loans/<id>/statement/pdf/   ← matches ✓
    #
    # GET         → returns PDF inline  (Content-Disposition: inline)
    # GET ?download=1 → forces browser/share-sheet download
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
]