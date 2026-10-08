from . import (carton_count, carton_damage, colour, missing_components,
               other_quality, quantity, sku, unit_damage, units_per_carton, variant)

CHECKS = {
    "sku_identity": sku.run,
    "colour": colour.run,
    "variant": variant.run,
    "quantity": quantity.run,
    "carton_count": carton_count.run,
    "carton_damage": carton_damage.run,
    "unit_damage": unit_damage.run,
    "units_per_carton": units_per_carton.run,
    "missing_components": missing_components.run,
    "other_quality": other_quality.run,
}