from pydantic import BaseModel
from typing import List, Optional
from datetime import time, datetime

class SettingsCreateUpdate(BaseModel):
    unifi_host: str
    unifi_port: int
    unifi_username: str
    unifi_password: str
    unifi_site: str
    pihole_url_1: str
    pihole_api_key_1: str
    pihole_url_2: str
    pihole_api_key_2: str
    timezone: str

class CategoryBase(BaseModel):
    name: str
    domains: str

class CategoryCreate(CategoryBase):
    pass

class CategoryResponse(CategoryBase):
    id: int
    class Config:
        from_attributes = True

class ProfileQuotaBase(BaseModel):
    category_id: int
    daily_limit_minutes: int
    enforcement: str
    traffic_rule_id: Optional[str] = None

class ProfileQuotaCreate(ProfileQuotaBase):
    pass

class ProfileQuotaResponse(ProfileQuotaBase):
    id: int
    profile_id: int
    class Config:
        from_attributes = True

class ProfileBase(BaseModel):
    name: str
    ip_address: str
    mac_address: str
    curfew_start: Optional[time] = None
    curfew_end: Optional[time] = None
    curfew_enforcement: str = "station_block"
    audit_only: bool = False

class ProfileCreate(ProfileBase):
    pass

class ProfileResponse(ProfileBase):
    id: int
    is_blocked: bool
    quotas: List[ProfileQuotaResponse] = []
    class Config:
        from_attributes = True

class DashboardUsage(BaseModel):
    profile_id: int
    profile_name: str
    category_id: int
    category_name: str
    active_minutes: int
    limit_minutes: int
    is_blocked: bool

class AuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    profile_id: Optional[int]
    action: str
    target: str
    reason: str
    class Config:
        from_attributes = True
