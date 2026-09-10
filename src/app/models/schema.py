from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Time
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class SystemSettings(Base):
    __tablename__ = "system_settings"
    id = Column(Integer, primary_key=True, index=True)
    unifi_host = Column(String, default="https://192.168.1.1")
    unifi_port = Column(Integer, default=443)
    unifi_username = Column(String, default="")
    unifi_password = Column(String, default="")
    unifi_site = Column(String, default="default")
    pihole_url_1 = Column(String, default="http://192.168.1.2")
    pihole_api_key_1 = Column(String, default="")
    pihole_url_2 = Column(String, default="")
    pihole_api_key_2 = Column(String, default="")
    timezone = Column(String, default="America/New_York")

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    domains = Column(String) # Comma-separated list of domains

    quotas = relationship("ProfileQuota", back_populates="category", cascade="all, delete")

class Profile(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    ip_address = Column(String, unique=True, index=True)
    mac_address = Column(String, unique=True, index=True)
    curfew_start = Column(Time, nullable=True) # E.g., 20:30
    curfew_end = Column(Time, nullable=True)   # E.g., 07:00
    curfew_enforcement = Column(String, default="station_block") # station_block or traffic_rule
    is_blocked = Column(Boolean, default=False)
    audit_only = Column(Boolean, default=False)

    quotas = relationship("ProfileQuota", back_populates="profile", cascade="all, delete")
    daily_usage = relationship("DailyUsage", back_populates="profile", cascade="all, delete")

class ProfileQuota(Base):
    __tablename__ = "profile_quotas"
    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"))
    category_id = Column(Integer, ForeignKey("categories.id"))
    daily_limit_minutes = Column(Integer, default=60)
    enforcement = Column(String, default="traffic_rule")
    traffic_rule_id = Column(String, nullable=True) # UniFi traffic rule ID

    profile = relationship("Profile", back_populates="quotas")
    category = relationship("Category", back_populates="quotas")

class DailyUsage(Base):
    __tablename__ = "daily_usage"
    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, index=True) # Format: YYYY-MM-DD
    profile_id = Column(Integer, ForeignKey("profiles.id"))
    category_id = Column(Integer, ForeignKey("categories.id"))
    active_minutes = Column(Integer, default=0)
    is_blocked = Column(Boolean, default=False)

    profile = relationship("Profile", back_populates="daily_usage")
    category = relationship("Category")

class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    profile_id = Column(Integer, nullable=True)
    action = Column(String) # 'BLOCK', 'UNBLOCK', 'RESET', 'ERROR'
    target = Column(String) # Category name or 'STATION'
    reason = Column(String)
