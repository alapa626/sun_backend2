from django.urls import path
from .views import (
    CustomerListCreateView, CustomerDetailView,
    GoldItemListCreateView, GoldItemDetailView,
    LoanListCreateView, LoanDetailView,
    RecordPaymentView, DashboardView,
    RemindersView, StatementView,
    UploadPhotoView, GetPhotosView, DeletePhotoView,  # ✅ FIX: added DeletePhotoView
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

    # ── Statement ─────────────────────────────────────────────────────
    path('loans/<int:loan_id>/statement/', StatementView.as_view(), name='statement'),

    # ── Dashboard ─────────────────────────────────────────────────────
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

    # ── Reminders ─────────────────────────────────────────────────────
    path('reminders/', RemindersView.as_view(), name='reminders'),

    # ── Photos ────────────────────────────────────────────────────────
    # GET  — list all photos for a customer (returns list with id + photoUrl)
    path('customers/<int:customer_id>/photos/',
         GetPhotosView.as_view(), name='get-photos'),

    # POST — upload a new photo (multipart: photo_type + photo file)
    path('customers/<int:customer_id>/photos/upload/',
         UploadPhotoView.as_view(), name='upload-photo'),

    # ✅ NEW: DELETE — remove a single photo by its DB id
    #         Flutter's delete button uses PhotoService.deletePhoto(photoId)
    #         which calls DELETE /customers/<id>/photos/<photo_id>/
    path('customers/<int:customer_id>/photos/<int:photo_id>/',
         DeletePhotoView.as_view(), name='delete-photo'),
]