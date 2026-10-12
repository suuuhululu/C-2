"""색상·블록 종류별 공급 슬롯 순환에 공통으로 사용하는 계산."""
from app.contracts import _integer


def next_supply_slot(slot, slot_count=6):
    _integer(slot_count, 1, 6, "supply.slot_count")
    _integer(slot, 1, slot_count, "supply.slot")
    return slot % slot_count + 1
