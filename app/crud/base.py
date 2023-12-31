from typing import Any, List

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class CRUDBase:
    def __init__(self, model):
        self.model = model

    async def get_one(
        self,
        obj_id: str,
        session: AsyncSession,
    ) -> Any:
        db_obj = await session.execute(
            select(self.model).where(
                self.model.id == obj_id,
            ),
        )
        return db_obj.scalars().first()

    async def get_many(
        self,
        session: AsyncSession,
    ) -> list[Any]:
        db_objs = await session.execute(select(self.model))
        return db_objs.scalars().all()

    async def create(
        self,
        obj_in: Any,
        session: AsyncSession,
    ) -> Any:
        obj_in_data = obj_in.dict()
        db_obj = self.model(**obj_in_data)
        session.add(db_obj)
        await session.commit()
        await session.refresh(db_obj)
        return db_obj

    async def update(
        self,
        db_obj: Any,
        obj_in: Any,
        session: AsyncSession,
    ) -> Any:
        obj_data = jsonable_encoder(db_obj)
        update_data = obj_in.dict(exclude_unset=True)

        for field in obj_data:
            if field in update_data:
                setattr(db_obj, field, update_data[field])
        session.add(db_obj)
        await session.commit()
        await session.refresh(db_obj)
        return db_obj

    async def delete(
        self,
        db_obj: Any,
        session: AsyncSession,
    ) -> Any:
        await session.delete(db_obj)
        await session.commit()
        return db_obj

    async def read_all_subobjects(
        self,
        obj_id: str,
        session: AsyncSession,
    ) -> list[Any]:
        subobjects = await session.execute(
            select(self.model).where(self.model.parent_id == obj_id),
        )
        return subobjects.scalars().all()

    async def create_subobject(
        self,
        obj_id: str,
        obj_in: Any,
        session: AsyncSession,
    ) -> Any:
        new_data = obj_in.dict()
        db_subobj = self.model(**new_data, parent_id=obj_id)
        session.add(db_subobj)
        await session.commit()
        await session.refresh(db_subobj)
        return db_subobj

    async def create_from_dict(
        self,
        id: str,
        title: str,
        description: str,
        session: AsyncSession,
    ) -> Any:
        db_obj = self.model(id=id, title=title, description=description)
        session.add(db_obj)
        await session.commit()
        await session.refresh(db_obj)
        return db_obj
