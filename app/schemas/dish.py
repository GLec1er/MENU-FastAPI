from pydantic import BaseModel, validator


class DishBase(BaseModel):
    title: str
    description: str
    price: str

    @validator("price")
    def check_price(cls, value: str) -> str:
        if not float(value):
            raise ValueError("price must be a number")
        value = format(float(value), ".2f")
        return value


class DishCreate(DishBase):
    submenu_id: str

    class Config:
        schema_extra = {
            "example": {
                "title": "My dish 1",
                "description": "My dish description 1",
                "price": "12.50",
            },
        }


class DishUpdate(DishCreate):
    class Config:
        schema_extra = {}


class DishOut(DishBase):
    id: str

    class Config:
        orm_mode = True
