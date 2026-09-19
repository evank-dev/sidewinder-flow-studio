import uvicorn
from app.core.config import settings
from app.core.app_factory import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
