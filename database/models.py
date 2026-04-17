import enum
import datetime
from sqlalchemy import Column, Integer, String, BigInteger, Float, DateTime, ForeignKey, Enum as SqlEnum
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

# --- ENUMLAR ---

class UserRole(enum.Enum):
    FOUNDER = "FOUNDER"
    LOGIST = "LOGIST"
    DISPATCHER = "DISPATCHER"
    DRIVER = "DRIVER"
    CASHIER = "CASHIER"
    PENDING = "PENDING"

class OrderStatus(enum.Enum):
    NEW = "NEW"
    DISPATCHER_ASSIGNED = "DISPATCHER_ASSIGNED"
    DRIVER_ASSIGNED = "DRIVER_ASSIGNED"
    LOADING = "LOADING"
    ON_WAY = "ON_WAY"
    DIDOX_PENDING = "DIDOX_PENDING"
    UNLOADED = "UNLOADED"
    PAID = "PAID"
    COMPLETED = "COMPLETED"  # BU YERGA QO'SHILDI
    CANCELLED = "CANCELLED"

# --- FOYDALANUVCHILAR JADVALI ---

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    full_name = Column(String)
    username = Column(String, nullable=True) 
    phone = Column(String, nullable=True)
    role = Column(SqlEnum(UserRole), default=UserRole.PENDING)
    card_number = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    orders_as_logist = relationship("Order", foreign_keys="Order.logist_id", back_populates="logist")
    orders_as_dispatcher = relationship("Order", foreign_keys="Order.dispatcher_id", back_populates="dispatcher")
    orders_as_driver = relationship("Order", foreign_keys="Order.driver_id", back_populates="driver")

# --- BUYURTMALAR JADVALI ---

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    logist_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    dispatcher_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    driver_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)

    status = Column(SqlEnum(OrderStatus), default=OrderStatus.NEW)
    cargo_description = Column(String, nullable=False)
    point_a = Column(String, nullable=False)
    point_b = Column(String, nullable=False)
    client_phone = Column(String, nullable=False)
    vehicle_number = Column(String, nullable=True)
    
    sale_price = Column(Float, nullable=False, default=0.0)
    cost_price = Column(Float, nullable=False, default=0.0)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    # Xatolikni oldini olish uchun updated_at qo'shildi
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    logist = relationship("User", foreign_keys=[logist_id], back_populates="orders_as_logist")
    dispatcher = relationship("User", foreign_keys=[dispatcher_id], back_populates="orders_as_dispatcher")
    driver = relationship("User", foreign_keys=[driver_id], back_populates="orders_as_driver")
    
    locations = relationship("OrderLocation", back_populates="order", cascade="all, delete-orphan")

# --- LOKATSIYALAR VA MEDIA ---

class OrderLocation(Base):
    __tablename__ = "order_locations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    address = Column(String, nullable=True)
    sent_at = Column(DateTime, default=datetime.datetime.utcnow)
    order = relationship("Order", back_populates="locations")

class OrderMedia(Base):
    __tablename__ = "order_media"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    file_id = Column(String, nullable=False) 
    file_type = Column(String) 
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    order = relationship("Order")