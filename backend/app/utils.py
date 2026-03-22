"""Shared utility functions for stats calculations."""


def calc_kd(pvp_kills: int, deaths: int) -> float:
    """Calculate K/D ratio (PvP kills / deaths). Returns kills if no deaths."""
    if deaths > 0:
        return round(pvp_kills / deaths, 2)
    return float(pvp_kills)


def calc_survival_rate(survived: int, total: int) -> float:
    """Calculate survival rate as percentage."""
    if total > 0:
        return round(survived / total * 100, 1)
    return 0.0
