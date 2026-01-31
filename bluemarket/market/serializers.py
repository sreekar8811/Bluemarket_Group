from rest_framework import serializers
from django.contrib.auth.models import User
from django.db import transaction
from .models import CustomerProfile, VendorProfile, Product, Order, OrderItem, Payment, Shipping

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()
    role = serializers.ChoiceField(choices=[('vendor', 'Vendor'), ('customer', 'Customer')])

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

class CustomerProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    class Meta:
        model = CustomerProfile
        fields = '__all__'

class VendorProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    class Meta:
        model = VendorProfile
        fields = '__all__'

class ProductSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source='vendor.name', read_only=True)
    
    class Meta:
        model = Product
        fields = '__all__'
        read_only_fields = ['vendor', 'product_id']

class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    
    class Meta:
        model = OrderItem
        fields = ['product', 'quantity', 'price', 'product_name']
        read_only_fields = ['price'] 

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ['order', 'status']

class ShippingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shipping
        fields = '__all__'
        read_only_fields = ['order', 'status']

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)
    payment = PaymentSerializer(read_only=True)
    shipping = ShippingSerializer(read_only=True)
    
    class Meta:
        model = Order
        fields = ['order_id', 'order_date', 'total_amount', 'status', 'items', 'payment', 'shipping']
        read_only_fields = ['order_id', 'order_date', 'total_amount', 'status', 'customer']

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        request = self.context.get('request')
        customer = request.user.customer_profile
        
        # Atomic transaction for stock concurrency
        with transaction.atomic():
            total_amount = 0
            order_items = []
            
            # Select products for update to lock rows
            # We need to process items one by one or fetch them all with lock
            # Let's iterate and lock each product
            
            for item_data in items_data:
                product = Product.objects.select_for_update().get(pk=item_data['product'].product_id)
                quantity = item_data['quantity']
                
                if product.stock < quantity:
                    raise serializers.ValidationError(f"Insufficient stock for {product.name}")
                
                product.stock -= quantity
                product.save()
                
                price = product.price # Take current price
                item_total = price * quantity
                total_amount += item_total
                
                order_items.append({
                    'product': product,
                    'quantity': quantity,
                    'price': price
                })
            
            order = Order.objects.create(
                customer=customer,
                total_amount=total_amount,
                status='PENDING'
            )
            
            for item in order_items:
                OrderItem.objects.create(
                    order=order,
                    product=item['product'],
                    quantity=item['quantity'],
                    price=item['price']
                )
            
            # Create Payment (COD Default)
            Payment.objects.create(
                order=order,
                amount=total_amount,
                method='COD',
                status='PENDING'
            )
            
            # Create Shipping placeholder
            Shipping.objects.create(
                order=order,
                address="Default Address", # You might want to pass address in context or validated_data
                status='PENDING'
            )
            
        return order
