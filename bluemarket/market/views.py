from rest_framework import viewsets, status, permissions, views
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate
from django.db.models import Sum, F
from .models import Product, Order, OrderItem, VendorProfile, CustomerProfile, Payment, Shipping
from .serializers import ProductSerializer, OrderSerializer, LoginSerializer, VendorProfileSerializer, CustomerProfileSerializer 
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from .forms import LoginForm, RegistrationForm, ProductForm, OrderForm
import uuid
import hmac
import hashlib
import json
import logging
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from .razorpay_client import get_razorpay_client

logger = logging.getLogger(__name__)

# We missed LoginSerializer in serializers.py, but we can handle it with standard serializer or manual parsing in view
# Let's add permissions first

class IsVendor(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and hasattr(request.user, 'vendor_profile')

class IsCustomer(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and hasattr(request.user, 'customer_profile')

class CustomLoginView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        role = request.data.get('role') # 'vendor' or 'customer'

        if not email or not password:
            return Response({'error': 'Please provide email and password'}, status=status.HTTP_400_BAD_REQUEST)

        # Login uses username in standard django, but we want email. 
        # We need to find user by email.
        try:
            from django.contrib.auth.models import User
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(username=user.username, password=password)

        if not user:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_400_BAD_REQUEST)

        # check role
        if role == 'vendor':
            if not hasattr(user, 'vendor_profile'):
               return Response({'error': 'User is not a vendor'}, status=status.HTTP_403_FORBIDDEN)
            redirect_url = '/vendor/dashboard'
        elif role == 'customer':
            if not hasattr(user, 'customer_profile'):
               return Response({'error': 'User is not a customer'}, status=status.HTTP_403_FORBIDDEN)
            redirect_url = '/customer/home'
        else:
            return Response({'error': 'Role required'}, status=status.HTTP_400_BAD_REQUEST)

        token, _ = Token.objects.get_or_create(user=user)
        
        return Response({
            'token': token.key,
            'redirect_url': redirect_url,
            'user_id': user.id,
            'role': role
        })

class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsVendor()]
        return [permissions.AllowAny()] # Public read

    def get_queryset(self):
        return Product.objects.all()

    def perform_create(self, serializer):
        serializer.save(vendor=self.request.user.vendor_profile)

class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'customer_profile'):
            return Order.objects.filter(customer=user.customer_profile)
        elif hasattr(user, 'vendor_profile'):
            # Vendors should see orders containing their products
            # This is complex because Order is per customer.
            # We can filter orders that have items belonging to this vendor.
            return Order.objects.filter(items__product__vendor=user.vendor_profile).distinct()
        return Order.objects.none()

    def create(self, request, *args, **kwargs):
        if not hasattr(request.user, 'customer_profile'):
            return Response({'error': 'Only customers can place orders'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)

class VendorDashboardView(views.APIView):
    permission_classes = [IsVendor]

    def get(self, request):
        vendor = request.user.vendor_profile
        products = Product.objects.filter(vendor=vendor)
        total_products = products.count()
        low_stock_products = products.filter(stock__lt=10).values('name', 'stock')
        
        # Calculate total sales for this vendor
        # Sum of (price * quantity) for items belonging to this vendor in COMPLETED orders ??
        # Or just all orders? Requirement says "view their own orders".
        # Let's give simple stats.
        
        my_order_items = OrderItem.objects.filter(product__vendor=vendor)
        total_sales = my_order_items.aggregate(total=Sum(F('quantity') * F('price')))['total'] or 0

        return Response({
            'total_sales': total_sales,
            'low_stock': low_stock_products
        })

# ==========================================
# FRONTEND VIEWS
# ==========================================

def register_view(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            email = form.cleaned_data['email']
            role = form.cleaned_data['role']
            
            try:
                from django.contrib.auth.models import User
                existing_user = User.objects.get(email=email)
                
                # Check if this user already has the OTHER role
                if role == 'vendor' and hasattr(existing_user, 'customer_profile'):
                    messages.error(request, 'You are already a customer. Please use new credentials to login for vendor.')
                    return redirect('register_page')
                if role == 'customer' and hasattr(existing_user, 'vendor_profile'):
                    messages.error(request, 'You are already a vendor. Please use new credentials to login for customer.')
                    return redirect('register_page')
                
                # If they already have the SAME role, let them try login
                if (role == 'vendor' and hasattr(existing_user, 'vendor_profile')) or \
                   (role == 'customer' and hasattr(existing_user, 'customer_profile')):
                    messages.warning(request, 'This account already exists. Please login.')
                    return redirect('login_page')
                    
            except User.DoesNotExist:
                pass # Proceed with registration

            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            # Generate temporary username if not provided
            if not user.username:
                user.username = form.cleaned_data['email']
            user.email = form.cleaned_data['email']
            user.save()

            if role == 'vendor':
                VendorProfile.objects.create(
                    user=user,
                    name=form.cleaned_data['name'],
                    email=form.cleaned_data['email'],
                    profile_image=form.cleaned_data.get('profile_image')
                )
            else:
                CustomerProfile.objects.create(
                    user=user,
                    name=form.cleaned_data['name'],
                    email=form.cleaned_data['email'],
                    profile_image=form.cleaned_data.get('profile_image')
                )
            
            messages.success(request, 'Registration successful. Please login.')
            return redirect('login_page')
    else:
        form = RegistrationForm()
    return render(request, 'market/register.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            
            try:
                from django.contrib.auth.models import User
                user_obj = User.objects.get(email=email)
            except User.DoesNotExist:
                messages.error(request, 'Invalid email or password')
                return redirect('login_page')

            user = authenticate(username=user_obj.username, password=password)
            
            if user:
                login(request, user)
                # Redirect based on profile
                if hasattr(user, 'vendor_profile'):
                    return redirect('vendor_dashboard_page')
                elif hasattr(user, 'customer_profile'):
                    return redirect('customer_home_page')
                else:
                    # Fallback for staff
                    return redirect('admin:index')
            else:
                messages.error(request, 'Invalid email or password')
    else:
        form = LoginForm()
    return render(request, 'market/login.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('login_page')

@login_required
def vendor_dashboard(request):
    if not hasattr(request.user, 'vendor_profile'):
        messages.error(request, 'You are not authorized to this page')
        return redirect('customer_home_page')
    
    products = Product.objects.filter(vendor=request.user.vendor_profile)
    return render(request, 'market/vendor_dashboard.html', {'products': products})

@login_required
def add_product(request):
    if not hasattr(request.user, 'vendor_profile'):
        messages.error(request, 'You are not authorized to this page')
        return redirect('customer_home_page')
        
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.vendor = request.user.vendor_profile
            product.save()
            messages.success(request, 'Product added successfully')
            return redirect('vendor_dashboard_page')
    else:
        form = ProductForm()
    return render(request, 'market/product_form.html', {'form': form, 'title': 'Add Product'})

@login_required
def edit_product(request, pk):
    if not hasattr(request.user, 'vendor_profile'):
        messages.error(request, 'You are not authorized to this page')
        return redirect('customer_home_page')
    product = get_object_or_404(Product, pk=pk, vendor=request.user.vendor_profile)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product updated')
            return redirect('vendor_dashboard_page')
    else:
        form = ProductForm(instance=product)
    return render(request, 'market/product_form.html', {'form': form, 'title': 'Edit Product'})

@login_required
def delete_product(request, pk):
    if not hasattr(request.user, 'vendor_profile'):
        messages.error(request, 'You are not authorized to this page')
        return redirect('customer_home_page')
    product = get_object_or_404(Product, pk=pk, vendor=request.user.vendor_profile)
    if request.method == 'POST':
        product.delete()
        messages.success(request, 'Product deleted')
        return redirect('vendor_dashboard_page')
    return render(request, 'market/product_confirm_delete.html', {'product': product})

@login_required
def customer_home(request):
    if not hasattr(request.user, 'customer_profile'):
        messages.error(request, 'You are not authorized to this page')
        return redirect('vendor_dashboard_page')
        
    products = Product.objects.all()
    return render(request, 'market/customer_home.html', {'products': products})

@login_required
@login_required
def buy_product_view(request, pk):
    if not hasattr(request.user, 'customer_profile'):
        messages.error(request, 'You are not authorized to this page')
        return redirect('vendor_dashboard_page')

    product = get_object_or_404(Product, pk=pk)
    
    if request.method == 'GET':
        quantity = int(request.GET.get('quantity', 1))
        # Ensure quantity is within stock
        if product.stock < quantity:
             messages.error(request, f'Not enough stock for {product.name}')
             return redirect('customer_home_page')
             
        total_price = product.price * quantity
        return render(request, 'market/checkout.html', {
            'product': product,
            'quantity': quantity,
            'total_price': total_price
        })

    if request.method == 'POST':
        qty = int(request.POST.get('quantity', 1))
        payment_method = request.POST.get('payment_method', 'COD')
        
        try:
            with transaction.atomic():
                product = Product.objects.select_for_update().get(pk=pk)
                if product.stock < qty:
                     messages.error(request, f'Not enough stock for {product.name}')
                     return redirect('customer_home_page')
                
                total_price = product.price * qty
                
                # If Razorpay, we don't reduce stock until payment is verified or we hold it
                # For simplicity in this demo, we create order first.
                
                order = Order.objects.create(
                    customer=request.user.customer_profile,
                    total_amount=total_price,
                    status='PENDING'
                )
                
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=qty,
                    price=product.price
                )
                
                payment = Payment.objects.create(
                    order=order,
                    amount=total_price,
                    method=payment_method,
                    status='PENDING'
                )

                # Create shipping record early to capture address
                address = request.POST.get('address', 'Default Address')
                Shipping.objects.create(
                    order=order,
                    address=address,
                    status='PENDING'
                )

                if payment_method == 'RAZORPAY':
                    client = get_razorpay_client()
                    razorpay_order_data = {
                        'amount': int(total_price * 100), # amount in paise
                        'currency': 'INR',
                        'receipt': str(order.order_id),
                        'payment_capture': 1
                    }
                    razorpay_order = client.order.create(data=razorpay_order_data)
                    payment.razorpay_order_id = razorpay_order['id']
                    payment.save()

                    return render(request, 'market/checkout.html', {
                        'product': product,
                        'quantity': qty,
                        'total_price': total_price,
                        'razorpay_order_id': razorpay_order['id'],
                        'razorpay_key_id': settings.RAZORPAY_KEY_ID,
                        'order_id': order.order_id
                    })

                # COD Flow
                product.stock -= qty
                product.save()
                
                order.status = 'SHIPPING'
                order.save()
                
                payment.status = 'SUCCESS'
                payment.save()
                
                messages.success(request, 'Order placed successfully and is now in shipping!')
                return redirect('customer_orders_page')
                
        except Exception as e:
            logger.error(f"Error in buy_product_view: {str(e)}")
            messages.error(request, f'Error placing order: {str(e)}')
            
    return redirect('customer_home_page')

@csrf_exempt
@login_required
def verify_razorpay_payment(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            razorpay_order_id = data.get('razorpay_order_id')
            razorpay_payment_id = data.get('razorpay_payment_id')
            razorpay_signature = data.get('razorpay_signature')

            client = get_razorpay_client()
            
            # Verify signature
            params_dict = {
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            }
            
            try:
                client.utility.verify_payment_signature(params_dict)
            except razorpay.errors.SignatureVerificationError:
                return JsonResponse({"status": "failed", "message": "Invalid signature"}, status=400)

            # Update database
            payment = Payment.objects.get(razorpay_order_id=razorpay_order_id)
            order = payment.order
            
            with transaction.atomic():
                payment.status = 'SUCCESS'
                payment.razorpay_payment_id = razorpay_payment_id
                payment.razorpay_signature = razorpay_signature
                payment.save()
                
                order.status = 'CONFIRMED'
                order.save()
                
                # Reduce stock now that payment is confirmed
                for item in order.items.all():
                    p = item.product
                    p.stock -= item.quantity
                    p.save()

                Shipping.objects.get_or_create(
                    order=order,
                    defaults={'address': "Address from Checkout", 'status': 'PENDING'}
                )

            return JsonResponse({"status": "success"})
        except Exception as e:
            logger.error(f"Error in verification: {str(e)}")
            return JsonResponse({"status": "failed", "message": str(e)}, status=500)
    return HttpResponse(status=405)

@csrf_exempt
def razorpay_webhook(request):
    payload = request.body
    sig = request.headers.get('X-Razorpay-Signature')
    secret = settings.RAZORPAY_WEBHOOK_SECRET

    try:
        client = get_razorpay_client()
        client.utility.verify_webhook_signature(payload, sig, secret)
    except razorpay.errors.SignatureVerificationError:
        return HttpResponse(status=400)

    data = json.loads(payload)
    event = data.get('event')

    if event == "payment.captured":
        payment_id = data['payload']['payment']['entity']['id']
        order_id = data['payload']['payment']['entity']['order_id']
        
        try:
            payment = Payment.objects.get(razorpay_order_id=order_id)
            if payment.status != 'SUCCESS':
                with transaction.atomic():
                    payment.status = 'SUCCESS'
                    payment.razorpay_payment_id = payment_id
                    payment.save()
                    
                    order = payment.order
                    order.status = 'CONFIRMED'
                    order.save()
                    
                    # Stock logic here if not already handled by verify_razorpay_payment
                    # For safety, check if stock already reduced
        except Payment.DoesNotExist:
             logger.error(f"Payment for order {order_id} not found in webhook")

    elif event == "payment.failed":
        # Handle failure
        pass

    return HttpResponse(status=200)

@login_required
def refund_order(request, order_id):
    # Stub for refund logic
    # client = get_razorpay_client()
    # client.payment.refund(payment_id, amount)
    messages.info(request, "Refund functionality is not implemented in this demo.")
    return redirect('customer_orders_page')

@login_required
def customer_orders(request):
    if not hasattr(request.user, 'customer_profile'):
        messages.error(request, 'You are not authorized to this page')
        return redirect('vendor_dashboard_page')
        
    orders = Order.objects.filter(customer=request.user.customer_profile).order_by('-order_date')
    return render(request, 'market/customer_orders.html', {'orders': orders})
@login_required
def profile_view(request):
    user = request.user
    if hasattr(user, 'vendor_profile'):
        profile = user.vendor_profile
        role = 'vendor'
        orders_done = Order.objects.filter(items__product__vendor=profile).distinct().count()
        context = {'profile': profile, 'role': role, 'orders_done': orders_done}
    elif hasattr(user, 'customer_profile'):
        profile = user.customer_profile
        role = 'customer'
        orders = Order.objects.filter(customer=profile).order_by('-order_date')
        context = {'profile': profile, 'role': role, 'orders': orders}
    else:
        # For staff/superusers without specific profiles
        context = {'profile': None, 'role': 'staff'}
    
    return render(request, 'market/profile.html', context)
@login_required
def cancel_order(request, pk):
    if not hasattr(request.user, 'customer_profile'):
        messages.error(request, 'You are not authorized to this page')
        return redirect('vendor_dashboard_page')
    
    order = get_object_or_404(Order, pk=pk, customer=request.user.customer_profile)
    
    if order.status not in ['PENDING', 'SHIPPING']:
        messages.error(request, 'This order cannot be cancelled.')
        return redirect('customer_orders_page')
    
    try:
        with transaction.atomic():
            # Get order items
            items = order.items.all()
            
            for item in items:
                # Use select_for_update for concurrency
                product = Product.objects.select_for_update().get(pk=item.product.pk)
                product.stock += item.quantity
                product.save()
            
            order.status = 'CANCELLED'
            order.save()
            
            # Update payment status if exists
            if hasattr(order, 'payment'):
                order.payment.status = 'FAILED'
                order.payment.save()
            
            messages.success(request, f'Order {str(order.order_id)[:8]} cancelled and stock restored.')
    except Exception as e:
        messages.error(request, f'Error cancelling order: {str(e)}')
    
    return redirect('customer_orders_page')
