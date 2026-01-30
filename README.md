# Blue Market - E-commerce Marketplace

Blue Market is a Django-based e-commerce platform where customers can browse and purchase products from various vendors. It features a robust order management system and integrated payments via Razorpay and COD.

## Tech Stack
- **Backend:** Django
- **Database:** PostgreSQL
- **Payments:** Razorpay (Integrated in Test Mode)
- **Frontend:** Vanilla HTML/CSS with Django Templates

---

## Prerequisites
- Python 3.8+
- PostgreSQL
- Razorpay Account (for Test API Keys)

---

## Getting Started

### 1. Clone the project
```bash
git clone <repository-url>
cd "Blue market"
```

### 2. Setup Virtual Environment
```bash
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux/macOS
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Database Configuration
Ensure PostgreSQL is running. Open `bluemarket/settings.py` and update the `DATABASES` section with your credentials:
```python
DATABASES = {
    "default": {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME':'bluemarket',
        'USER':'your_username',
        'PASSWORD':'your_password',
        'HOST':'localhost',
        'PORT':'5432',
    }
}
```

### 5. Environment Variables
Create a file named `.env` in the `bluemarket/` directory (where `manage.py` is):
```env
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxxxxxx
RAZORPAY_WEBHOOK_SECRET=your_secret_optional
```

### 6. Run Migrations
```bash
cd bluemarket
python manage.py makemigrations
python manage.py migrate
```

### 7. Run the Server
```bash
python manage.py runserver
```

---

## How to Test Razorpay Payments
1. Register as a **Customer**.
2. Go to the dashboard and select a product.
3. Choose **Razorpay** as the payment method.
4. Click **Confirm Order**.
5. Use [Razorpay Test Card Details](https://razorpay.com/docs/payments/payments/test-card-details/) in the popup.
6. Upon successful payment, your order will be marked as **CONFIRMED**.

## Project Structure
- `market/`: Main application logic (Models, Views, Templates).
- `bluemarket/`: Project configuration (Settings, URLs).
- `media/`: Uploaded product and profile images.
- `requirements.txt`: Python package list.
