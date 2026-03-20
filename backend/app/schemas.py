from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# --- Runner ---

class RunnerCreate(BaseModel):
    name: str
    icon: Optional[str] = None
    notes: Optional[str] = None

class RunnerUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    notes: Optional[str] = None

class RunnerOut(BaseModel):
    id: int
    name: str
    icon: Optional[str]
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# --- Weapon ---

class WeaponCreate(BaseModel):
    name: str
    weapon_type: Optional[str] = None
    notes: Optional[str] = None

class WeaponOut(BaseModel):
    id: int
    name: str
    weapon_type: Optional[str]
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# --- Loadout ---

class LoadoutCreate(BaseModel):
    name: str
    runner_id: Optional[int] = None
    primary_weapon: Optional[str] = None
    secondary_weapon: Optional[str] = None
    mods: Optional[list] = None
    gear: Optional[list] = None
    notes: Optional[str] = None

class LoadoutUpdate(BaseModel):
    name: Optional[str] = None
    runner_id: Optional[int] = None
    primary_weapon: Optional[str] = None
    secondary_weapon: Optional[str] = None
    mods: Optional[list] = None
    gear: Optional[list] = None
    notes: Optional[str] = None

class LoadoutOut(BaseModel):
    id: int
    name: str
    runner_id: Optional[int]
    primary_weapon: Optional[str]
    secondary_weapon: Optional[str]
    mods: Optional[list]
    gear: Optional[list]
    notes: Optional[str]
    screenshot_path: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# --- Run ---

class RunCreate(BaseModel):
    runner_id: Optional[int] = None
    loadout_id: Optional[int] = None
    map_name: Optional[str] = None
    date: Optional[datetime] = None
    survived: Optional[bool] = None
    kills: int = 0
    combatant_eliminations: int = 0
    runner_eliminations: int = 0
    deaths: int = 0
    assists: int = 0
    crew_revives: int = 0
    loot_extracted: Optional[list] = None
    loot_value_total: float = 0.0
    duration_seconds: Optional[int] = None
    squad_size: Optional[int] = None
    squad_members: Optional[list] = None
    notes: Optional[str] = None
    session_id: Optional[int] = None

class RunUpdate(BaseModel):
    runner_id: Optional[int] = None
    loadout_id: Optional[int] = None
    map_name: Optional[str] = None
    date: Optional[datetime] = None
    survived: Optional[bool] = None
    kills: Optional[int] = None
    deaths: Optional[int] = None
    assists: Optional[int] = None
    crew_revives: Optional[int] = None
    loot_extracted: Optional[list] = None
    loot_value_total: Optional[float] = None
    duration_seconds: Optional[int] = None
    squad_size: Optional[int] = None
    squad_members: Optional[list] = None
    notes: Optional[str] = None
    viewed: Optional[bool] = None
    session_id: Optional[int] = None

class RunOut(BaseModel):
    id: int
    runner_id: Optional[int]
    loadout_id: Optional[int]
    map_name: Optional[str]
    date: datetime
    survived: Optional[bool]
    kills: int
    combatant_eliminations: int
    runner_eliminations: int
    deaths: int
    assists: int
    crew_revives: int
    loot_extracted: Optional[list]
    loot_value_total: float
    duration_seconds: Optional[int]
    squad_size: Optional[int]
    squad_members: Optional[list]
    screenshot_path: Optional[str]
    notes: Optional[str]
    session_id: Optional[int]
    spawn_location: Optional[str] = None
    primary_weapon: Optional[str] = None
    secondary_weapon: Optional[str] = None
    killed_by: Optional[str] = None
    killed_by_damage: Optional[int] = None
    grade: Optional[str] = None
    summary: Optional[str] = None
    shell_name: Optional[str] = None
    player_gamertag: Optional[str] = None
    recording_path: Optional[str] = None
    viewed: Optional[bool] = None
    created_at: datetime

    class Config:
        from_attributes = True


# --- Session ---

class SessionCreate(BaseModel):
    notes: Optional[str] = None

class SessionOut(BaseModel):
    id: int
    started_at: datetime
    ended_at: Optional[datetime]
    notes: Optional[str]
    runs: list[RunOut] = []

    class Config:
        from_attributes = True


# --- Spawn Point ---

class SpawnPointCreate(BaseModel):
    run_id: Optional[int] = None
    map_name: str
    spawn_location: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    notes: Optional[str] = None

class SpawnPointOut(BaseModel):
    id: int
    run_id: Optional[int]
    map_name: str
    spawn_location: Optional[str]
    x: Optional[float]
    y: Optional[float]
    game_coord_x: Optional[float] = None
    game_coord_y: Optional[float] = None
    screenshot_path: Optional[str]
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class ParsedSpawnScreenshot(BaseModel):
    map_name: Optional[str] = None
    spawn_location: Optional[str] = None
    landmarks_visible: Optional[list[str]] = None
    raw_text: Optional[str] = None
    confidence: Optional[str] = None


# --- Screenshot Parse Result ---

class ParsedScreenshot(BaseModel):
    survived: Optional[bool] = None
    kills: int = 0
    combatant_eliminations: int = 0
    runner_eliminations: int = 0
    deaths: int = 0
    assists: int = 0
    map_name: Optional[str] = None
    duration_seconds: Optional[int] = None
    loot_extracted: Optional[list] = None
    loot_value_total: float = 0.0
    runner_name: Optional[str] = None
    primary_weapon: Optional[str] = None
    secondary_weapon: Optional[str] = None
    items_collected: Optional[int] = None
    items_auto_vaulted: Optional[int] = None
    bullet_balance: Optional[float] = None
    raw_text: Optional[str] = None
    confidence: Optional[str] = None


# --- Stats ---

class MapTime(BaseModel):
    map_name: str
    total_seconds: int = 0

class OverviewStats(BaseModel):
    total_runs: int = 0
    total_survived: int = 0
    survival_rate: float = 0.0
    total_kills: int = 0
    total_deaths: int = 0
    total_assists: int = 0
    total_revives: int = 0
    kd_ratio: float = 0.0
    total_loot_value: float = 0.0
    avg_kills_per_run: float = 0.0
    avg_loot_per_run: float = 0.0
    favorite_map: Optional[str] = None
    favorite_runner: Optional[str] = None
    favorite_shell: Optional[str] = None
    favorite_weapon: Optional[str] = None
    favorite_squad_mate: Optional[str] = None
    favorite_squad_mate_runs: int = 0
    total_time_seconds: int = 0
    time_by_map: list[MapTime] = []
