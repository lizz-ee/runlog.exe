from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, Float, Text, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import relationship

from .database import Base


class Runner(Base):
    __tablename__ = "runners"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    icon = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    loadouts = relationship("Loadout", back_populates="runner")
    runs = relationship("Run", back_populates="runner")


class Weapon(Base):
    __tablename__ = "weapons"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    weapon_type = Column(String(50), nullable=True)  # primary, secondary, heavy
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Loadout(Base):
    __tablename__ = "loadouts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    runner_id = Column(Integer, ForeignKey("runners.id"), nullable=True)
    primary_weapon = Column(String(100), nullable=True)
    secondary_weapon = Column(String(100), nullable=True)
    heavy_weapon = Column(String(100), nullable=True)
    mods = Column(JSON, nullable=True)
    gear = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    screenshot_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    runner = relationship("Runner", back_populates="loadouts")
    runs = relationship("Run", back_populates="loadout")


class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    runner_id = Column(Integer, ForeignKey("runners.id"), nullable=True)
    loadout_id = Column(Integer, ForeignKey("loadouts.id"), nullable=True)
    map_name = Column(String(100), nullable=True)
    date = Column(DateTime, default=datetime.utcnow)
    survived = Column(Boolean, nullable=True)
    kills = Column(Integer, default=0)
    combatant_eliminations = Column(Integer, default=0)
    runner_eliminations = Column(Integer, default=0)
    deaths = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    crew_revives = Column(Integer, default=0)
    loot_extracted = Column(JSON, nullable=True)
    loot_value_total = Column(Float, default=0.0)
    duration_seconds = Column(Integer, nullable=True)
    squad_size = Column(Integer, nullable=True)
    squad_members = Column(JSON, nullable=True)
    screenshot_path = Column(String(500), nullable=True)
    primary_weapon = Column(String(100), nullable=True)
    secondary_weapon = Column(String(100), nullable=True)
    killed_by = Column(String(100), nullable=True)
    killed_by_damage = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    runner = relationship("Runner", back_populates="runs")
    loadout = relationship("Loadout", back_populates="runs")
    session = relationship("Session", back_populates="runs")
    spawn_point = relationship("SpawnPoint", back_populates="run", uselist=False)

    @property
    def spawn_location(self) -> str | None:
        return self.spawn_point.spawn_location if self.spawn_point else None

    @property
    def shell_name(self) -> str | None:
        return self.runner.name if self.runner else None


class SpawnPoint(Base):
    __tablename__ = "spawn_points"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=True)
    map_name = Column(String(100), nullable=False)
    spawn_location = Column(String(200), nullable=True)
    spawn_region = Column(String(100), nullable=True)
    x = Column(Float, nullable=True)  # % position on map image (0-100)
    y = Column(Float, nullable=True)  # % position on map image (0-100)
    compass_bearing = Column(String(20), nullable=True)  # e.g. "S 195" — direction facing on spawn
    screenshot_path = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("Run", back_populates="spawn_point")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    runs = relationship("Run", back_populates="session")
