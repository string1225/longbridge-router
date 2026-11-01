from router.app import create_app
from router.config import Settings

app = create_app(Settings.from_env())
