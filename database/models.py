import enum
import datetime
from sqlalchemy import Column, Integer, String, BigInteger, Float, DateTime, ForeignKey, Enum as SqlEnum
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class UserRole(enum.Enum):
    FOUNDER    = "FOUNDER"
    LOGIST     = "LOGIST"
    DISPATCHER = "DISPATCHER"
    DRIVER     = "DRIVER"
    CASHIER    = "CASHIER"
    CLIENT     = "CLIENT"
    PENDING    = "PENDING"


class OrderStatus(enum.Enum):
    NEW                 = "NEW"
    DISPATCHER_ASSIGNED = "DISPATCHER_ASSIGNED"
    DRIVER_ASSIGNED     = "DRIVER_ASSIGNED"
    ARRIVED_A           = "ARRIVED_A"
    LOADING             = "LOADING"
    ON_WAY              = "ON_WAY"
    ARRIVED_B           = "ARRIVED_B"
    DIDOX_TASDIQDA      = "DIDOX_TASDIQDA"
    UNLOADED            = "UNLOADED"
    PAID                = "PAID"
    COMPLETED           = "COMPLETED"
    CANCELLED           = "CANCELLED"


class User(Base):
    __tablename__ = "users"

    id          = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    full_name   = Column(String)
    username    = Column(String, nullable=True)
    phone       = Column(String, nullable=True)
    role        = Column(SqlEnum(UserRole), default=UserRole.PENDING)
    card_number = Column(String, nullable=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)

    orders_as_logist     = relationship("Order", foreign_keys="Order.logist_id",     back_populates="logist_rel")
    orders_as_dispatcher = relationship("Order", foreign_keys="Order.dispatcher_id", back_populates="dispatcher_rel")
    orders_as_driver     = relationship("Order", foreign_keys="Order.driver_id",     back_populates="driver_rel")


class Order(Base):
    __tablename__ = "orders"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    logist_id         = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    dispatcher_id     = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    driver_id         = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    status            = Column(SqlEnum(OrderStatus), default=OrderStatus.NEW)
    cargo_description = Column(String, nullable=False)

    # A nuqta: nom (matn) + joylashuv
    point_a           = Column(String, nullable=False)
    point_a_lat       = Column(Float,  nullable=True)
    point_a_lon       = Column(Float,  nullable=True)    
    point_b           = Column(String, nullable=False)          # matn manzil
    point_b_lat       = Column(Float,  nullable=True)
    point_b_lon       = Column(Float,  nullable=True)

    client_phone      = Column(String, nullable=False)
    vehicle_number    = Column(String, nullable=True)
    sale_price        = Column(Float,  nullable=False, default=0.0)
    cost_price        = Column(Float,  nullable=False, default=0.0)
    created_at        = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at        = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    logist_rel     = relationship("User", foreign_keys=[logist_id],     back_populates="orders_as_logist")
    dispatcher_rel = relationship("User", foreign_keys=[dispatcher_id], back_populates="orders_as_dispatcher")
    driver_rel     = relationship("User", foreign_keys=[driver_id],     back_populates="orders_as_driver")
    locations      = relationship("OrderLocation", back_populates="order", cascade="all, delete-orphan")
    media          = relationship("OrderMedia",    back_populates="order", cascade="all, delete-orphan")


class OrderLocation(Base):
    __tablename__ = "order_locations"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    order_id  = Column(Integer, ForeignKey("orders.id"), nullable=False)
    latitude  = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    sent_at   = Column(DateTime, default=datetime.datetime.utcnow)
    order     = relationship("Order", back_populates="locations")


class OrderMedia(Base):
    __tablename__ = "order_media"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    order_id   = Column(Integer, ForeignKey("orders.id"), nullable=False)
    file_id    = Column(String, nullable=False)
    file_type  = Column(String)   # "photo" | "video"
    stage      = Column(String)   # "loading_a" | "arrived_b" | "unloading_b"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    order      = relationship("Order", back_populates="media")
