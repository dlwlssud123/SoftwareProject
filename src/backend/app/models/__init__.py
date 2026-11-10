"""Database models; importing this package registers migration metadata."""

from app.models.auth import AuthSession, User  # noqa: F401
from app.models.content import (  # noqa: F401
    LifeGuide,
    MealFacility,
    SeasonalFood,
    SeasonalIngredient,
    SeasonalRecipeLink,
)
from app.models.jobs import JobRun  # noqa: F401
from app.models.profile import Profile  # noqa: F401
from app.models.public_data import (  # noqa: F401
    DataImportRun,
    Food,
    FoodRevision,
    Recipe,
    RecipeIngredient,
    RecipeRevision,
    RecipeStep,
)
from app.models.user_data import (  # noqa: F401
    MealLog,
    MealLogItem,
    MealPlanEntry,
    SavedRecipe,
    SavedWelfareService,
)
from app.models.welfare import WelfareNotice, WelfareRevision, WelfareService  # noqa: F401
