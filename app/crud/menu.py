from typing import Any, Dict, List

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.crud.base import CRUDBase
from app.models import Menu, SubMenu


class MenuCrud(CRUDBase):
    async def select_all_data(self, session: AsyncSession) -> list[dict[str, Any]]:
        result = await session.scalars(
            select(self.model).options(
                joinedload(self.model.submenus).joinedload(SubMenu.dishes)
            )
        )
        menus = result.unique().all()
        menu_data = jsonable_encoder(menus)
        return menu_data


menu_crud = MenuCrud(Menu)
