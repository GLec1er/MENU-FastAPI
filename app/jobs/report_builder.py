from io import BytesIO
from typing import Any, Dict, List

import xlsxwriter


class InvalidSnapshot(Exception):
    """Снимок меню нельзя обработать: повторы бесполезны."""


def validate_snapshot(menus: Any) -> List[Dict[str, Any]]:
    try:
        if not isinstance(menus, list):
            raise TypeError("snapshot must be a list")
        for menu in menus:
            menu["title"], menu["description"]
            for submenu in menu["submenus"]:
                submenu["title"], submenu["description"]
                for dish in submenu["dishes"]:
                    dish["title"], dish["description"], dish["price"]
    except (KeyError, TypeError) as exc:
        raise InvalidSnapshot(str(exc)) from exc
    return menus


def build_menu_report(snapshot: Any) -> bytes:
    """Строит XLSX целиком в памяти; раскладка листа совпадает с прежней."""
    menus = validate_snapshot(snapshot)
    buffer = BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
    worksheet = workbook.add_worksheet()

    def make_format(size: int, italic: bool = False):
        fmt = workbook.add_format()
        fmt.set_bold()
        if italic:
            fmt.set_italic()
        fmt.set_font_size(size)
        fmt.set_text_wrap()
        fmt.set_align("vjustify")
        fmt.set_font_name("Times New Roman")
        return fmt

    set_format = make_format(12)
    dish_format = make_format(10, italic=True)
    dish_title_format = make_format(12, italic=True)

    worksheet.set_column(1, 4, 40, set_format)

    menu_row = 0
    menu_count = 1
    menu_gap = 1

    submenu_row = 1
    submenu_count = 1

    dish_row = 2
    dish_count = 1

    for menu in menus:
        worksheet.write(menu_row, 0, menu_count)
        worksheet.write(menu_row, 1, menu["title"])
        worksheet.write(menu_row, 2, menu["description"])
        menu_count += 1

        for submenu in menu["submenus"]:
            worksheet.write(submenu_row, 1, submenu_count)
            worksheet.write(submenu_row, 2, submenu["title"])
            worksheet.write(submenu_row, 3, submenu["description"])
            submenu_row += len(submenu["dishes"]) + 1
            submenu_count += 1
            menu_gap += len(submenu["dishes"])

            for dish in submenu["dishes"]:
                worksheet.write(dish_row, 2, dish_count, dish_title_format)
                worksheet.write(dish_row, 3, dish["title"], dish_title_format)
                worksheet.write(dish_row, 4, dish["description"], dish_format)
                worksheet.write(dish_row, 5, dish["price"], set_format)
                dish_row += 1
                dish_count += 1
            dish_count = 1
            dish_row += 1

        menu_row += len(menu["submenus"]) + menu_gap
        submenu_row += 1
        dish_row += 1
        submenu_count = 1
        dish_count = 1

    workbook.close()
    return buffer.getvalue()
