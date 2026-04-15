from sqlalchemy import Column, Integer, BigInteger, String, ForeignKey, Enum, Float, DateTime, Boolean
from sqlalchemy.orm import relationship
from database.base import Base
import datetime
import enum

class UserRole(enum.Enum):
    PENDING = "kutilmoqda" 
    CLIENT = "mijoz"
    LOGIST = "logist"
    DISPATCHER = "dispetcher"
    DRIVER = "haydovchi"
    CASHIER = "kassir"
    FOUNDER = "founder"

class OrderStatus(enum.Enum):
    NEW = "YANGI"
    DISPATCHER_ASSIGNED = "DISPETCHERGA BIRIKTIRILDI"
    DRIVER_ASSIGNED = "HAYDOVCHI BIRIKTIRILDI"
    ARRIVED_A = "A NUQTAGA KELDI"
    LOADED = "YUK ORTILDI"
    ON_WAY = "YO'LDA"
    ARRIVED_B = "B NUQTADA"
    DIDOX_PENDING = "DIDOX TASDIQDA"
    UNLOADED = "YUK TUSHIRILDI"
    PAID = "TO'LANGAN"
    COMPLETED = "YAKUNLANDI"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.PENDING, nullable=False)
    full_name = Column(String)
    phone = Column(String, nullable=True) 
    card_number = Column(String, nullable=True) # Driver karta raqami

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    logist_id = Column(Integer, ForeignKey("users.id"))
    dispatcher_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    status = Column(Enum(OrderStatus), default=OrderStatus.NEW)
    cargo_description = Column(String)
    point_a = Column(String)
    point_b = Column(String)
    
    client_phone = Column(String) 
    vehicle_number = Column(String, nullable=True) 
    
    sale_price = Column(Float) 
    cost_price = Column(Float) 
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class OrderLocation(Base):
    __tablename__ = "order_locations"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    latitude = Column(Float)
    longitude = Column(Float)
    is_confirmed = Column(Boolean, default=False) 
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class OrderMedia(Base):
    __tablename__ = "order_media"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    media_type = Column(String) 
    file_path = Column(String) 
    stage = Column(String)