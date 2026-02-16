"""Conftest for auth unit tests — ensures all SQLAlchemy models are loaded."""

# Import all models so ForeignKey references between tables can be resolved.
# Without this, importing auth models fails because ModelAccess references 'models.id'.
from yaai.server.models import auth as _auth_models  # noqa: F401
from yaai.server.models import inference as _inference_models  # noqa: F401
from yaai.server.models import job as _job_models  # noqa: F401
from yaai.server.models import model as _model_models  # noqa: F401
