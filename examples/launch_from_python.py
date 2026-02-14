"""Launch Boulder from Python."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("boulder.api.main:app", host="0.0.0.0", port=8050, reload=True)
