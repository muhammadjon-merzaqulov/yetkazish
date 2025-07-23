from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
import datetime

class Category(models.Model):
    """Mahsulot kategoriyalari"""
    name = models.CharField(max_length=100, verbose_name="Kategoriya nomi")
    description = models.TextField(blank=True, verbose_name="Tavsif")
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True, verbose_name="Faol")

    class Meta:
        verbose_name = "Kategoriya"
        verbose_name_plural = "Kategoriyalar"
        ordering = ['name']

    def __str__(self):
        return self.name

class Product(models.Model):
    """Mahsulotlar"""
    category = models.ForeignKey(Category, on_delete=models.CASCADE, verbose_name="Kategoriya")
    name = models.CharField(max_length=200, verbose_name="Mahsulot nomi")
    description = models.TextField(blank=True, verbose_name="Tavsif")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Narxi (so'm)")
    image = models.ImageField(upload_to='products/', blank=True, null=True, verbose_name="Rasm")
    is_available = models.BooleanField(default=True, verbose_name="Mavjud")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Mahsulot"
        verbose_name_plural = "Mahsulotlar"
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name} - {self.price:,} so'm"

class Customer(models.Model):
    """Mijozlar"""
    telegram_id = models.BigIntegerField(unique=True, verbose_name="Telegram ID")
    full_name = models.CharField(max_length=200, verbose_name="To'liq ismi")
    phone_number = models.CharField(max_length=20, verbose_name="Telefon raqami")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mijoz"
        verbose_name_plural = "Mijozlar"

    def __str__(self):
        return f"{self.full_name} ({self.phone_number})"

class Order(models.Model):
    """Buyurtmalar"""
    STATUS_CHOICES = [
        ('yangi', 'Yangi'),
        ('tasdiqlangan', 'Tasdiqlangan'),
        ('tayor', 'Tayor'),
        ('yolda', 'Yo\'lda'),
        ('yetkazildi', 'Yetkazildi'),
        ('bekor_qilingan', 'Bekor qilingan'),
    ]

    PAYMENT_CHOICES = [
        ('naqd', 'Naqd'),
        ('karta', 'Karta'),
        ('online', 'Online to\'lov'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name="Mijoz")
    telegram_user_id = models.BigIntegerField(verbose_name="Telegram User ID", null=True, blank=True)
    order_number = models.CharField(max_length=20, unique=True, verbose_name="Buyurtma raqami")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='yangi', verbose_name="Holati")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='naqd', verbose_name="To'lov usuli")
    
    # Manzil ma'lumotlari
    latitude = models.FloatField(verbose_name="Kenglik", null=True, blank=True)
    longitude = models.FloatField(verbose_name="Uzunlik", null=True, blank=True)
    address = models.TextField(blank=True, null=True, verbose_name="Manzil")
    
    # Narxlar
    products_total = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Mahsulotlar summasi")
    delivery_cost = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Yetkazib berish narxi")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Umumiy summa")
    
    # Vaqt ma'lumotlari
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan vaqti")
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name="Tasdiqlangan vaqti")
    ready_at = models.DateTimeField(null=True, blank=True, verbose_name="Tayor bo'lgan vaqti")
    delivered_at = models.DateTimeField(null=True, blank=True, verbose_name="Yetkazilgan vaqti")
    
    # Telegram message ID'lar
    chef_message_id = models.BigIntegerField(null=True, blank=True)
    user_message_id = models.BigIntegerField(null=True, blank=True)
    courier_message_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Buyurtma"
        verbose_name_plural = "Buyurtmalar"
        ordering = ['-created_at']

    def __str__(self):
        return f"Buyurtma #{self.order_number} - {self.customer.full_name}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            # Buyurtma raqamini avtomatik generatsiya qilish
            last_order = Order.objects.order_by('-id').first()
            if last_order:
                self.order_number = str(int(last_order.order_number) + 1)
            else:
                self.order_number = "1"
        super().save(*args, **kwargs)

class OrderItem(models.Model):
    """Buyurtma elementlari"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items', verbose_name="Buyurtma")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name="Mahsulot")
    quantity = models.PositiveIntegerField(verbose_name="Miqdori")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Narxi")
    total = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Jami")

    class Meta:
        verbose_name = "Buyurtma elementi"
        verbose_name_plural = "Buyurtma elementlari"

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

    def save(self, *args, **kwargs):
        self.total = self.quantity * self.price
        super().save(*args, **kwargs)

class OrderStatusHistory(models.Model):
    """Buyurtma holati tarixi"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='status_history')
    old_status = models.CharField(max_length=20, verbose_name="Eski holat")
    new_status = models.CharField(max_length=20, verbose_name="Yangi holat")
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="O'zgartirgan")
    changed_at = models.DateTimeField(auto_now_add=True, verbose_name="O'zgartirilgan vaqt")
    notes = models.TextField(blank=True, verbose_name="Izohlar")

    class Meta:
        verbose_name = "Holat tarixi"
        verbose_name_plural = "Holat tarixi"
        ordering = ['-changed_at']

    def __str__(self):
        return f"{self.order.order_number}: {self.old_status} -> {self.new_status}"

class BotSettings(models.Model):
    """Telegram bot sozlamalari"""
    service_start_time = models.TimeField(
        verbose_name="Xizmat boshlanish vaqti",
        default=datetime.time(10, 0),
        help_text="Bot qaysi vaqtdan buyurtma qabul qilishni boshlaydi"
    )
    service_end_time = models.TimeField(
        verbose_name="Xizmat tugash vaqti",
        default=datetime.time(22, 0),
        help_text="Bot qaysi vaqtgacha buyurtma qabul qiladi"
    )
    delivery_base_cost = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=5000,
        verbose_name="Yetkazib berish boshlang'ich narxi (so'm)",
        help_text="Har qanday masofada minimal yetkazib berish narxi",
        validators=[MinValueValidator(0)]
    )
    delivery_cost_per_extra_km_block = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=6000,
        verbose_name="Har km uchun qo'shimcha narx (so'm)",
        help_text="Birinchi kilometrdan keyin har km uchun qo'shimcha to'lov",
        validators=[MinValueValidator(0)]
    )
    delivery_max_radius_km = models.FloatField(
        default=10.0,
        verbose_name="Maksimal yetkazib berish radiusi (km)",
        help_text="Bu masofadan uzoqroqqa yetkazib berish yo'q",
        validators=[MinValueValidator(1.0), MaxValueValidator(100.0)]
    )
    broadcast_message_text = models.TextField(
        blank=True, 
        null=True,
        verbose_name="E'lon matni",
        help_text="Barcha foydalanuvchilarga yuborilishi mumkin bo'lgan e'lon matni"
    )
    last_broadcast_sent_at = models.DateTimeField(
        null=True, 
        blank=True,
        verbose_name="Oxirgi e'lon yuborilgan vaqt"
    )

    class Meta:
        verbose_name = "Bot Sozlamalari"
        verbose_name_plural = "Bot Sozlamalari"

    def __str__(self):
        return f"Bot Sozlamalari ({self.service_start_time.strftime('%H:%M')} - {self.service_end_time.strftime('%H:%M')})"

    def save(self, *args, **kwargs):
        # Ensure only one instance exists
        if not self.pk and BotSettings.objects.exists():
            raise ValueError("Faqat bitta Bot Sozlamalari obyekti bo'lishi mumkin!")
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        """Get or create the single settings instance"""
        settings, created = cls.objects.get_or_create(
            pk=1,
            defaults={
                'service_start_time': datetime.time(10, 0),
                'service_end_time': datetime.time(22, 0),
                'delivery_base_cost': 5000,
                'delivery_cost_per_extra_km_block': 6000,
                'delivery_max_radius_km': 10.0
            }
        )
        return settings
