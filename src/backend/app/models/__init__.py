"""Database models; importing this package registers migration metadata."""

from app.models.auth import (  # noqa: F401
    AdminCredential,
    AdminLoginBucket,
    AuthSession,
    KakaoIdentity,
    User,
)
from app.models.content import (  # noqa: F401
    GuideAuditEvent,
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
from app.models.recipe_nutrition import (  # noqa: F401
    RecipeComputedNutrition,
    RecipeIngredientFood,
)
from app.models.user_data import (  # noqa: F401
    MealCreateRequest,
    MealLog,
    MealLogItem,
    MealPlanEntry,
    RecommendationItem,
    RecommendationRun,
    SavedRecipe,
    SavedWelfareService,
    ShoppingCheck,
)
from app.models.welfare import WelfareNotice, WelfareRevision, WelfareService  # noqa: F401
