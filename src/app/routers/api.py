from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from datetime import datetime

from ..models.database import get_db
from ..models.schema import SystemSettings, Category, Profile, ProfileQuota, DailyUsage, AuditLog
from ..models.pydantic_schemas import (
    SettingsCreateUpdate, CategoryCreate, CategoryResponse,
    ProfileCreate, ProfileResponse, ProfileQuotaCreate, DashboardUsage, AuditLogResponse
)
from ..services.unifi import UnifiClient
from sqlalchemy.orm import selectinload

from ..models.auth import verify_credentials

router = APIRouter(prefix="/api", dependencies=[Depends(verify_credentials)])

# --- System Settings ---
@router.get("/settings", response_model=SettingsCreateUpdate)
async def get_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalars().first()
    if not settings:
        settings = SystemSettings()
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings

@router.put("/settings", response_model=SettingsCreateUpdate)
async def update_settings(settings_in: SettingsCreateUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalars().first()
    if not settings:
        settings = SystemSettings(**settings_in.model_dump())
        db.add(settings)
    else:
        for k, v in settings_in.model_dump().items():
            setattr(settings, k, v)
    await db.commit()
    return settings

# --- Categories ---
@router.get("/categories", response_model=List[CategoryResponse])
async def get_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category))
    return result.scalars().all()

@router.post("/categories", response_model=CategoryResponse)
async def create_category(cat_in: CategoryCreate, db: AsyncSession = Depends(get_db)):
    cat = Category(**cat_in.model_dump())
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat

@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category).where(Category.id == cat_id))
    cat = result.scalars().first()
    if not cat:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(cat)
    await db.commit()
    return {"status": "deleted"}

# --- Profiles ---
@router.get("/profiles", response_model=List[ProfileResponse])
async def get_profiles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Profile).options(selectinload(Profile.quotas)))
    return result.scalars().all()

@router.post("/profiles", response_model=ProfileResponse)
async def create_profile(prof_in: ProfileCreate, db: AsyncSession = Depends(get_db)):
    prof = Profile(**prof_in.model_dump())
    db.add(prof)
    await db.commit()
    await db.refresh(prof)
    return prof

@router.delete("/profiles/{prof_id}")
async def delete_profile(prof_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Profile).where(Profile.id == prof_id))
    prof = result.scalars().first()
    if not prof:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(prof)
    await db.commit()
    return {"status": "deleted"}

# --- Profile Quotas ---
@router.post("/profiles/{prof_id}/quotas", response_model=ProfileResponse)
async def add_quota(prof_id: int, quota_in: ProfileQuotaCreate, db: AsyncSession = Depends(get_db)):
    quota = ProfileQuota(profile_id=prof_id, **quota_in.model_dump())
    db.add(quota)
    await db.commit()
    # Return updated profile
    result = await db.execute(select(Profile).options(selectinload(Profile.quotas)).where(Profile.id == prof_id))
    return result.scalars().first()

@router.delete("/quotas/{quota_id}")
async def delete_quota(quota_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProfileQuota).where(ProfileQuota.id == quota_id))
    quota = result.scalars().first()
    if not quota:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(quota)
    await db.commit()
    return {"status": "deleted"}

# --- Dashboard & Logs ---
@router.get("/dashboard", response_model=List[DashboardUsage])
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    today_str = datetime.now().strftime("%Y-%M-%d")

    # We need to join Profile, ProfileQuota, and DailyUsage to build the dashboard view
    profiles_result = await db.execute(select(Profile).options(selectinload(Profile.quotas)))
    profiles = profiles_result.scalars().all()

    categories_result = await db.execute(select(Category))
    categories = {c.id: c.name for c in categories_result.scalars().all()}

    dashboard_data = []

    for prof in profiles:
        for quota in prof.quotas:
            usage_result = await db.execute(
                select(DailyUsage)
                .where(DailyUsage.profile_id == prof.id)
                .where(DailyUsage.category_id == quota.category_id)
                .where(DailyUsage.date == today_str)
            )
            usage = usage_result.scalars().first()

            dashboard_data.append(DashboardUsage(
                profile_id=prof.id,
                profile_name=prof.name,
                category_id=quota.category_id,
                category_name=categories.get(quota.category_id, "Unknown"),
                active_minutes=usage.active_minutes if usage else 0,
                limit_minutes=quota.daily_limit_minutes,
                is_blocked=usage.is_blocked if usage else False
            ))

    return dashboard_data

@router.get("/logs", response_model=List[AuditLogResponse])
async def get_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit))
    return result.scalars().all()

# --- Manual Overrides ---
@router.post("/overrides/unblock-station/{prof_id}")
async def manual_unblock_station(prof_id: int, db: AsyncSession = Depends(get_db)):
    # 1. Update DB
    result = await db.execute(select(Profile).where(Profile.id == prof_id))
    prof = result.scalars().first()
    if not prof:
        raise HTTPException(404, "Profile not found")

    prof.is_blocked = False
    log = AuditLog(profile_id=prof.id, action="UNBLOCK", target="STATION", reason="Manual Override")
    db.add(log)

    # 2. Update UniFi
    settings_result = await db.execute(select(SystemSettings).limit(1))
    settings = settings_result.scalars().first()
    if settings and settings.unifi_host:
        unifi = UnifiClient(settings.unifi_host, settings.unifi_port, settings.unifi_username, settings.unifi_password, settings.unifi_site)
        await unifi.unblock_station(prof.mac_address)
        await unifi.close()

    await db.commit()
    return {"status": "success"}

@router.post("/overrides/reset-usage/{prof_id}/{cat_id}")
async def reset_usage(prof_id: int, cat_id: int, db: AsyncSession = Depends(get_db)):
    today_str = datetime.now().strftime("%Y-%M-%d")
    result = await db.execute(
        select(DailyUsage)
        .where(DailyUsage.profile_id == prof_id)
        .where(DailyUsage.category_id == cat_id)
        .where(DailyUsage.date == today_str)
    )
    usage = result.scalars().first()

    if usage:
        usage.active_minutes = 0
        usage.is_blocked = False
        db.add(AuditLog(profile_id=prof_id, action="RESET", target=f"Category {cat_id}", reason="Manual Override"))

        # Unblock in UniFi if it was a traffic rule
        quota_result = await db.execute(select(ProfileQuota).where(ProfileQuota.profile_id == prof_id).where(ProfileQuota.category_id == cat_id))
        quota = quota_result.scalars().first()

        if quota and quota.enforcement == "traffic_rule" and quota.traffic_rule_id:
            settings_result = await db.execute(select(SystemSettings).limit(1))
            settings = settings_result.scalars().first()
            if settings and settings.unifi_host:
                unifi = UnifiClient(settings.unifi_host, settings.unifi_port, settings.unifi_username, settings.unifi_password, settings.unifi_site)
                await unifi.set_traffic_rule(quota.traffic_rule_id, enabled=False)
                await unifi.close()

        await db.commit()

    return {"status": "success"}
