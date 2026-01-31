from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProductViewSet, OrderViewSet, CustomLoginView, VendorDashboardView,
    login_view, register_view, logout_view, vendor_dashboard, 
    add_product, edit_product, delete_product, customer_home, 
    buy_product_view, customer_orders, profile_view, cancel_order,
    verify_razorpay_payment, razorpay_webhook, refund_order
)

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'orders', OrderViewSet, basename='order')

urlpatterns = [
    path('customer/order/<str:pk>/cancel/', cancel_order, name='cancel_order_page'),
    path('', include(router.urls)),
    # API endpoints
    path('api/login/', CustomLoginView.as_view(), name='api_login'),
    path('api/vendor/dashboard/', VendorDashboardView.as_view(), name='api_vendor_dashboard'),

    # Frontend endpoints
    path('login/', login_view, name='login_page'),
    path('register/', register_view, name='register_page'),
    path('logout/', logout_view, name='logout_page'),
    
    path('vendor/dashboard/', vendor_dashboard, name='vendor_dashboard_page'),
    path('vendor/products/add/', add_product, name='add_product_page'),
    path('vendor/products/<uuid:pk>/edit/', edit_product, name='edit_product_page'),
    path('vendor/products/<uuid:pk>/delete/', delete_product, name='delete_product_page'),
    
    path('customer/dashboard/', customer_home, name='customer_home_page'),
    path('customer/buy/<uuid:pk>/', buy_product_view, name='buy_product_page'),
    path('customer/orders/', customer_orders, name='customer_orders_page'),
    path('profile/', profile_view, name='profile_page'),
    
    # Razorpay URLs
    path('razorpay/verify/', verify_razorpay_payment, name='verify_razorpay_payment'),
    path('razorpay/webhook/', razorpay_webhook, name='razorpay_webhook'),
    path('refund/<uuid:order_id>/', refund_order, name='refund_order'),
]
