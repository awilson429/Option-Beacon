from fastapi import HTTPException

from api.services import SUPPORTED_SYMBOLS


def normalized_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if value not in SUPPORTED_SYMBOLS:
        raise HTTPException(status_code=404, detail=f"Unsupported symbol: {value}")
    return value
