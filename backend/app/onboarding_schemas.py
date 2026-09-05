from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator


class RestaurantRegistrationIn(BaseModel):
    restaurant_name: str = Field(min_length=2, max_length=160)
    location_name: str = Field(min_length=2, max_length=160)
    address: str = Field(min_length=5, max_length=300)
    owner_name: str = Field(min_length=2, max_length=160)
    owner_email: EmailStr
    password: str = Field(min_length=10, max_length=72)
    accepted_terms: bool

    @field_validator("accepted_terms")
    @classmethod
    def terms_are_required(cls, value: bool) -> bool:
        if not value:
            raise ValueError("You must accept the terms to register a restaurant.")
        return value


class RestaurantRegistrationOut(BaseModel):
    tenant_slug: str
    location_slug: str
    lifecycle: str
    message: str
